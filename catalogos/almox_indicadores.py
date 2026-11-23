"""Indicadores do almoxarifado (Suprimentos › Indicadores).

Pedido de 18/11/2026: um painel separado com gráficos, contadores e o que for
relevante; entre os gráficos, % de itens abaixo do mínimo por grupo e % de
itens sem foto por grupo.

Mesma base da Visão Geral (almoxarifado._preparado: itens, grupos-raiz,
mínimo SGA|Manager, foto, compra em andamento), então os números batem com a
tela do Almoxarifado. Por cima disso, o que só existe aqui:

- % abaixo do mínimo = abaixo ÷ itens COM mínimo (mesma base do card).
- % sem foto = sem foto ÷ itens COM SALDO (item sem saldo não é estoque).
- % sem mínimo = com saldo e sem mínimo ÷ com saldo.
- Consumo de 12 meses (requisições tipo 2 líquidas, como no resto do
  almoxarifado), giro (consumo 12 m ÷ valor em estoque) e cobertura em dias.
- Parado: item com saldo sem requisição (MOVESTOQUE tipo 2 com quantidade
  negativa) há mais de 1 ano, ou que nunca saiu.
- Movimentações dos últimos 30 dias (a mesma leitura da Visão Geral), por dia e
  por grupo-raiz, para o gráfico filtrar por grupo; e as últimas movimentações.

18/11 (tarde): a pedido, saíram idade do estoque, curva ABC, valor por grupo,
entradas × consumo mensal e os cards de parado e giro; entraram a distribuição
do valor por grupo (pizza) e as movimentações da Visão Geral.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import almoxarifado as ax

TOP = 10
FAIXAS_IDADE = (  # (até N dias, chave, rótulo); None = sem limite
    (30, 'ate30', 'Até 30 dias'),
    (90, 'ate90', '31 a 90 dias'),
    (180, 'ate180', '91 a 180 dias'),
    (365, 'ate365', '181 dias a 1 ano'),
    (None, 'mais365', 'Mais de 1 ano'),
)
NUNCA = ('nunca', 'Nunca saiu')
PARADO_DIAS = 365

_SQL_ULTIMA_SAIDA = """
    SELECT MESTQESTQ ESTQ, MAX(MESTQDATA) ULTIMA
    FROM MOVESTOQUE
    WHERE MESTQEMP = :emp AND MESTQREFTIPO IN (2, 3) AND MESTQTIPO = 0 AND MESTQREF = 0
      AND MESTQQUANT < 0 {filtro_filial}   -- requisição ou saída por lançamento de produção (transferência p/ a fábrica)
    GROUP BY MESTQESTQ
