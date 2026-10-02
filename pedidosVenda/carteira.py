"""
Carteira do vendedor: positivação, ciclo de recompra e mix por linha (02/10/2026).

Fonte: notas faturadas do SGA com o MESMO filtro de venda válida das comissões
(`comissoes/clientes_inativos.py`): NFSIT = 1, GALMPRODVENDA = 'S', flags 1 e 25
da natureza, série 8 (acerto) fora. A "linha" do produto é o grupo de
almoxarifado (GRUPOALMOXARIFADO), o mesmo agrupamento do catálogo do pedido.

O vendedor é quem faturou (NFREP), como nas comissões — não o CLIREP do cadastro.
"""
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from django.core.cache import cache

from . import erp

JANELA_DIAS = 395          # 13 meses: o mês atual + 12 completos
INATIVO_DIAS = 180         # sem compra há mais que isso: inativo (a tela de inativos das comissões cuida)
FOLGA_CICLO = 1.25         # passou 25% do intervalo normal sem comprar ⇒ atrasado
LINHA_PERDIDA_DIAS = 120   # linha que o cliente comprava e não compra há 4 meses
CACHE_SEG = 600

_SQL = """
    SELECT NF.NFCLI cliente, CAST(NF.NFDATA AS DATE) data, NF.NFREP repcod,
           G.GALMCOD linha_cod, G.GALMNOME linha,
           SUM(INF.INFTOTAL) valor,
           SUM(INF.INFQUANT * CASE WHEN E.ESTQPESO > 0 THEN E.ESTQPESO ELSE 1 END / 1000.0) tn
    FROM NOTAFISCAL NF
    JOIN ITEMNOTAFISCAL INF ON INF.INFNFCOD = NF.NFCOD
    JOIN NATUREZAOPERACAO N ON N.NOPCOD = INF.INFNOP
    JOIN ESTOQUE E ON E.ESTQCOD = INF.INFESTQ
    JOIN GRUPOALMOXARIFADO G ON G.GALMCOD = E.ESTQGALM
    WHERE NF.NFSIT = 1 AND G.GALMPRODVENDA = 'S'
      AND SUBSTRING(N.NOPFLAGNF, 1, 1) = 'S' AND SUBSTRING(N.NOPFLAGNF, 25, 1) = 'N'
      AND NF.NFSNF NOT IN (8)
      AND NF.NFDATA >= :desde
      {filtro}
    GROUP BY NF.NFCLI, CAST(NF.NFDATA AS DATE), NF.NFREP, G.GALMCOD, G.GALMNOME
"""

_SQL_CLIENTES = """
    SELECT C.CLICOD cod, C.CLINOME nome, C.CLINOMEFANT fantasia,
           C.CLICELULAR celular, C.CLITELEFONE telefone,
           (SELECT CI.CIDNOME + '-' + ES.ESTUF FROM CIDADE CI JOIN ESTADO ES ON ES.ESTCOD = CI.CIDEST
             WHERE CI.CIDCOD = C.CLICIDADE) cidade
    FROM CLIENTE C WHERE C.CLICOD IN ({cods})
"""


def _linhas_erp(repcods: list[int] | None, desde: date) -> list[dict]:
    filtro = ''
    if repcods is not None:
        reps = erp._inteiros(repcods) or [-1]
        filtro = f"AND NF.NFREP IN ({','.join(str(r) for r in reps)})"
    linhas = erp._limpar(erp._rows(_SQL.format(filtro=filtro), desde=desde))
    for l in linhas:  # CAST AS DATE chega como date, que o _limpar não converte
        if not isinstance(l['data'], str):
            l['data'] = l['data'].isoformat()
    return linhas


