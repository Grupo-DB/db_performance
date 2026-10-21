"""
Leitura do SGA (Minerion) para o combustível. SÓ LEITURA, usuário DBCONSULTA, sempre com
parâmetros (nada de texto do usuário colado no SQL).

Onde está cada coisa (levantado em 20–21/10/2026):

* Entradas: ``ITEMNOTAFISCALENTRADA`` (INFEITEM = produto) + ``NOTAFISCALENTRADA`` + ``FORNECEDOR``.
* Saídas: ``BAIXAESTOQUE`` — BESTSIT 8 ativa, 9 cancelada (fica de fora), 10 devolução (subtrai).
  BESTIAB ≠ 0 = veio da integração (IABCODAB); BESTIAB ≥ BASE_CODIGO_INTEGRACAO = veio do Manager.
* Horímetro/km de cada abastecimento: ``INTEGRACAOABASTECIMENTO`` (uma linha por TENTATIVA,
  IABERRO 'S' quando o SGA recusou).

``BESTIAB`` não tem índice: toda consulta por ele leva filtro de data junto (sem isso a
tabela de 750 mil linhas é varrida inteira e passa de 5 minutos).
"""
from datetime import date, datetime, timedelta

from django.core.cache import cache
from sqlalchemy import bindparam, text

from pedidosVenda.erp import engine

from .models import BASE_CODIGO_INTEGRACAO, PRODUTOS

ITENS = tuple(PRODUTOS)
CACHE_CADASTRO = 30 * 60
CACHE_MOVIMENTO = 3 * 60


class ErpIndisponivel(Exception):
    pass


def _rows(sql: str, expandir: tuple = (), **params) -> list[dict]:
    consulta = text(sql)
    if expandir:
        consulta = consulta.bindparams(*[bindparam(n, expanding=True) for n in expandir])
    try:
        with engine().connect() as conn:
            return [dict(r._mapping) for r in conn.execute(consulta, params)]
    except Exception as exc:  # pyodbc/sqlalchemy: ERP fora do ar, rede, timeout
        raise ErpIndisponivel(str(exc)[:200]) from exc


def _texto(v):
    if v is None:
        return ''
    return str(v).replace('\x00', '').strip()


def _num(v):
    return float(v) if v is not None else 0.0


def _cacheado(chave, segundos, func):
    valor = cache.get(chave)
    if valor is None:
        valor = func()
        cache.set(chave, valor, segundos)
    return valor


# Tipos de equipamento (TIPOEQUIPAMENTO) que abastecem diesel: veículos, máquinas móveis e os
# motores estacionários que vão ao tanque (gerador, bomba d'água). A planta (correia, rosca, silo,
# moinho…) fica de fora — eram 900 dos 986 equipamentos ativos na lista do registro.
TIPOS_QUE_ABASTECEM = {
    1: 'Carregadeira', 2: 'Escavadeira', 3: 'Veículos pesados', 4: 'Veículos leves', 13: 'Perfuratriz',
    35: 'Gerador', 55: 'Munck', 59: 'Empilhadeira', 60: 'Patrola', 61: 'Retroescavadeira', 62: 'Sonda',
    63: 'Trator', 64: "Bomba d'água", 74: 'Picador de cavaco', 85: 'Veículos leves PPR', 87: 'Ônibus', 94: 'Rompedor',
}


def tag_do_nome(nome: str) -> str:
    """'VEC-CF-09 - CAMINHAO FORA EST SCANIA IUB' → 'VEC-CF-09' (o SGA guarda TAG e descrição no mesmo campo)."""
    nome = _texto(nome)
    return nome.split(' - ', 1)[0].strip() if ' - ' in nome else nome