"""


def _pct(parte: int | float, todo: int | float) -> float | None:
    return round(100.0 * parte / todo, 1) if todo else None


# ── Montagem (funções puras) ────────────────────────────────────────────────

def recorte(df: pd.DataFrame) -> pd.DataFrame:
    """Só as raízes que viram card na Visão Geral (com algum saldo ou mínimo)."""
    return df[df.RAIZ.isin(df[df.TEM_SALDO | df.TEM_MIN].RAIZ.unique())]


def faixa_idade(dias: float | None) -> str:
    if dias is None or pd.isna(dias):
        return NUNCA[0]
    for limite, chave, _ in FAIXAS_IDADE:
        if limite is None or dias <= limite:
            return chave
    return FAIXAS_IDADE[-1][1]


def juntar_extras(df: pd.DataFrame, consumo12: dict[int, float], ultima: dict[int, date], hoje: date) -> pd.DataFrame:
    df = df.copy()
    df['CONSUMO12'] = [max(0.0, ax._num(consumo12.get(int(c), 0.0))) for c in df.ESTQCOD]
    df['ULTIMA_SAIDA'] = [ultima.get(int(c)) for c in df.ESTQCOD]
    df['DIAS_PARADO'] = [(hoje - u).days if u else None for u in df.ULTIMA_SAIDA]
    df['FAIXA'] = [faixa_idade(d) for d in df.DIAS_PARADO]
    df['PARADO'] = df.TEM_SALDO & df.FAIXA.isin(['mais365', NUNCA[0]])
    return df


# Situação de compra (23/11/2026, pedido: gráfico de itens por situação de compra, "bem destacado").
# Cada item conta uma vez, pela situação mais crítica: nota já lançada e não registrada (o material
# chegou e não entrou) > ordem com entrega atrasada > ordem no prazo > coleta > requisição.
SITUACOES_COMPRA = (
    ('requisicao', 'Requisição aberta'),
    ('coleta', 'Coleta de preço'),
    ('ordem', 'Ordem no prazo'),
    ('atrasada', 'Ordem atrasada'),
    ('nota', 'NF pendente de registro'),
)
TOP_GRUPOS_COMPRA = 10


def situacao_compra(compras) -> str | None:
    """Chave de SITUACOES_COMPRA para a lista de compras abertas do item (None = sem compra)."""
    if not compras:
        return None
    if any(c.get('nota_pendente') for c in compras):
        return 'nota'
    etapa = compras[0].get('etapa')                      # a mais adiantada vem primeiro (montar_compras)
    if etapa == 'ordem':
        return 'atrasada' if any(c.get('atrasada') for c in compras if c.get('etapa') == 'ordem') else 'ordem'
    return etapa if etapa in ('requisicao', 'coleta') else 'requisicao'


def compras(df: pd.DataFrame) -> dict:
    """Itens por situação de compra, com quantos estão abaixo do mínimo, e por grupo-raiz."""
    sit = df.COMPRAS.map(situacao_compra)
    abaixo = df.ABAIXO.astype(bool)
    situacoes = []
    for chave, rotulo in SITUACOES_COMPRA:
        m = sit == chave
        situacoes.append({'chave': chave, 'rotulo': rotulo, 'itens': int(m.sum()), 'abaixo': int((m & abaixo).sum())})
    sem = abaixo & sit.isna()
    grupos = []
    for (cod, nome), idx in df.groupby(['RAIZ', 'RAIZ_NOME']).groups.items():
        s_g, a_g = sit.loc[idx], abaixo.loc[idx]
        linha = {'codigo': int(cod), 'nome': nome, 'sem_compra': int((a_g & s_g.isna()).sum())}
        linha.update({ch: int((s_g == ch).sum()) for ch, _ in SITUACOES_COMPRA})
        linha['total'] = sum(linha[ch] for ch, _ in SITUACOES_COMPRA)
        if linha['total'] or linha['sem_compra']:
            grupos.append(linha)
    grupos.sort(key=lambda g: (-(g['total'] + g['sem_compra']), g['nome']))
    return {
        'dias': ax.DIAS_COMPRA,
        'em_compra': int(sit.notna().sum()),
        'abaixo': int(abaixo.sum()),
        'abaixo_em_compra': int((abaixo & sit.notna()).sum()),
        'abaixo_sem_compra': int(sem.sum()),
        'situacoes': situacoes,
        'grupos': grupos[:TOP_GRUPOS_COMPRA],
    }


def por_grupo(df: pd.DataFrame) -> list[dict]:
    linhas = []
    for (cod, nome), g in df.groupby(['RAIZ', 'RAIZ_NOME']):
        if not g.TEM_SALDO.any() and not g.TEM_MIN.any():
            continue
        c = ax._contas(g)
        parado = g[g.PARADO]
        linhas.append({
            'codigo': int(cod), 'nome': nome,
            'itens': c['itens'], 'com_saldo': c['com_saldo'], 'com_minimo': c['com_minimo'],
            'abaixo_minimo': c['abaixo_minimo'], 'zerados': c['zerados'], 'atencao': c['atencao'],
            'sem_minimo': c['sem_minimo'], 'com_foto': c['com_foto'], 'sem_foto': c['sem_foto'],
            'em_compra': c['em_compra'], 'abaixo_em_compra': c['abaixo_em_compra'],
            'valor': c['valor'],
            'consumo_12m': round(float(g.CONSUMO12.sum()), 2),
            'parados': int(len(parado)), 'valor_parado': round(float(parado.VALOR.sum()), 2),
            'pct_abaixo': _pct(c['abaixo_minimo'], c['com_minimo']),
            'pct_sem_foto': _pct(c['sem_foto'], c['com_saldo']),
            'pct_sem_minimo': _pct(c['sem_minimo'], c['com_saldo']),
            'pct_no_minimo': c['percentual'],
        })
    linhas.sort(key=lambda x: -x['valor'])
    return linhas


ULTIMAS = 15  # por grupo: a tabela filtra por grupo e precisa de linhas de cada um


def movimentos(mov: pd.DataFrame, df: pd.DataFrame, hoje: date) -> dict:
    """Entradas × saídas por dia (R$) nos últimos 30 dias, no total e por grupo-raiz,
    e as últimas movimentações. Mesmas regras de almoxarifado.montar_movimentos."""
    dias = [hoje - timedelta(days=i) for i in range(ax.DIAS_MOVIMENTO - 1, -1, -1)]
    saida = {'dias': [d.isoformat() for d in dias], 'grupos': {}, 'ultimas': []}
    if mov.empty or df.empty:
        return saida
    m = mov.copy()
    m['QUANT'] = pd.to_numeric(m.QUANT, errors='coerce').fillna(0.0)
    m['VALOR'] = pd.to_numeric(m.VALOR, errors='coerce').fillna(0.0).abs()
    m.loc[m.VALOR > ax.CUSTO_UNITARIO_MAX * 10, 'VALOR'] = 0.0
    m['DIA'] = pd.to_datetime(m.DATA).dt.date
    info = df.drop_duplicates('ESTQCOD').set_index('ESTQCOD')
    m = m[m.ESTQ.isin(info.index)]
    if m.empty:
        return saida
    m['RAIZ'] = [int(info.at[e, 'RAIZ']) for e in m.ESTQ]
    m['SENTIDO'] = ['entradas' if q > 0 else 'saidas' for q in m.QUANT]
    soma = m.groupby(['RAIZ', 'SENTIDO', 'DIA']).VALOR.sum()
    for raiz in sorted(m.RAIZ.unique()):
        saida['grupos'][str(raiz)] = {
            sentido: [round(float(soma.get((raiz, sentido, d), 0.0)), 2) for d in dias]
            for sentido in ('entradas', 'saidas')}
    # As 15 mais recentes de cada grupo (inclui as 15 mais recentes no geral).
    ult = m.sort_values('DATA', ascending=False).groupby('RAIZ', sort=False).head(ULTIMAS)
    saida['ultimas'] = [{
        'data': pd.Timestamp(r.DATA).date().isoformat(),
        'tipo': ax.TIPOS_MOVIMENTO.get(int(r.TIPO), str(r.TIPO)),
        'entrada': bool(r.QUANT > 0),
        'codigo': int(r.ESTQ),
        'item': str(info.at[r.ESTQ, 'ESTQNOME'] or '').strip(),
        'grupo_codigo': int(r.RAIZ),
        'grupo': info.at[r.ESTQ, 'RAIZ_NOME'],
        'quantidade': round(abs(float(r.QUANT)), 3),
        'unidade': str(info.at[r.ESTQ, 'ESPSIGLA'] or '').strip(),
        'valor': round(float(r.VALOR), 2),
    } for r in ult.itertuples()]
    return saida


def _linha_item(r, **extra) -> dict:
    return {'codigo': int(r.ESTQCOD), 'nome': str(r.ESTQNOME or '').strip(), 'unidade': str(r.ESPSIGLA or '').strip(),
            'grupo': r.RAIZ_NOME, 'saldo': round(float(r.SALDO), 3), 'valor': round(float(r.VALOR), 2),
            'consumo_12m': round(float(r.CONSUMO12), 2), 'tem_foto': bool(getattr(r, 'TEM_FOTO', False)),
            'ultima_saida': r.ULTIMA_SAIDA.isoformat() if r.ULTIMA_SAIDA else None, **extra}


def montar(df: pd.DataFrame, mov: pd.DataFrame, hoje: date) -> dict:
    """`mov` = MOVESTOQUE dos últimos 30 dias (almoxarifado._erp)."""
    c = ax._contas(df)
    valor = c['valor']
    consumo12 = float(df.CONSUMO12.sum())
    parados = df[df.PARADO]
    com_saldo = df[df.TEM_SALDO]
    return {
        'totais': {
            **c,
            'pct_abaixo': _pct(c['abaixo_minimo'], c['com_minimo']),
            'pct_sem_foto': _pct(c['sem_foto'], c['com_saldo']),
            'pct_sem_minimo': _pct(c['sem_minimo'], c['com_saldo']),
            'pct_com_minimo': _pct(int((df.TEM_SALDO & df.TEM_MIN).sum()), c['com_saldo']),
            'consumo_12m': round(consumo12, 2),
            'giro': round(consumo12 / valor, 2) if valor else None,
            'cobertura_dias': round(valor / (consumo12 / 365.0)) if consumo12 else None,
            'parados': int(len(parados)),
            'valor_parado': round(float(parados.VALOR.sum()), 2),
            'pct_valor_parado': _pct(float(parados.VALOR.sum()), valor),
        },
        'grupos': por_grupo(df),
        'compras': compras(df),
        'movimentos': movimentos(mov, df, hoje),
        'top_valor': [_linha_item(r) for r in com_saldo.nlargest(TOP, 'VALOR').itertuples()],
        'top_consumo': [_linha_item(r) for r in df[df.CONSUMO12 > 0].nlargest(TOP, 'CONSUMO12').itertuples()],
        'top_parados': [_linha_item(r, dias_parado=None if pd.isna(r.DIAS_PARADO) else int(r.DIAS_PARADO))
                        for r in parados.nlargest(TOP, 'VALOR').itertuples()],
    }


# ── Leitura ─────────────────────────────────────────────────────────────────

def _ler_extras(filial: int | None, hoje: date) -> dict:
    def ler():
        params = {'emp': ax.EMPRESA}
        if filial is not None:
            params['fil'] = filial
        f_m = '' if filial is None else 'AND MESTQFIL = :fil'
        ult = ax._ler(_SQL_ULTIMA_SAIDA.format(filtro_filial=f_m), **params)
        return {'ultima': {int(e): pd.Timestamp(u).date() for e, u in zip(ult.ESTQ, ult.ULTIMA) if pd.notna(u)}}
    return ax._cacheado(f'almox:indicadores:extras:{"todas" if filial is None else filial}:{hoje.isoformat()}',
                        ax.CACHE_SEG, ler)


def indicadores(filial: int | None, fonte: str = 'sga') -> dict:
    hoje = date.today()
    chave = f'almox:indicadores:{"todas" if filial is None else filial}:{fonte}:{hoje.isoformat()}:{ax._versao()}'

    def calcular():
        df, erp, _ = ax._preparado(filial, fonte)  # 90 dias: mesmos números da Visão Geral
        df = recorte(df)
        cons12 = ax._consumo(filial, hoje - timedelta(days=364), hoje)['valor']
        extras = _ler_extras(filial, hoje)
        df = juntar_extras(df, cons12, extras['ultima'], hoje)
        return {'filial': filial, 'fonte': fonte, 'atualizado_em': erp['lido_em'],
                'parado_dias': PARADO_DIAS, **montar(df, erp['mov'], hoje)}

    return ax._cacheado(chave, ax.CACHE_SEG, calcular)
