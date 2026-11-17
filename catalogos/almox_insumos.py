"""
Painel de Insumos de produção (17/11/2026): estoque, consumo e cobertura dos
grupos/itens que o gestor escolhe monitorar (models.InsumoMonitorado).

- Itens: os mesmos do almoxarifado (almoxarifado._preparado — saldo, mínimo,
  valor, compra em andamento, foto). Um grupo monitorado leva os subgrupos.
  Item que cai em mais de um monitorado fica no mais específico: item avulso
  primeiro, depois o grupo mais fundo da árvore.
- Consumo: MOVESTOQUE tipo 2 (requisição do almoxarifado), líquido de
  devolução — é por onde a fábrica tira matéria-prima, embalagem, energia e
  lenha/cavaco (conferido em 17/11: CAL R$ 2,2 mi e CAVACO R$ 2,1 mi em 90 dias).
  Entrada: tipo 1 (nota). Valor = MESTQCUSTO (com sinal).
- Cobertura (dias) = saldo ÷ consumo médio diário do período escolhido. Num
  grupo, em R$ (valor em estoque ÷ consumo diário em R$), porque as unidades
  se misturam (KWH, KG, UN…).
- Situação do item: abaixo (abaixo do mínimo, ou sem saldo com consumo no
  período), atencao (cobertura ≤ prazo do grupo — o mesmo prazo de atenção do
  almoxarifado), ok, sem_consumo.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from . import almoxarifado as ax

logger = logging.getLogger(__name__)

DIAS_OPCOES = (30, 90, 180, 365)
DIAS_PADRAO = 90
MESES_SERIE = 12

_SQL_MOV = """
    SELECT MESTQESTQ ESTQ, CAST(MESTQDATA AS DATE) DIA, MESTQREFTIPO TIPO,
           SUM(MESTQQUANT) QUANT, SUM(MESTQCUSTO) VALOR
    FROM MOVESTOQUE
    WHERE MESTQEMP = :emp AND MESTQDATA >= :desde AND MESTQREFTIPO IN (1, 2)
      AND MESTQESTQ IN ({codigos}) {filtro_filial}
    GROUP BY MESTQESTQ, CAST(MESTQDATA AS DATE), MESTQREFTIPO