# ── Cadastros ────────────────────────────────────────────────────────────────────
def equipamentos() -> list[dict]:
    def buscar():
        linhas = _rows("""
            SELECT e.EQPCOD cod, e.EQPNOME nome, e.EQPPLACA placa, e.EQPCC cc, c.CCNOME cc_nome,
                   e.EQPKMSN km, e.EQPHRSN hr, e.EQPIDENTIAB ident, e.EQPTEQP tipo
            FROM EQUIPAMENTO e LEFT JOIN CENTROCUSTO c ON c.CCCOD = e.EQPCC
            WHERE ISNULL(e.EQPINATIVO, 'N') <> 'S'""")
        return [{
            'cod': int(l['cod']), 'nome': _texto(l['nome']), 'placa': _texto(l['placa']),
            'tag': tag_do_nome(l['nome']),
            'descricao': _texto(l['nome']).split(' - ', 1)[1].strip() if ' - ' in _texto(l['nome']) else '',
            'tipo': int(l['tipo'] or 0) or None,
            'tipo_nome': TIPOS_QUE_ABASTECEM.get(int(l['tipo'] or 0), ''),
            'abastece': int(l['tipo'] or 0) in TIPOS_QUE_ABASTECEM,
            'centro_custo': int(l['cc'] or 0) or None, 'centro_custo_nome': _texto(l['cc_nome']),
            'usa_km': _texto(l['km']) == 'S', 'usa_horimetro': _texto(l['hr']) == 'S',
            # Sem identificação o SgaAbastecimento recusa com "Equipamento não identificado".
            'integra': bool(_texto(l['ident'])),
        } for l in linhas]
    return _cacheado('comb:equipamentos:v2', CACHE_CADASTRO, buscar)


def funcionarios() -> list[dict]:
    def buscar():
        linhas = _rows("""
            SELECT FUNCOD cod, FUNNOME nome, FUNIDENTIAB ident
            FROM FUNCIONARIO WHERE ISNULL(FUNBLOQ, 'N') <> 'S' AND ISNULL(FUNNOME, '') <> ''""")
        return [{
            'cod': int(l['cod']), 'nome': _texto(l['nome']),
            # Só quem tem FUNIDENTIAB passa na integração ("Funcionário não identificado").
            'integra': bool(_texto(l['ident'])),
        } for l in linhas]
    return _cacheado('comb:funcionarios', CACHE_CADASTRO, buscar)


def mapa_equipamentos() -> dict[int, dict]:
    return {e['cod']: e for e in equipamentos()}


def estoque_sga() -> dict[tuple[int, int], dict]:
    """Saldo contábil e custo médio do SGA por (produto, filial) — QUANTESTOQUE, linha QESTQREF 0."""
    def buscar():
        linhas = _rows("""
            SELECT QESTQESTQ item, QESTQFIL fil, QESTQESTOQUE saldo, QESTQCUSTO custo, QESTQESTMIN minimo, QESTQESTMAX maximo
            FROM QUANTESTOQUE WHERE QESTQESTQ IN :itens AND QESTQEMP = 1 AND QESTQTIPO = 0 AND QESTQREF = 0""",
            expandir=('itens',), itens=list(ITENS))
        return {f"{int(l['item'])}:{int(l['fil'])}": {
            'saldo': _num(l['saldo']), 'custo_medio': _num(l['custo']),
            'minimo': _num(l['minimo']), 'maximo': _num(l['maximo']),
        } for l in linhas}
    bruto = _cacheado('comb:estoque', CACHE_MOVIMENTO, buscar)
    return {tuple(int(x) for x in k.split(':')): v for k, v in bruto.items()}


# ── Movimento ────────────────────────────────────────────────────────────────────
def _periodo(inicio: date, fim: date):
    return datetime.combine(inicio, datetime.min.time()), datetime.combine(fim + timedelta(days=1), datetime.min.time())


def baixas(inicio: date, fim: date) -> list[dict]:
    """Saídas de combustível do período (ativas e devoluções), com o custo do SGA."""
    de, ate = _periodo(inicio, fim)

    def buscar():
        linhas = _rows("""
            SELECT b.BESTCOD cod, b.BESTDATA data, b.BESTESTQ item, b.BESTQUANT litros, b.BESTCUSTO custo,
                   b.BESTEQP eqp, b.BESTCC cc, b.BESTSIT sit, b.BESTIAB iab, b.BESTFIL fil, b.BESTFUNREQ func
            FROM BAIXAESTOQUE b
            WHERE b.BESTESTQ IN :itens AND b.BESTDATA >= :de AND b.BESTDATA < :ate AND b.BESTSIT IN (8, 10)""",
            expandir=('itens',), itens=list(ITENS), de=de, ate=ate)
        saida = []
        for l in linhas:
            iab = int(l['iab'] or 0)
            sinal = -1 if int(l['sit']) == 10 else 1
            saida.append({
                'cod': int(l['cod']), 'data': l['data'].isoformat() if l['data'] else None,
                'item': int(l['item']), 'litros': sinal * _num(l['litros']), 'custo': sinal * _num(l['custo']),
                'equipamento': int(l['eqp'] or 0) or None, 'centro_custo': int(l['cc'] or 0) or None,
                'situacao': int(l['sit']), 'iab': iab or None, 'filial': int(l['fil'] or 0),
                'requisitante': int(l['func'] or 0) or None,
                'origem': 'MANAGER' if iab >= BASE_CODIGO_INTEGRACAO else ('BOMBA' if iab else 'MANUAL'),
            })
        return saida
    return _cacheado(f'comb:baixas:{inicio}:{fim}', CACHE_MOVIMENTO, buscar)


