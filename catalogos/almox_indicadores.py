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
  almoxarifado) → curva ABC (A até 80% do consumo, B até 95%, C o resto),
  giro (consumo 12 m ÷ valor em estoque) e cobertura em dias.
- Idade do estoque: dias desde a última requisição do item (MOVESTOQUE tipo 2
  com quantidade negativa), só itens com saldo, em faixas. Sem requisição
  nenhuma = "nunca saiu" (item comprado e nunca usado, ou só vendido/transferido).
- Entradas (tipo 1, nota) × consumo (tipo 2) mês a mês, 12 meses.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import almoxarifado as ax

MESES = 12
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
    WHERE MESTQEMP = :emp AND MESTQREFTIPO = 2 AND MESTQQUANT < 0 {filtro_filial}
    GROUP BY MESTQESTQ
"""

# Por item para dar para cortar no mesmo recorte de grupos da tela.
_SQL_MENSAL = """
    SELECT YEAR(MESTQDATA) ANO, MONTH(MESTQDATA) MES, MESTQREFTIPO TIPO, MESTQESTQ ESTQ,
           SUM(MESTQCUSTO) VALOR
    FROM MOVESTOQUE
    WHERE MESTQEMP = :emp AND MESTQREFTIPO IN (1, 2) AND MESTQDATA >= :desde {filtro_filial}
    GROUP BY YEAR(MESTQDATA), MONTH(MESTQDATA), MESTQREFTIPO, MESTQESTQ
"""


def _pct(parte: int | float, todo: int | float) -> float | None:
    return round(100.0 * parte / todo, 1) if todo else None


def inicio_meses(hoje: date, meses: int = MESES) -> date:
    """Dia 1º do mês que abre a janela de `meses` meses terminando no mês de hoje."""
    m = hoje.month - (meses - 1)
    a = hoje.year
    while m <= 0:
        m += 12
        a -= 1
    return date(a, m, 1)


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


def curva_abc(df: pd.DataFrame) -> dict:
    """Classes pelo consumo de 12 meses (só itens que tiveram consumo)."""
    c = df[df.CONSUMO12 > 0].sort_values('CONSUMO12', ascending=False)
    total = float(c.CONSUMO12.sum())
    saida = {k: {'itens': 0, 'valor': 0.0, 'valor_estoque': 0.0} for k in ('A', 'B', 'C')}
    if not total:
        return {'total': 0.0, 'classes': saida}
    acum = c.CONSUMO12.cumsum() / total
    # A inclui o item que cruza os 80% (o primeiro já pode passar disso sozinho).
    anterior = acum.shift(fill_value=0.0)
    classe = ['A' if a < 0.80 else 'B' if a < 0.95 else 'C' for a in anterior]
    for k, v, e in zip(classe, c.CONSUMO12, c.VALOR):
        saida[k]['itens'] += 1
        saida[k]['valor'] += float(v)
        saida[k]['valor_estoque'] += float(e)
    for k in saida:
        saida[k]['valor'] = round(saida[k]['valor'], 2)
        saida[k]['valor_estoque'] = round(saida[k]['valor_estoque'], 2)
        saida[k]['pct_itens'] = _pct(saida[k]['itens'], len(c))
        saida[k]['pct_valor'] = _pct(saida[k]['valor'], total)
    return {'total': round(total, 2), 'itens': int(len(c)), 'classes': saida}


def idade(df: pd.DataFrame) -> list[dict]:
    com = df[df.TEM_SALDO]
    total = float(com.VALOR.sum())
    linhas = []
    for chave, rotulo in [(c, r) for _, c, r in FAIXAS_IDADE] + [NUNCA]:
        g = com[com.FAIXA == chave]
        linhas.append({'faixa': chave, 'rotulo': rotulo, 'itens': int(len(g)),
                       'valor': round(float(g.VALOR.sum()), 2), 'pct_valor': _pct(float(g.VALOR.sum()), total)})
    return linhas


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


def mensal(mov: pd.DataFrame, codigos: set[int], hoje: date) -> list[dict]:
    """Entradas por nota e consumo por requisição, R$, mês a mês (meses vazios inclusos)."""
    ini = inicio_meses(hoje)
    chaves = []
    a, m = ini.year, ini.month
    while (a, m) <= (hoje.year, hoje.month):
        chaves.append((a, m))
        m += 1
        if m > 12:
            m, a = 1, a + 1
    ent, con = {}, {}
    if not mov.empty:
        mv = mov.copy()
        mv['VALOR'] = pd.to_numeric(mv.VALOR, errors='coerce').fillna(0.0)
        mv = mv[mv.ESTQ.astype(int).isin(codigos) & (mv.VALOR.abs() < ax.CUSTO_UNITARIO_MAX * 10)]
        for (ano, mes, tipo), v in mv.groupby(['ANO', 'MES', 'TIPO']).VALOR.sum().items():
            alvo = ent if int(tipo) == 1 else con
            alvo[(int(ano), int(mes))] = float(v) if int(tipo) == 1 else -float(v)
    return [{'mes': f'{a}-{m:02d}', 'entradas': round(ent.get((a, m), 0.0), 2),
             'consumo': round(max(0.0, con.get((a, m), 0.0)), 2)} for a, m in chaves]


def _linha_item(r, **extra) -> dict:
    return {'codigo': int(r.ESTQCOD), 'nome': str(r.ESTQNOME or '').strip(), 'unidade': str(r.ESPSIGLA or '').strip(),
            'grupo': r.RAIZ_NOME, 'saldo': round(float(r.SALDO), 3), 'valor': round(float(r.VALOR), 2),
            'consumo_12m': round(float(r.CONSUMO12), 2), 'tem_foto': bool(getattr(r, 'TEM_FOTO', False)),
            'ultima_saida': r.ULTIMA_SAIDA.isoformat() if r.ULTIMA_SAIDA else None, **extra}


def montar(df: pd.DataFrame, mov: pd.DataFrame, hoje: date) -> dict:
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
        'idade': idade(df),
        'abc': curva_abc(df),
        'mensal': mensal(mov, set(int(x) for x in df.ESTQCOD), hoje),
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
        mov = ax._ler(_SQL_MENSAL.format(filtro_filial=f_m), desde=inicio_meses(hoje), **params)
        return {'ultima': {int(e): pd.Timestamp(u).date() for e, u in zip(ult.ESTQ, ult.ULTIMA) if pd.notna(u)},
                'mov': mov}
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
        return {'filial': filial, 'fonte': fonte, 'atualizado_em': erp['lido_em'], 'meses': MESES,
                'parado_dias': PARADO_DIAS, **montar(df, extras['mov'], hoje)}

    return ax._cacheado(chave, ax.CACHE_SEG, calcular)