def _clientes_erp(cods: list[int]) -> dict[int, dict]:
    saida = {}
    cods = erp._inteiros(cods)
    for i in range(0, len(cods), 900):  # IN do SQL Server: lotes
        lote = cods[i:i + 900]
        for c in erp._limpar(erp._rows(_SQL_CLIENTES.format(cods=','.join(map(str, lote))))):
            # CLICELULAR costuma vir com 13 bytes nulos (LEN 13, sem dígito): o
            # COALESCE do SQL o escolhia e o telefone sumia. Vale o 1º com dígitos.
            fones = [str(f or '').replace('\x00', '').strip() for f in (c.pop('celular'), c['telefone'])]
            c['telefone'] = next((f for f in fones if sum(ch.isdigit() for ch in f) >= 8), '')
            saida[c['cod']] = c
    return saida


def _mes(d: date) -> str:
    return f'{d.year:04d}-{d.month:02d}'


def calcular(linhas: list[dict], hoje: date, cadastro: dict[int, dict]) -> dict:
    """Puro (sem ERP), para testar: `linhas` = uma por cliente × dia × linha de produto."""
    ini_mes = hoje.replace(day=1)
    ini_mes_ant = (ini_mes - timedelta(days=1)).replace(day=1)
    # Mês anterior até o mesmo dia: comparar o mês corrente com o anterior inteiro é injusto.
    corte_mes_ant = min(ini_mes_ant + timedelta(days=hoje.day - 1), ini_mes - timedelta(days=1))
    desde_12m = ini_mes - timedelta(days=365)

    por_cli: dict[int, dict] = {}
    meses_cli: dict[str, set] = defaultdict(set)
    for l in linhas:
        d = date.fromisoformat(l['data'])
        c = por_cli.setdefault(l['cliente'], {
            'datas': set(), 'linhas': {}, 'valor_12m': 0.0, 'tn_12m': 0.0, 'valor_mes': 0.0, 'reps': defaultdict(float),
        })
        c['datas'].add(d)
        c['reps'][l['repcod']] += float(l['valor'] or 0)
        lin = c['linhas'].setdefault(l['linha_cod'], {'cod': l['linha_cod'], 'nome': l['linha'], 'ultima': d, 'valor': 0.0})
        lin['ultima'] = max(lin['ultima'], d)
        if d >= desde_12m:
            lin['valor'] += float(l['valor'] or 0)
            c['valor_12m'] += float(l['valor'] or 0)
            c['tn_12m'] += float(l['tn'] or 0)
        if d >= ini_mes:
            c['valor_mes'] += float(l['valor'] or 0)
        meses_cli[_mes(d)].add(l['cliente'])

    clientes = []
    for cod, c in por_cli.items():
        datas = sorted(c['datas'])
        ultima = datas[-1]
        dias = (hoje - ultima).days
        intervalos = [(b - a).days for a, b in zip(datas, datas[1:]) if (b - a).days > 0]
        ciclo = round(median(intervalos)) if len(intervalos) >= 2 else None
        if ultima >= ini_mes:
            situacao = 'COMPROU'
        elif dias > INATIVO_DIAS:
            situacao = 'INATIVO'
        elif ciclo is None:
            situacao = 'SEM_CICLO'
        elif dias > ciclo * FOLGA_CICLO:
            situacao = 'ATRASADO'
        else:
            situacao = 'NO_PRAZO'
        linhas_cli = sorted(c['linhas'].values(), key=lambda x: -x['valor'])
        perdidas = [x['nome'] for x in linhas_cli
                    if (hoje - x['ultima']).days > LINHA_PERDIDA_DIAS and dias <= LINHA_PERDIDA_DIAS]
        cad = cadastro.get(cod, {})
        clientes.append({
            'cod': cod,
            'nome': cad.get('fantasia') or cad.get('nome') or f'Cliente {cod}',
            'razao': cad.get('nome') or '',
            'cidade': cad.get('cidade') or '',
            'telefone': cad.get('telefone') or '',
            'repcod': max(c['reps'], key=c['reps'].get),
            'ultima_compra': ultima.isoformat(),
            'dias_sem_comprar': dias,
            'compras_12m': sum(1 for d in datas if d >= desde_12m),
            'ciclo_dias': ciclo,
            'proxima_prevista': (ultima + timedelta(days=ciclo)).isoformat() if ciclo else None,
            'atraso_dias': max(dias - ciclo, 0) if ciclo else None,
            'situacao': situacao,
            'valor_12m': round(c['valor_12m'], 2),
            'tn_12m': round(c['tn_12m'], 3),
            'valor_mes': round(c['valor_mes'], 2),
            'linhas': [{'cod': x['cod'], 'nome': x['nome'], 'ultima': x['ultima'].isoformat()} for x in linhas_cli],
            'linhas_perdidas': perdidas,
        })

    # Carteira = quem comprou nos últimos 12 meses (inclui o mês corrente: cliente novo conta).
    base = {c['cod'] for c in clientes if any(d >= desde_12m for d in por_cli[c['cod']]['datas'])}
    positivados = {c['cod'] for c in clientes if c['situacao'] == 'COMPROU'}
    positivados_ant = {l['cliente'] for l in linhas if ini_mes_ant <= date.fromisoformat(l['data']) <= corte_mes_ant}

    # Clientes distintos por mês: os 6 fechados + o corrente.
    serie = []
    m = ini_mes
    for _ in range(7):
        serie.append({'mes': _mes(m), 'clientes': len(meses_cli.get(_mes(m), ()))})
        m = (m - timedelta(days=1)).replace(day=1)
    serie.reverse()

    # Mix: quantos clientes ativos compraram cada linha em 12 meses; quem não compra é oportunidade.
    ativos = [c for c in clientes if c['situacao'] != 'INATIVO']
    por_linha: dict[int, dict] = {}
    for c in ativos:
        for x in c['linhas']:
            if date.fromisoformat(x['ultima']) >= desde_12m:
                l = por_linha.setdefault(x['cod'], {'cod': x['cod'], 'nome': x['nome'], 'clientes': 0})
                l['clientes'] += 1
    valor_linha = defaultdict(float)
    for l in linhas:
        if date.fromisoformat(l['data']) >= desde_12m:
            valor_linha[l['linha_cod']] += float(l['valor'] or 0)
    n_ativos = len(ativos)
    mix = sorted(({
        **l, 'valor': round(valor_linha[l['cod']], 2),
        'cobertura': round(l['clientes'] / n_ativos * 100, 1) if n_ativos else 0,
    } for l in por_linha.values()), key=lambda l: -l['valor'])

    linhas_por_cli = [sum(1 for x in c['linhas'] if date.fromisoformat(x['ultima']) >= desde_12m) for c in ativos]
    return {
        'hoje': hoje.isoformat(),
        'resumo': {
            'carteira': len(base),
            'ativos': n_ativos,
            'positivados': len(positivados),
            'positivacao': round(len(positivados) / len(base) * 100, 1) if base else 0,
            'positivados_mes_anterior': len(positivados_ant),
            'positivacao_mes_anterior': round(len(positivados_ant) / len(base) * 100, 1) if base else 0,
            'atrasados': sum(1 for c in clientes if c['situacao'] == 'ATRASADO'),
            'mix_medio': round(sum(linhas_por_cli) / len(linhas_por_cli), 2) if linhas_por_cli else 0,
            'valor_mes': round(sum(c['valor_mes'] for c in clientes), 2),
        },
        'serie': serie,
        'mix': mix,
        'clientes': sorted(clientes, key=lambda c: (-c['valor_12m'])),
        'parametros': {'folga_ciclo': FOLGA_CICLO, 'inativo_dias': INATIVO_DIAS, 'linha_perdida_dias': LINHA_PERDIDA_DIAS},
    }


def carteira(repcods: list[int] | None) -> dict:
    hoje = date.today()
    reps = 'todos' if repcods is None else '-'.join(map(str, sorted(repcods)))
    chave = f'pedidosVenda:carteira:{hoje}:{reps}'
    dados = cache.get(chave)
    if dados is None:
        linhas = _linhas_erp(repcods, hoje - timedelta(days=JANELA_DIAS))
        cadastro = _clientes_erp(sorted({l['cliente'] for l in linhas}))
        dados = calcular(linhas, hoje, cadastro)
        cache.set(chave, dados, CACHE_SEG)
    return dados