def entradas(inicio: date, fim: date) -> list[dict]:
    """Notas fiscais de entrada de combustível (data de entrada no SGA)."""
    de, ate = _periodo(inicio, fim)

    def buscar():
        linhas = _rows("""
            SELECT n.NFECOD cod, n.NFEDATA data, n.NFEDATANF data_nf, n.NFENUMNF numero, n.NFEFIL fil,
                   f.FORNOME fornecedor, f.FORNOMEFANT fantasia, i.INFEITEM item, i.INFEQUANT litros,
                   i.INFEUNIT preco, i.INFETOTAL total
            FROM ITEMNOTAFISCALENTRADA i
            JOIN NOTAFISCALENTRADA n ON n.NFECOD = i.INFENFE
            LEFT JOIN FORNECEDOR f ON f.FORCOD = n.NFEFOR
            WHERE i.INFEITEM IN :itens AND n.NFEDATA >= :de AND n.NFEDATA < :ate""",
            expandir=('itens',), itens=list(ITENS), de=de, ate=ate)
        return [{
            'cod': int(l['cod']), 'data': l['data'].date().isoformat() if l['data'] else None,
            'data_nf': l['data_nf'].date().isoformat() if l['data_nf'] else None,
            'numero': int(l['numero'] or 0) or None, 'filial': int(l['fil'] or 0),
            'fornecedor': _texto(l['fantasia']) or _texto(l['fornecedor']),
            'item': int(l['item']), 'litros': _num(l['litros']), 'preco': _num(l['preco']), 'total': _num(l['total']),
        } for l in linhas]
    return _cacheado(f'comb:entradas:{inicio}:{fim}', CACHE_MOVIMENTO, buscar)


def leituras(inicio: date, fim: date) -> list[dict]:
    """Horímetro/km dos abastecimentos aceitos pela integração (uma linha por abastecimento)."""
    de, ate = _periodo(inicio, fim)

    def buscar():
        linhas = _rows("""
            SELECT IABCODAB cod, MAX(IABEQP) eqp, MAX(IABDATA) data, MAX(IABHR) hr, MAX(IABKM) km, MAX(IABQUANT) litros
            FROM INTEGRACAOABASTECIMENTO
            WHERE IABDATA >= :de AND IABDATA < :ate AND ISNULL(IABERRO, 'N') <> 'S'
            GROUP BY IABCODAB""", de=de, ate=ate)
        return [{
            'cod': int(l['cod']), 'equipamento': int(l['eqp'] or 0) or None,
            'data': l['data'].isoformat() if l['data'] else None,
            'horimetro': _num(l['hr']) or None, 'km': _num(l['km']) or None, 'litros': _num(l['litros']),
        } for l in linhas]
    return _cacheado(f'comb:leituras:{inicio}:{fim}', CACHE_MOVIMENTO, buscar)


def ultima_leitura(equipamento: int) -> dict | None:
    """Maior horímetro/km já aceito para o equipamento — base da conferência do registro novo."""
    linhas = _rows("""
        SELECT TOP 1 IABDATA data, IABHR hr, IABKM km FROM INTEGRACAOABASTECIMENTO
        WHERE IABEQP = :eqp AND ISNULL(IABERRO, 'N') <> 'S' AND IABDATA >= :desde
        ORDER BY IABDATA DESC""", eqp=equipamento, desde=datetime.now() - timedelta(days=180))
    if not linhas:
        return None
    l = linhas[0]
    return {'data': l['data'].isoformat() if l['data'] else None, 'horimetro': _num(l['hr']) or None, 'km': _num(l['km']) or None}