"""


def _f(v) -> float:
    return ax._num(v)


def _r(v, casas=2):
    return None if v is None or pd.isna(v) else round(float(v), casas)


def variacao(atual: float, anterior: float) -> float | None:
    if anterior <= 0:
        return None
    return round(100.0 * (atual - anterior) / anterior, 1)


def passo_serie(dias: int) -> int:
    """Tamanho (dias) de cada barrinha da série: ~13 a 30 pontos no período."""
    return 1 if dias <= 31 else 7 if dias <= 120 else 14 if dias <= 200 else 30


# ── Monitorados ─────────────────────────────────────────────────────────────

def monitorados_app() -> list[dict]:
    from .models import InsumoMonitorado
    return list(InsumoMonitorado.objects.values('id', 'tipo', 'codigo', 'ordem'))


def caminho_grupo(cod: int, nome: dict, pai: dict) -> str:
    partes, atual, visto = [], cod, set()
    while atual and atual not in visto:
        visto.add(atual)
        partes.append(nome.get(atual, f'Grupo {atual}'))
        atual = pai.get(atual)
    return ' › '.join(reversed(partes))


def distribuir(df: pd.DataFrame, grupos: pd.DataFrame, monitorados: list[dict]) -> tuple[pd.Series, list[dict]]:
    """(chave do monitorado por linha do df — None = fora do painel, descrição de cada monitorado)."""
    nome, _raiz, pai = ax.arvore(grupos)
    filhos = ax.filhos_por_grupo(pai)
    nomes_item = {int(c): str(n or '').strip() for c, n in zip(df.ESTQCOD, df.ESTQNOME)}

    def profundidade(c):
        n, atual, visto = 0, c, set()
        while pai.get(atual) and atual not in visto:
            visto.add(atual)
            atual = pai[atual]
            n += 1
        return n

    info, por_item, por_grupo = [], {}, {}
    for m in monitorados:
        chave = f"{m['tipo'][0]}{m['codigo']}"
        d = {'id': m.get('id'), 'chave': chave, 'tipo': m['tipo'], 'codigo': int(m['codigo'])}
        if m['tipo'] == 'item':
            d['nome'] = nomes_item.get(int(m['codigo']), f"Item {m['codigo']}")
            d['caminho'] = ''
            por_item[int(m['codigo'])] = chave
        else:
            cod = int(m['codigo'])
            d['nome'] = nome.get(cod, f'Grupo {cod}')
            d['caminho'] = caminho_grupo(pai.get(cod) or 0, nome, pai) if pai.get(cod) else ''
            fundo = profundidade(cod)
            for g in ax.descendentes(cod, filhos):
                atual = por_grupo.get(g)
                if atual is None or atual[0] < fundo:
                    por_grupo[g] = (fundo, chave)
        d['existe'] = (int(m['codigo']) in nomes_item) if m['tipo'] == 'item' else (int(m['codigo']) in nome)
        info.append(d)

    chaves = [por_item.get(int(c)) or (por_grupo.get(int(g)) or (None, None))[1]
              for c, g in zip(df.ESTQCOD, df.GALM)]
    return pd.Series(chaves, index=df.index, dtype=object), info


# ── Movimento ───────────────────────────────────────────────────────────────

def ler_movimento(filial: int | None, codigos: list[int], desde: date) -> pd.DataFrame:
    if not codigos:
        return pd.DataFrame(columns=['ESTQ', 'DIA', 'TIPO', 'QUANT', 'VALOR'])
    codigos = sorted({int(c) for c in codigos})

    def ler():
        params = {'emp': ax.EMPRESA, 'desde': desde}
        filtro = ''
        if filial is not None:
            params['fil'] = filial
            filtro = 'AND MESTQFIL = :fil'
        partes = []
        for i in range(0, len(codigos), 2000):          # limite de parâmetros do SQL Server
            lote = ','.join(str(c) for c in codigos[i:i + 2000])
            partes.append(ax._ler(_SQL_MOV.format(codigos=lote, filtro_filial=filtro), **params))
        return pd.concat(partes, ignore_index=True)

    chave = f'almox:ins:mov:{"todas" if filial is None else filial}:{desde}:{hash(tuple(codigos))}'
    return ax._cacheado(chave, ax.CACHE_SEG, ler)


def preparar_movimento(mov: pd.DataFrame) -> pd.DataFrame:
    """ESTQ, DIA (Timestamp), CONS_Q/CONS_V (consumo, positivo) e ENT_Q/ENT_V (entrada)."""
    m = mov.copy()
    if m.empty:
        return pd.DataFrame({'ESTQ': pd.Series(dtype=int), 'DIA': pd.Series(dtype='datetime64[ns]'),
                             **{c: pd.Series(dtype=float) for c in ('CONS_Q', 'CONS_V', 'ENT_Q', 'ENT_V')}})
    m['ESTQ'] = pd.to_numeric(m.ESTQ, errors='coerce').fillna(-1).astype(int)
    m['DIA'] = pd.to_datetime(m.DIA).dt.normalize()
    m['TIPO'] = pd.to_numeric(m.TIPO, errors='coerce').fillna(0).astype(int)
    q = pd.to_numeric(m.QUANT, errors='coerce').fillna(0.0)
    v = pd.to_numeric(m.VALOR, errors='coerce').fillna(0.0)
    cons = m.TIPO == 2
    m['CONS_Q'] = (-q).where(cons, 0.0)
    m['CONS_V'] = (-v).where(cons, 0.0)
    m['ENT_Q'] = q.where(~cons, 0.0)
    m['ENT_V'] = v.where(~cons, 0.0)
    return m[['ESTQ', 'DIA', 'CONS_Q', 'CONS_V', 'ENT_Q', 'ENT_V']]


def _serie(mov: pd.DataFrame, coluna: str, inicio: pd.Timestamp, passo: int, n: int) -> list[float]:
    if mov.empty:
        return [0.0] * n
    idx = ((mov.DIA - inicio).dt.days // passo).astype(int)
    ok = (idx >= 0) & (idx < n)
    s = mov.loc[ok, coluna].groupby(idx[ok]).sum()
    return [round(float(s.get(i, 0.0)), 3) for i in range(n)]


# ── Montagem ────────────────────────────────────────────────────────────────

def _situacao(r, cons_dia: float, cobertura: float | None) -> str:
    if r.ABAIXO or (r.SALDO <= 0 and cons_dia > 0):
        return 'abaixo'
    if cons_dia <= 0:
        return 'sem_consumo'
    if cobertura is not None and cobertura <= r.PRAZO:
        return 'atencao'
    return 'ok'


def montar_painel(df: pd.DataFrame, grupos: pd.DataFrame, mov: pd.DataFrame, monitorados: list[dict],
                  hoje: date, dias: int) -> dict:
    """Payload do painel a partir do df do almoxarifado (já preparado) e do movimento diário."""
    chaves, info = distribuir(df, grupos, monitorados)
    df = df.assign(MONIT=chaves)
    df = df[df.MONIT.notna()].copy()
    mov = preparar_movimento(mov)

    fim = pd.Timestamp(hoje)
    ini = fim - pd.Timedelta(days=dias - 1)
    ini_ant = ini - pd.Timedelta(days=dias)
    passo = passo_serie(dias)
    n_serie = -(-dias // passo)
    ini_serie = fim - pd.Timedelta(days=n_serie * passo - 1)

    periodo = mov[(mov.DIA >= ini) & (mov.DIA <= fim)]
    anterior = mov[(mov.DIA >= ini_ant) & (mov.DIA < ini)]
    por_item = periodo.groupby('ESTQ')[['CONS_Q', 'CONS_V', 'ENT_Q', 'ENT_V']].sum()
    ant_item = anterior.groupby('ESTQ')[['CONS_Q', 'CONS_V']].sum()
    ult_ent = mov[mov.ENT_Q > 0].groupby('ESTQ').DIA.max()
    ult_cons = mov[mov.CONS_Q > 0].groupby('ESTQ').DIA.max()
    mov_por_item = {k: g for k, g in mov[mov.DIA >= ini_serie].groupby('ESTQ')}

    def pega(tab, cod, col):
        return float(tab.at[cod, col]) if cod in tab.index else 0.0

    itens = []
    for r in df.itertuples():
        cod = int(r.ESTQCOD)
        cq, cv = pega(por_item, cod, 'CONS_Q'), pega(por_item, cod, 'CONS_V')
        aq = pega(ant_item, cod, 'CONS_Q')
        eq, ev = pega(por_item, cod, 'ENT_Q'), pega(por_item, cod, 'ENT_V')
        if not (r.SALDO > 0 or r.TEM_MIN or r.EM_COMPRA or cq or eq or cod in mov_por_item):
            continue                                    # item morto: não polui o painel
        cons_dia = max(cq, 0.0) / dias
        cob = (max(float(r.SALDO), 0.0) / cons_dia) if cons_dia > 0 else None
        base = ax._item(r)
        itens.append({
            'codigo': cod,
            'nome': base['nome'],
            'unidade': base['unidade'],
            'grupo_item': base['grupo_item'],
            'monitorado': r.MONIT,
            'saldo': base['saldo'],
            'minimo': base['minimo'],
            'valor': base['valor'],
            'custo_unitario': _r(r.VALOR / r.SALDO, 4) if r.SALDO > 0 else None,
            'consumo': round(cq, 3),
            'consumo_valor': round(cv, 2),
            'consumo_anterior': round(aq, 3),
            'variacao': variacao(cq, aq),
            'consumo_dia': round(cons_dia, 3),
            'cobertura_dias': _r(cob, 1),
            'prazo': int(r.PRAZO),
            'entrada': round(eq, 3),
            'entrada_valor': round(ev, 2),
            'ultima_entrada': ax._data_iso(ult_ent.get(cod)),
            'ultimo_consumo': ax._data_iso(ult_cons.get(cod)),
            'situacao': _situacao(r, cons_dia, cob),
            'serie': _serie(mov_por_item.get(cod, mov.iloc[0:0]), 'CONS_Q', ini_serie, passo, n_serie),
            'tem_foto': base['tem_foto'],
            'em_compra': base['em_compra'],
            'compra_etapa': base['compra_etapa'],
            'compra_texto': base['compra_texto'],
        })
    itens.sort(key=lambda i: (-i['consumo_valor'], -i['valor'], i['nome']))

    # Série mensal (R$ consumidos) por monitorado: últimos MESES_SERIE meses, o atual incluso.
    mes_fim = fim.to_period('M')
    meses = [str(mes_fim - k) for k in range(MESES_SERIE - 1, -1, -1)]
    chave_item = dict(zip(df.ESTQCOD.astype(int), df.MONIT))
    mm = mov[mov.ESTQ.isin(chave_item.keys())].copy()
    mm['MES'] = mm.DIA.dt.to_period('M').astype(str)
    mm['MONIT'] = mm.ESTQ.map(chave_item)
    mm = mm[mm.MES.isin(meses)]
    cons_mes = mm.groupby(['MONIT', 'MES']).CONS_V.sum()
    ent_mes = mm.groupby('MES').ENT_V.sum()

    cards = []
    for d in info:
        its = [i for i in itens if i['monitorado'] == d['chave']]
        valor = sum(i['valor'] for i in its)
        cv = sum(i['consumo_valor'] for i in its)
        cods = {i['codigo'] for i in its}
        cv_ant = float(anterior[anterior.ESTQ.isin(cods)].CONS_V.sum()) if cods else 0.0
        unidades = {i['unidade'] for i in its if i['consumo'] or i['saldo']}
        unidade = unidades.pop() if len(unidades) == 1 else None
        mov_g = mov[mov.ESTQ.isin(cods) & (mov.DIA >= ini_serie)]
        cv_dia = cv / dias
        cards.append({
            **d,
            'itens': len(its),
            'valor': round(valor, 2),
            'consumo_valor': round(cv, 2),
            'consumo_valor_anterior': round(cv_ant, 2),
            'variacao': variacao(cv, cv_ant),
            'entrada_valor': round(sum(i['entrada_valor'] for i in its), 2),
            'cobertura_dias': round(valor / cv_dia, 1) if cv_dia > 0 else None,
            'unidade': unidade,
            'saldo': round(sum(i['saldo'] for i in its), 3) if unidade else None,
            'consumo': round(sum(i['consumo'] for i in its), 3) if unidade else None,
            'abaixo': sum(i['situacao'] == 'abaixo' for i in its),
            'atencao': sum(i['situacao'] == 'atencao' for i in its),
            'em_compra': sum(bool(i['compra_etapa']) for i in its),
            'serie': _serie(mov_g, 'CONS_V', ini_serie, passo, n_serie),
            'mensal': [round(float(cons_mes.get((d['chave'], m), 0.0)), 2) for m in meses],
            'destaques': [{'codigo': i['codigo'], 'nome': i['nome'], 'consumo': i['consumo'], 'unidade': i['unidade'],
                           'cobertura_dias': i['cobertura_dias'], 'situacao': i['situacao']}
                          for i in its[:3] if i['consumo_valor'] > 0],
        })

    valor = sum(c['valor'] for c in cards)
    cv = sum(c['consumo_valor'] for c in cards)
    cv_ant = sum(c['consumo_valor_anterior'] for c in cards)
    return {
        'dias': dias,
        'inicio': ini.date().isoformat(),
        'fim': fim.date().isoformat(),
        'passo_serie': passo,
        'inicio_serie': ini_serie.date().isoformat(),
        'totais': {
            'valor': round(valor, 2),
            'consumo_valor': round(cv, 2),
            'consumo_valor_anterior': round(cv_ant, 2),
            'variacao': variacao(cv, cv_ant),
            'entrada_valor': round(sum(c['entrada_valor'] for c in cards), 2),
            'consumo_dia': round(cv / dias, 2),
            'cobertura_dias': round(valor / (cv / dias), 1) if cv > 0 else None,
            'itens': len(itens),
            'abaixo': sum(i['situacao'] == 'abaixo' for i in itens),
            'atencao': sum(i['situacao'] == 'atencao' for i in itens),
            'ok': sum(i['situacao'] == 'ok' for i in itens),
            'sem_consumo': sum(i['situacao'] == 'sem_consumo' for i in itens),
            'em_compra': sum(bool(i['compra_etapa']) for i in itens),
        },
        'meses': meses,
        'entradas_mensal': [round(float(ent_mes.get(m, 0.0)), 2) for m in meses],
        'monitorados': cards,
        'itens': itens,
    }


def painel(filial: int | None, dias: int = DIAS_PADRAO, fonte: str = 'sga', hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    df, erp, _prazos = ax._preparado(filial, fonte)
    monitorados = monitorados_app()
    chaves, _ = distribuir(df, erp['grupos'], monitorados)
    codigos = [int(c) for c in df.ESTQCOD[chaves.notna()]]
    # Período atual + anterior (comparação) e pelo menos 12 meses para a série mensal.
    janela = max(2 * dias, 366 + 31)
    mov = ler_movimento(filial, codigos, hoje - timedelta(days=janela))
    dados = montar_painel(df, erp['grupos'], mov, monitorados, hoje, dias)
    dados['lido_em'] = erp.get('lido_em')
    return dados


# ── Edição (gestor) ─────────────────────────────────────────────────────────

def incluir(tipo: str, codigo: int, usuario) -> dict:
    from django.db.models import Max
    from .models import InsumoMonitorado
    if tipo not in ('grupo', 'item'):
        raise ValueError("tipo deve ser 'grupo' ou 'item'.")
    try:
        codigo = int(codigo)
    except (TypeError, ValueError):
        raise ValueError('codigo deve ser um número.')
    ordem = (InsumoMonitorado.objects.aggregate(m=Max('ordem'))['m'] or 0) + 1
    obj, criado = InsumoMonitorado.objects.get_or_create(
        tipo=tipo, codigo=codigo, defaults={'ordem': ordem, 'incluido_por': usuario})
    return {'id': obj.id, 'criado': criado}


def remover(pk: int) -> bool:
    from .models import InsumoMonitorado
    return InsumoMonitorado.objects.filter(pk=pk).delete()[0] > 0


def reordenar(ids: list[int]) -> None:
    from .models import InsumoMonitorado
    for i, pk in enumerate(ids):
        InsumoMonitorado.objects.filter(pk=int(pk)).update(ordem=i)
