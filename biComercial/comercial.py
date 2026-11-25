"""
BI Comercial (23/11/2026): o relatório do Power BI "Comercial - Dagoberto Barcellos"
dentro do Manager. As consultas são as MESMAS do modelo do Power BI (sql/*.sql,
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
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from django.core.cache import cache
from sqlalchemy import text

from pedidosVenda import erp

logger = logging.getLogger(__name__)

_SQL_DIR = Path(__file__).with_name('sql')
CACHE_SEG = 10 * 60
PERIODO_MAX_DIAS = 3 * 366

# filtro da URL → coluna do DataFrame (os mesmos segmentadores do BI)
FILTROS = {
    'filial': 'FILIAL', 'regiao': 'REGIAO', 'segmento': 'SEGMENTO', 'grupo': 'GRUPO_GESTAO',
    'representante': 'REPRESENTANTE', 'cliente': 'CLIENTE', 'natureza': 'NATUREZA', 'produto': 'PRODUTO',
}
# Naturezas que o segmentador "Nat. Operação" do Power BI deixa marcadas (prints de
# 23/11/2026). Com elas, 2026 até 22/11 bateu com o BI: R$ 126,9 mi; novembro R$ 6,34 mi
# e 22.950,8 t (BI: R$ 6M e 22,95K). Algumas só aparecem em outros anos.
NATUREZAS_PADRAO = (
    'Devol. Venda Merc.Adq. Terceiros (1.411)',
    'Venda De Merc. Ad. Terc. (5.102)', 'Venda De Merc. Ad. Terc. (6.102)',
    'Venda De Merc. Ad. Terc.(Exp.) (7.102)', 'Venda De Merc. Ad. Terc.(St) (5.403)',
    'Venda De Prod. Estab. (5.101)', 'Venda De Prod. Estab. (6.101)',
    'Venda De Prod. Estab. (Exp.) (7.101)', 'Venda De Prod. Estab. (St)(401) (5.401)',
    'Devol. Vendas Simp. Remessa (1.201)', 'Devolucao Venda Prod. Estabelecimento (1.201)',
    'Simples Remessa (5.116)', 'Venda De Merc. Ad. Terc.(St) (5.405)',
    'Venda De Prod. Estab. (Exp.) (5.101)', 'Devolucao De Compras (Geral) (6.202)',
)


def _chave(s: str) -> str:
    return ' '.join(str(s).upper().split())


def naturezas_padrao(disponiveis: list[str]) -> list[str]:
    alvo = {_chave(n) for n in NATUREZAS_PADRAO}
    return [n for n in disponiveis if _chave(n) in alvo]


FILTROS_SALDO = {'filial': 'FILIAL', 'grupo': 'GRUPO', 'produto': 'PRODUTO', 'cliente': 'CLIENTE'}


def _sql(nome: str) -> str:
    return (_SQL_DIR / nome).read_text(encoding='utf-8')


def _ler(sql: str, **params) -> pd.DataFrame:
    with erp.engine().connect() as c:
        return pd.read_sql(text(sql), c, params=params)


def _titulo(s) -> str:
    """Text.Proper do Power Query: 1ª letra de cada sequência de letras maiúscula, o resto
    minúsculo — "(ST)" vira "(St)" e "MERC.ADQ." vira "Merc.Adq.", como o BI mostra."""
    s = '' if s is None or (isinstance(s, float) and pd.isna(s)) else str(s).strip()
    return re.sub(r'[^\W\d_]+', lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), s)


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
        'NATUREZA': r.NATUREZA_OPERACAO.map(_titulo),       # "Nat. Operação" do BI (Text.Proper)
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
        'opcoes': (op := opcoes(todos)),
        # Seleção inicial dos filtros, como o BI abre (o front aplica na 1ª carga).
        'padroes': {'natureza': naturezas_padrao(op['natureza'])},
        'ultima_nota': df.DATA.max().date().isoformat() if len(df) else None,
    }


def painel(desde: date | None = None, ate: date | None = None, filtros: dict[str, list[str]] | None = None) -> dict:
    desde, ate = periodo(desde, ate)
    todos = ler_faturamento(desde, ate)
    return montar(filtrar(todos, filtros or {}), todos, desde, ate)


# ── Mês a mês: cada dia do mês (25/11/2026) ────────────────────────────────

DIAS_SEMANA = ('seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom')
_ZERO = pd.Series({k: 0.0 for k in ('VALOR', 'TN', 'QTD', 'FAT_V', 'CARR_T', 'CARR_U')})


def _mes_limites(mes: str) -> tuple[date, date]:
    """'AAAA-MM' → (1º dia, último dia)."""
    try:
        a, m = (int(x) for x in mes.split('-'))
        ini = date(a, m, 1)
    except (ValueError, AttributeError):
        raise ValueError('Mês inválido (AAAA-MM).')
    fim = (date(a + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
    return ini, fim


def _ler_mes_e_anterior(mes: str) -> tuple[pd.DataFrame, date, date, date, date]:
    ini, fim = _mes_limites(mes)
    ant_fim = ini - timedelta(days=1)
    ant_ini = ant_fim.replace(day=1)
    return ler_faturamento(ant_ini, fim), ini, fim, ant_ini, ant_fim


def _totais(df: pd.DataFrame) -> dict:
    tot = _soma(df.assign(_=1), ['_'])
    return {**_linha(tot.iloc[0] if len(tot) else _ZERO), 'notas': int(df[df.TIPO_NF == 'S'].NFCOD.nunique()),
            'clientes': int(df[df.TIPO_NF == 'S'].CLIENTE_COD.nunique())}


def mes_diario(mes: str, filtros: dict[str, list[str]] | None = None, hoje: date | None = None) -> dict:
    """
    Cada dia do mês (inclusive os sem nota), com as mesmas medidas do painel, e o mês anterior
    para comparar: no mês corrente, o anterior vai só até o mesmo dia (comparação justa).
    """
    hoje = hoje or date.today()
    todos, ini, fim, ant_ini, ant_fim = _ler_mes_e_anterior(mes)
    df_all = filtrar(todos, filtros or {})
    df = df_all[(df_all.DATA >= pd.Timestamp(ini)) & (df_all.DATA <= pd.Timestamp(fim))]
    ant = df_all[(df_all.DATA >= pd.Timestamp(ant_ini)) & (df_all.DATA <= pd.Timestamp(ant_fim))]

    corrente = ini <= hoje <= fim
    ate_dia = hoje.day if corrente else fim.day
    ant_corte = ant_ini + timedelta(days=min(ate_dia, ant_fim.day) - 1)
    ant_mesmo = ant[ant.DATA <= pd.Timestamp(ant_corte)]

    soma_dia = _soma(df, ['DATA']).set_index('DATA')
    notas_dia = df[df.TIPO_NF == 'S'].groupby('DATA').NFCOD.nunique()
    cli_dia = df[df.TIPO_NF == 'S'].groupby('DATA').CLIENTE_COD.nunique()
    seg_dia = df.groupby(['SEGMENTO', 'DATA']).VALOR.sum()
    ant_dia = ant.groupby(ant.DATA.dt.day).VALOR.sum()
    ant_carr = ant[ant.CARR].groupby(ant[ant.CARR].DATA.dt.day).TN.sum()

    dias = []
    d = ini
    while d <= fim:
        ts = pd.Timestamp(d)
        r = soma_dia.loc[ts] if ts in soma_dia.index else _ZERO
        dias.append({**_linha(r, data=d.isoformat(), dia=d.day, semana=DIAS_SEMANA[d.weekday()]),
                     'notas': int(notas_dia.get(ts, 0)), 'clientes': int(cli_dia.get(ts, 0)),
                     'futuro': d > hoje, 'anterior_valor': _r(ant_dia.get(d.day, 0.0)),
                     'anterior_carregamento_t': _r(ant_carr.get(d.day, 0.0), 3)})
        d += timedelta(days=1)

    segmentos = []
    for seg in _soma(df, ['SEGMENTO']).sort_values('VALOR', ascending=False).SEGMENTO:
        serie = seg_dia.loc[seg] if seg in seg_dia.index.get_level_values(0) else pd.Series(dtype=float)
        segmentos.append({'segmento': seg or '(sem segmento)',
                          'valores': [_r(serie.get(pd.Timestamp(x['data']), 0.0)) for x in dias]})

    com_venda = [x for x in dias if x['notas'] or x['valor']]
    melhor = max(com_venda, key=lambda x: x['valor'], default=None)
    return {
        'mes': ini.strftime('%Y-%m'), 'desde': ini.isoformat(), 'ate': fim.isoformat(), 'corrente': corrente,
        'ate_dia': ate_dia,
        'totais': {**_totais(df), 'dias_com_venda': len(com_venda),
                   'media_dia': _r(sum(x['valor'] for x in com_venda) / len(com_venda)) if com_venda else 0.0,
                   'media_dia_t': _r(sum(x['carregamento_t'] for x in com_venda) / len(com_venda), 3) if com_venda else 0.0},
        'anterior': {'mes': ant_ini.strftime('%Y-%m'), 'ate': ant_corte.isoformat(), 'mesmo_periodo': _totais(ant_mesmo),
                     'mes_inteiro': _totais(ant)},
        'melhor_dia': {'data': melhor['data'], 'valor': melhor['valor']} if melhor else None,
        'dias': dias,
        'segmentos': segmentos,
        'ultima_nota': df.DATA.max().date().isoformat() if len(df) else None,
    }


def dia_detalhe(dia: date, filtros: dict[str, list[str]] | None = None) -> dict:
    """As notas de um dia (saídas e devoluções), com os produtos de cada uma, e os rankings do dia."""
    todos, *_ = _ler_mes_e_anterior(dia.strftime('%Y-%m'))
    df = filtrar(todos, filtros or {})
    df = df[df.DATA == pd.Timestamp(dia)]
    chave = ['NFCOD', 'NOTA', 'TIPO_NF', 'CLIENTE', 'REPRESENTANTE', 'CIDADE_FAT', 'UF_FAT', 'NATUREZA', 'FILIAL', 'SEGMENTO']
    notas = []
    if len(df):
        itens = _soma(df, chave + ['PRODUTO', 'UNIDADE'])
        for k, g in itens.groupby(chave, dropna=False, sort=False):
            r = g[['VALOR', 'TN', 'QTD', 'FAT_V', 'CARR_T', 'CARR_U']].sum()
            nfcod, nota, tipo, cliente, rep, cidade, uf, nat, filial, seg = k
            notas.append(_linha(r, nfcod=int(nfcod), nota=int(nota), devolucao=tipo != 'S', cliente=cliente,
                                representante=rep, cidade=cidade if not uf or cidade.upper().endswith(uf.upper()) else f'{cidade}/{uf}', natureza=nat,
                                filial=filial, segmento=seg,
                                produtos=[_linha(p, produto=p.PRODUTO, unidade=p.UNIDADE)
                                          for p in g.sort_values('VALOR', ascending=False).itertuples()]))
        notas.sort(key=lambda n: (-n['valor'], n['nota']))

    def rank(col: str) -> list[dict]:
        return [_linha(r, nome=getattr(r, col) or '—') for r in _soma(df, [col]).sort_values('VALOR', ascending=False).itertuples()]

    return {'dia': dia.isoformat(), 'semana': DIAS_SEMANA[dia.weekday()], 'totais': _totais(df), 'notas': notas,
            'representantes': rank('REPRESENTANTE'), 'produtos': rank('PRODUTO'), 'segmentos': rank('SEGMENTO')}


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