def situacao_integracao() -> dict:
    """Saúde do SgaAbastecimento: última importação e o que está travado."""
    def buscar():
        ultima = _rows("SELECT MAX(IABDATAINC) inc, MAX(IABDATA) ab FROM INTEGRACAOABASTECIMENTO")[0]
        desde = datetime.now() - timedelta(days=120)
        travados = _rows("""
            WITH a AS (
                SELECT IABCODAB cod, MAX(IABDATA) data, MAX(IABEQP) eqp, MAX(IABQUANT) litros, COUNT(*) tentativas,
                       MAX(LEFT(IABERRODESC, 120)) erro, MAX(CASE WHEN ISNULL(IABERRO, 'N') <> 'S' THEN 1 ELSE 0 END) ok
                FROM INTEGRACAOABASTECIMENTO WHERE IABDATA >= :desde GROUP BY IABCODAB),
            b AS (SELECT DISTINCT BESTIAB FROM BAIXAESTOQUE WHERE BESTIAB <> 0 AND BESTDATA >= :desde_baixa)
            SELECT a.* FROM a LEFT JOIN b ON b.BESTIAB = a.cod WHERE b.BESTIAB IS NULL AND a.ok = 0
            ORDER BY a.data DESC""", desde=desde, desde_baixa=desde - timedelta(days=30))
        duplicadas = _rows("""
            SELECT BESTIAB iab, COUNT(*) n, SUM(BESTQUANT) litros, MIN(BESTDATA) data, MIN(BESTEQP) eqp,
                   STRING_AGG(CAST(BESTCOD AS varchar(12)), ',') baixas
            FROM BAIXAESTOQUE WHERE BESTIAB <> 0 AND BESTSIT = 8 AND BESTDATA >= :desde AND BESTESTQ IN :itens
            GROUP BY BESTIAB HAVING COUNT(*) > 1""", expandir=('itens',), desde=desde, itens=list(ITENS))
        return {
            'ultima_importacao': ultima['inc'].isoformat() if ultima['inc'] else None,
            'ultimo_abastecimento': ultima['ab'].isoformat() if ultima['ab'] else None,
            'travados': [{
                'cod': int(t['cod']), 'data': t['data'].isoformat() if t['data'] else None,
                'equipamento': int(t['eqp'] or 0) or None, 'litros': _num(t['litros']),
                'tentativas': int(t['tentativas']), 'erro': _texto(t['erro']),
            } for t in travados],
            'duplicadas': [{
                'iab': int(d['iab']), 'baixas': [int(x) for x in _texto(d['baixas']).split(',') if x],
                'litros': _num(d['litros']), 'data': d['data'].isoformat() if d['data'] else None,
                'equipamento': int(d['eqp'] or 0) or None,
            } for d in duplicadas],
        }
    return _cacheado('comb:situacao', CACHE_MOVIMENTO, buscar)


def carregamentos_comboio(equipamento: int, produto: int, desde: datetime) -> list[dict]:
    """
    Diesel baixado NO comboio (o carregamento que a bomba/CTA lança no equipamento do caminhão).
    Devolução (BESTSIT 10) entra negativa.
    """
    linhas = _rows("""
        SELECT BESTCOD cod, BESTDATA data, BESTQUANT litros, BESTSIT sit, BESTIAB iab FROM BAIXAESTOQUE
        WHERE BESTEQP = :eqp AND BESTESTQ = :item AND BESTDATA >= :desde AND BESTSIT IN (8, 10)""",
        eqp=equipamento, item=produto, desde=desde)
    return [{'cod': int(l['cod']), 'data': l['data'].isoformat() if l['data'] else None,
             'litros': (-1 if int(l['sit']) == 10 else 1) * _num(l['litros']), 'iab': int(l['iab'] or 0) or None}
            for l in linhas]


def baixas_dos_codigos(codigos: list[int], desde: datetime) -> dict[int, dict]:
    """Conciliação: quais registros do Manager o SGA já baixou (BESTIAB = código de integração)."""
    if not codigos:
        return {}
    linhas = _rows("""
        SELECT BESTIAB iab, BESTCOD cod, BESTDATA data, BESTSIT sit FROM BAIXAESTOQUE
        WHERE BESTIAB IN :codigos AND BESTDATA >= :desde AND BESTSIT IN (8, 10)""",
        expandir=('codigos',), codigos=list(codigos), desde=desde)
    return {int(l['iab']): {'baixa': int(l['cod']), 'data': l['data']} for l in linhas if int(l['sit']) == 8}
