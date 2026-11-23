"""
BI Comercial (23/11/2026): o relatório do Power BI "Comercial - Dagoberto Barcellos"
dentro do Manager. As consultas são as MESMAS do modelo do Power BI (bi_sql/*.sql,
copiadas de INFO.PARTITIONS) e as contas reproduzem as medidas dele:

- Faturamento      = soma de Valor Faturado nas linhas com flag FATURAMENTO
                     (natureza com "operação financeira" S e "não representa receita" N).
- Carregamento (t) = soma de Quantidade (t) nas linhas com flag CARREGAMENTO
                     (natureza que movimenta estoque, exceto NOPCOD 2); (un) idem em unidades.
- Ticket Médio     = soma de Valor Faturado ÷ soma de Quantidade (t), em TODAS as linhas
                     (no Power BI a medida não aplica as flags).
- "Vendas Realizadas" e a evolução mensal somam todas as linhas, como os cartões do BI.
- Saldo de pedidos = pedido − despachado − cancelado (t), pedidos abertos (PEDSIT 0).

As devoluções entram com sinal negativo (2ª parte do UNION, pela nota de entrada que
referencia a nota de saída), como no BI.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from django.core.cache import cache
from sqlalchemy import text

from . import erp

logger = logging.getLogger(__name__)

_SQL_DIR = Path(__file__).with_name('bi_sql')
CACHE_SEG = 10 * 60
PERIODO_MAX_DIAS = 3 * 366

# filtro da URL → coluna do DataFrame (os mesmos segmentadores do BI)
FILTROS = {
    'filial': 'FILIAL', 'regiao': 'REGIAO', 'segmento': 'SEGMENTO', 'grupo': 'GRUPO_GESTAO',
    'representante': 'REPRESENTANTE', 'cliente': 'CLIENTE', 'natureza': 'NATUREZA', 'produto': 'PRODUTO',
}
FILTROS_SALDO = {'filial': 'FILIAL', 'grupo': 'GRUPO', 'produto': 'PRODUTO', 'cliente': 'CLIENTE'}


def _sql(nome: str) -> str:
    return (_SQL_DIR / nome).read_text(encoding='utf-8')


def _ler(sql: str, **params) -> pd.DataFrame:
    with erp.engine().connect() as c:
        return pd.read_sql(text(sql), c, params=params)


def _titulo(s) -> str:
    """Text.Proper do Power Query: cada palavra com a 1ª maiúscula."""
    s = '' if s is None or (isinstance(s, float) and pd.isna(s)) else str(s).strip()
    return ' '.join(p[:1].upper() + p[1:].lower() for p in s.split(' ')) if s else ''


def _txt(s) -> str:
    return '' if s is None or (isinstance(s, float) and pd.isna(s)) else str(s).strip()


def periodo(desde: date | None, ate: date | None, hoje: date | None = None) -> tuple[date, date]:
    """(desde, ate) inclusivos; padrão = do 1º de janeiro até hoje."""
    hoje = hoje or date.today()
    ate = ate or hoje
    desde = desde or date(ate.year, 1, 1)
    if desde > ate:
        raise ValueError('O início do período vem depois do fim.')
    if (ate - desde).days > PERIODO_MAX_DIAS:
        raise ValueError('O período vai até 3 anos.')
    return desde, ate


# ── Faturamento / carregamento ─────────────────────────────────────────────

def preparar(raw: pd.DataFrame) -> pd.DataFrame:
    """Linhas da consulta → colunas com os nomes e os tratamentos do Power Query."""
    if raw.empty:
        return pd.DataFrame(columns=['FILIAL', 'DATA', 'MES', 'NOTA', 'NFCOD', 'TIPO_NF', 'NATUREZA', 'CLIENTE',
                                     'CLIENTE_COD', 'CNPJ', 'CIDADE', 'CIDADE_FAT', 'UF_FAT', 'REPRESENTANTE',
                                     'PRODUTO', 'ESTOQUE', 'ESTOQUE_COD', 'UNIDADE', 'GRUPO', 'GRUPO_GESTAO',
                                     'SEGMENTO', 'REGIAO', 'QTD', 'TN', 'VALOR', 'FAT', 'CARR'])
    r = raw
    df = pd.DataFrame({
        'FILIAL': r.EMPRESAFILIAL.map(_txt),
        'DATA': pd.to_datetime(r.DATA_EMISSAO).dt.normalize(),
        'NOTA': pd.to_numeric(r.NOTA_FISCAL, errors='coerce').fillna(0).astype('int64'),
        'NFCOD': pd.to_numeric(r.NFCOD, errors='coerce').fillna(0).astype('int64'),
        'TIPO_NF': r.TIPO_NF.map(_txt),
        'NATUREZA': r.NATUREZA_OPERACAO.map(_txt),
        'CLIENTE': r.CLIENTE_NOME.map(_txt),
        'CLIENTE_COD': pd.to_numeric(r.CLIENTE_CODIGO, errors='coerce').fillna(0).astype('int64'),
        'CNPJ': r.CLIENTE_CNPJCPF.map(_txt),
        'CIDADE': r.CLIENTE_CIDADE.map(_txt),
        'CIDADE_FAT': r.CIDADE_FATURAMENTO.map(_txt),
        'UF_FAT': r.UF_CLIENTE_FATURAMENTO.map(_txt),
        'REPRESENTANTE': r.REPRESENTANTE.map(_txt),
        'PRODUTO': r.APELIDO.map(_titulo),                 # "Produto" no BI = ESTQAPELIDO
        'ESTOQUE': r.ESTOQUE.map(_titulo),
        'ESTOQUE_COD': pd.to_numeric(r.ESTOQUE_CODIGO, errors='coerce').fillna(0).astype('int64'),
        'UNIDADE': r.UNIDADE.map(_txt),
        'GRUPO': r.GRUPO.map(_txt),
        'GRUPO_GESTAO': r.GRUPO_COMERCIAL.map(_titulo),     # "Grupo de Gestão" no BI
        'SEGMENTO': r.SEGMENTO_PRODUTO.map(_titulo),
        'REGIAO': r.REGIAO.map(_titulo),
        'QTD': pd.to_numeric(r.QUANTIDADE, errors='coerce').fillna(0.0),
        'TN': pd.to_numeric(r.QUANTIDADE_TN, errors='coerce').fillna(0.0),
        'VALOR': pd.to_numeric(r.VALOR_PRODUTO, errors='coerce').fillna(0.0),
        'FAT': r.FATURAMENTO.map(_txt) == 'FATURAMENTO',
        'CARR': r.CARREGAMENTO.map(_txt) == 'CARREGAMENTO',
    })
    df['MES'] = df.DATA.dt.strftime('%Y-%m')
    return df


def ler_faturamento(desde: date, ate: date) -> pd.DataFrame:
    chave = f'bi:com:fat:{desde.isoformat()}:{ate.isoformat()}'
    df = cache.get(chave)
    if df is None:
        df = preparar(_ler(_sql('faturamento.sql'), desde=desde, ate=ate + timedelta(days=1)))
        cache.set(chave, df, CACHE_SEG)
    return df


def filtrar(df: pd.DataFrame, filtros: dict[str, list[str]], mapa: dict[str, str] = FILTROS) -> pd.DataFrame:
    for k, valores in (filtros or {}).items():
        col = mapa.get(k)
        if col and valores:
            df = df[df[col].isin(valores)]
    return df


def _soma(df: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    """Valor/t/un de todas as linhas + faturamento e carregamento pelas flags."""
    d = df.assign(FAT_V=df.VALOR.where(df.FAT, 0.0), CARR_T=df.TN.where(df.CARR, 0.0), CARR_U=df.QTD.where(df.CARR, 0.0))
    return d.groupby(por, dropna=False)[['VALOR', 'TN', 'QTD', 'FAT_V', 'CARR_T', 'CARR_U']].sum().reset_index()


def _r(v, casas=2) -> float:
    return round(float(v or 0.0), casas)


def _ticket(valor: float, t: float) -> float | None:
    return round(valor / t, 2) if t else None


def _linha(r, **extra) -> dict:
    return {**extra, 'valor': _r(r.VALOR), 't': _r(r.TN, 3), 'un': _r(r.QTD, 3), 'faturamento': _r(r.FAT_V),
            'carregamento_t': _r(r.CARR_T, 3), 'carregamento_un': _r(r.CARR_U, 3), 'ticket': _ticket(r.VALOR, r.TN)}


def opcoes(df: pd.DataFrame, mapa: dict[str, str] = FILTROS) -> dict[str, list[str]]:
    return {k: sorted(v for v in df[c].dropna().unique().tolist() if v) for k, c in mapa.items()}


def montar(df: pd.DataFrame, todos: pd.DataFrame, desde: date, ate: date) -> dict:
    """`df` já filtrado; `todos` = o período inteiro (opções dos filtros)."""
    tot = _soma(df.assign(_=1), ['_'])
    t = tot.iloc[0] if len(tot) else None
    notas = df[df.TIPO_NF == 'S'].NFCOD.nunique()

    mensal = [_linha(r, mes=r.MES) for r in _soma(df, ['MES']).sort_values('MES').itertuples()]

    # Página 1: segmento › representante › cliente, com o valor de cada mês.
    vend = _soma(df, ['SEGMENTO', 'REPRESENTANTE', 'CLIENTE'])
    por_mes = df.groupby(['SEGMENTO', 'REPRESENTANTE', 'CLIENTE', 'MES']).VALOR.sum()
    vendas = []
    for r in vend.sort_values('VALOR', ascending=False).itertuples():
        meses = por_mes.loc[(r.SEGMENTO, r.REPRESENTANTE, r.CLIENTE)]
        vendas.append(_linha(r, segmento=r.SEGMENTO, representante=r.REPRESENTANTE, cliente=r.CLIENTE,
                             meses={m: _r(v) for m, v in meses.items() if v}))

    # Página 2 e 4/5: grupo de gestão › produto.
    produtos = [_linha(r, grupo=r.GRUPO_GESTAO or '(sem grupo)', produto=r.PRODUTO, segmento=r.SEGMENTO, unidade=r.UNIDADE)
                for r in _soma(df, ['GRUPO_GESTAO', 'PRODUTO', 'SEGMENTO', 'UNIDADE']).sort_values('VALOR', ascending=False).itertuples()]
    segmentos = [_linha(r, segmento=r.SEGMENTO) for r in _soma(df, ['SEGMENTO']).sort_values('FAT_V', ascending=False).itertuples()]
    grupos = [_linha(r, grupo=r.GRUPO_GESTAO or '(sem grupo)') for r in _soma(df, ['GRUPO_GESTAO']).sort_values('FAT_V', ascending=False).itertuples()]

    return {
        'desde': desde.isoformat(), 'ate': ate.isoformat(),
        'totais': {**(_linha(t) if t is not None else _linha(pd.Series({k: 0.0 for k in ('VALOR', 'TN', 'QTD', 'FAT_V', 'CARR_T', 'CARR_U')}))),
                   'notas': int(notas), 'linhas': int(len(df))},
        'mensal': mensal,
        'vendas': vendas,
        'produtos': produtos,
        'segmentos': segmentos,
        'grupos': grupos,
        'opcoes': opcoes(todos),
        'ultima_nota': df.DATA.max().date().isoformat() if len(df) else None,
    }


def painel(desde: date | None = None, ate: date | None = None, filtros: dict[str, list[str]] | None = None) -> dict:
    desde, ate = periodo(desde, ate)
    todos = ler_faturamento(desde, ate)
    return montar(filtrar(todos, filtros or {}), todos, desde, ate)


# ── Saldo de pedidos (página 8) ────────────────────────────────────────────

def preparar_saldo(raw: pd.DataFrame) -> pd.DataFrame:
    r = raw
    df = pd.DataFrame({
        'FILIAL': r.EMPRESA_FILIAL.map(_txt),
        'DATA': pd.to_datetime(r.DATA_CRIACAO).dt.normalize(),
        'PREVISAO': pd.to_datetime(r.DATA_PREVISTA_ENTREGA, errors='coerce').dt.normalize(),
        'PEDIDO': pd.to_numeric(r.PEDIDO, errors='coerce').fillna(0).astype('int64'),
        'CLIENTE': r.CLIENTE.map(_txt),
        'REPRESENTANTE': r.REPRESENTANTE.map(_txt),
        'CIDADE': r.CIDADEUF.map(_txt),
        'GRUPO': r.GRUPO.map(_txt),
        'PRODUTO_COD': pd.to_numeric(r.ESTOQUE_CODIGO, errors='coerce').fillna(0).astype('int64'),
        'PRODUTO': r.ESTOQUE.map(_txt),
        'UNIDADE': r.ESPECIE.map(_txt),
        'PED_T': pd.to_numeric(r.QUANT_TN, errors='coerce').fillna(0.0),
        'DESP_T': pd.to_numeric(r.QUANTDESP_TN, errors='coerce').fillna(0.0),
        'CANC_T': pd.to_numeric(r.QUANTCANC_TN, errors='coerce').fillna(0.0),
        'VALOR': pd.to_numeric(r.VALOR_TOTAL, errors='coerce').fillna(0.0),
        'ESTOQUE': pd.to_numeric(r.SALDO_ESTOQUE, errors='coerce'),
    })
    df['SALDO_T'] = df.PED_T - df.DESP_T - df.CANC_T
    return df


def ler_saldo() -> pd.DataFrame:
    df = cache.get('bi:com:saldo')
    if df is None:
        df = preparar_saldo(_ler(_sql('saldo_pedidos.sql')))
        cache.set('bi:com:saldo', df, CACHE_SEG)
    return df


def montar_saldo(df: pd.DataFrame, todos: pd.DataFrame) -> dict:
    """Produto › cliente, como a matriz do BI, com os pedidos de cada linha."""
    # Estoque é por produto × filial (repete em cada item de pedido): conta uma vez.
    est = df.drop_duplicates(['PRODUTO_COD', 'FILIAL']).groupby('PRODUTO_COD').ESTOQUE.sum(min_count=1)
    linhas = []
    for (grupo, cod, prod), g in df.groupby(['GRUPO', 'PRODUTO_COD', 'PRODUTO']):
        clientes = []
        for cli, c in g.groupby('CLIENTE'):
            clientes.append({'cliente': cli, 'pedido_t': _r(c.PED_T.sum(), 3), 'despachado_t': _r(c.DESP_T.sum(), 3),
                             'cancelado_t': _r(c.CANC_T.sum(), 3), 'saldo_t': _r(c.SALDO_T.sum(), 3),
                             'pedidos': sorted(int(p) for p in c.PEDIDO.unique())})
        clientes.sort(key=lambda x: -x['saldo_t'])
        e = est.get(cod)
        linhas.append({'grupo': grupo, 'codigo': int(cod), 'produto': prod, 'unidade': g.UNIDADE.iloc[0],
                       'estoque': None if e is None or pd.isna(e) else _r(e, 3),
                       'pedido_t': _r(g.PED_T.sum(), 3), 'despachado_t': _r(g.DESP_T.sum(), 3),
                       'cancelado_t': _r(g.CANC_T.sum(), 3), 'saldo_t': _r(g.SALDO_T.sum(), 3), 'clientes': clientes})
    linhas.sort(key=lambda x: -x['saldo_t'])
    return {
        'totais': {'pedido_t': _r(df.PED_T.sum(), 3), 'despachado_t': _r(df.DESP_T.sum(), 3),
                   'cancelado_t': _r(df.CANC_T.sum(), 3), 'saldo_t': _r(df.SALDO_T.sum(), 3),
                   'pedidos': int(df.PEDIDO.nunique()), 'clientes': int(df.CLIENTE.nunique())},
        'linhas': linhas,
        'opcoes': opcoes(todos, FILTROS_SALDO),
    }


def saldo(filtros: dict[str, list[str]] | None = None, desde: date | None = None, ate: date | None = None) -> dict:
    """`desde`/`ate` filtram pela data de criação do pedido (no BI, o segmentador de data)."""
    todos = ler_saldo()
    df = filtrar(todos, filtros or {}, FILTROS_SALDO)
    if desde:
        df = df[df.DATA >= pd.Timestamp(desde)]
    if ate:
        df = df[df.DATA <= pd.Timestamp(ate)]
    return montar_saldo(df, todos)
