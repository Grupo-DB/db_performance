"""
Visão geral do almoxarifado: estoque do SGA agrupado por GRUPO DE ITENS.

Lê só do ERP (somente leitura) e devolve, por grupo-raiz de GRUPOALMOXARIFADO:
itens, itens com saldo, valor em estoque e a situação contra o estoque mínimo
(QUANTESTOQUE.QESTQESTMIN). Mais as movimentações dos últimos dias
(MOVESTOQUE) e o detalhe de cada grupo (subgrupos e itens abaixo do mínimo).

Regras levantadas no SGA em 11/11/2026:

- Saldo, mínimo, máximo e custo médio ficam em QUANTESTOQUE, linha
  QESTQEMP = 1 e QESTQREF = 0, uma por filial (QESTQFIL). Filial 0 é a matriz.
- GRUPOALMOXARIFADO é uma árvore (GALMGALMPAI; 0 = raiz). Os cards são as
  RAÍZES; os subgrupos aparecem no detalhe.
- O percentual do card só olha os itens COM mínimo cadastrado: só uma parte
  tem (ex.: Mecânico Automotivo, 355 de 1.753 itens com saldo). Os sem mínimo
  saem contados à parte, para o almoxarifado ir completando no SGA.
- MOVESTOQUE.MESTQREFTIPO: 1 = entrada por nota, 2 = requisição (baixa) do
  almoxarifado, 3 = acerto/inventário, 6 = saída por nota (venda/transferência),
  8 = só custo (quantidade zero). MESTQQUANT tem sinal; MESTQCUSTO é o valor
  total da linha, também com sinal.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
from django.core.cache import cache
from sqlalchemy import text

from pedidosVenda.erp import engine

EMPRESA = 1
CACHE_SEG = 600
DIAS_MOVIMENTO = 30
MAX_ITENS_CRITICOS = 150

# Raízes que não são almoxarifado: produto acabado, serviço, imobilizado e
# grupos contábeis/fiscais. Comparação pelo nome normalizado (o código pode
# mudar entre bases, o nome é o que o almoxarifado reconhece).
RAIZES_FORA = {
    'IMOBILIZADO / INVESTIMENTO',
    'SERVICO DE TERCEIRO',
    'PRODUTO/SERVICO (VENDA)',
    'PRODUTO ATM (VENDA)',
    'PRODUTO (REVENDA)',
    'ITENS IMPORTACAO (NF)',
    'ACERTO',
    'ICMS (ITENS ESPECIAIS)',
    'ITENS OBSOLETOS',
}

# Custo unitário acima disto é lixo de cadastro (há 3e151 num grupo de venda).
CUSTO_UNITARIO_MAX = 10_000_000

TIPOS_MOVIMENTO = {1: 'Entrada (nota)', 2: 'Requisição', 3: 'Acerto', 6: 'Saída (nota)'}

FAIXAS = (
    (90, 'excelente', 'Excelente'),
    (75, 'adequado', 'Adequado'),
    (50, 'alerta', 'Alerta'),
    (0, 'critico', 'Crítico'),
)


def situacao(percentual: float | None) -> tuple[str, str]:
    """Faixa do card pelo % de itens com mínimo que estão no mínimo ou acima."""
    if percentual is None:
        return 'sem_minimo', 'Sem mínimo cadastrado'
    for piso, chave, rotulo in FAIXAS:
        if percentual >= piso:
            return chave, rotulo
    return 'critico', 'Crítico'


def _num(v, padrao=0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return padrao
    return padrao if math.isnan(f) or math.isinf(f) else f


# ── Leitura do ERP ───────────────────────────────────────────────────────────

_SQL_GRUPOS = text("""
    SELECT GALMCOD, GALMNOME, GALMGALMPAI, GALMBLOQ
    FROM GRUPOALMOXARIFADO
""")

_SQL_FILIAIS = text("""
    SELECT FILCOD, FILNOME FROM FILIAL WHERE FILEMP = :emp
""")

# Itens com a linha de saldo da(s) filial(is). Item sem linha em QUANTESTOQUE
# entra com saldo zero (LEFT JOIN) — conta como item do grupo, sem saldo.
_SQL_ITENS = """
    SELECT ESTQCOD, ESTQNOME, ESTQREF, ESTQGALM, ESPSIGLA,
           COALESCE(QESTQFIL, -1)    FIL,
           COALESCE(QESTQESTOQUE, 0) SALDO,
           COALESCE(QESTQESTMIN, 0)  MINIMO,
           COALESCE(QESTQESTMAX, 0)  MAXIMO,
           COALESCE(QESTQCUSTO, 0)   CUSTO
    FROM ESTOQUE
    LEFT JOIN ESPECIE ON ESPCOD = ESTQESP
    LEFT JOIN QUANTESTOQUE ON QESTQESTQ = ESTQCOD AND QESTQEMP = :emp
         AND QESTQREF = 0 AND QESTQTIPO = 0 {filtro_filial}
"""

_SQL_MOVIMENTOS = """
    SELECT MESTQDATA DATA, MESTQREFTIPO TIPO, MESTQESTQ ESTQ, MESTQQUANT QUANT,
           MESTQCUSTO VALOR, MESTQFIL FIL
    FROM MOVESTOQUE
    WHERE MESTQEMP = :emp AND MESTQDATA >= :desde AND MESTQREFTIPO IN (1, 2, 3, 6)
      AND MESTQQUANT <> 0 {filtro_filial}
"""


def _ler(sql, **params) -> pd.DataFrame:
    with engine().connect() as conn:
        return pd.read_sql(sql if not isinstance(sql, str) else text(sql), conn, params=params)


def filiais() -> list[dict]:
    """Matriz (0) + as filiais da empresa no SGA."""
    def ler():
        lista = [{'codigo': 0, 'nome': 'Matriz'}]
        df = _ler(_SQL_FILIAIS, emp=EMPRESA)
        for _, r in df.sort_values('FILCOD').iterrows():
            lista.append({'codigo': int(r.FILCOD), 'nome': str(r.FILNOME or '').strip() or f'Filial {r.FILCOD}'})
        return lista
    return _cacheado('almox:filiais', 3600, ler)


def _cacheado(chave, segundos, func):
    valor = cache.get(chave)
    if valor is None:
        valor = func()
        cache.set(chave, valor, segundos)
    return valor


# ── Montagem (funções puras sobre DataFrames — testáveis sem ERP) ───────────

def arvore(grupos: pd.DataFrame) -> tuple[dict, dict, dict]:
    """(nome por código, raiz de cada grupo, pai de cada grupo)."""
    nome = {int(c): str(n or '').strip() for c, n in zip(grupos.GALMCOD, grupos.GALMNOME)}
    pai = {int(c): int(_num(p)) for c, p in zip(grupos.GALMCOD, grupos.GALMGALMPAI)}

    raiz = {}
    for cod in nome:
        atual, visto = cod, set()
        while pai.get(atual) and pai[atual] != atual and atual not in visto:
            visto.add(atual)
            atual = pai[atual]
        raiz[cod] = atual
    return nome, raiz, pai


def _filho_da_raiz(cod: int, raiz: int, pai: dict) -> int:
    """O subgrupo de 1º nível (filho direto da raiz) onde o grupo `cod` cai."""
    atual, visto = cod, set()
    while pai.get(atual) and pai[atual] != raiz and atual not in visto:
        visto.add(atual)
        atual = pai[atual]
    return atual


def preparar_itens(itens: pd.DataFrame, grupos: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por item (filiais somadas), com raiz/subgrupo e as contas do card."""
    nome, raiz, pai = arvore(grupos)
    bloqueados = {int(c) for c, b in zip(grupos.GALMCOD, grupos.GALMBLOQ) if str(b or '').upper() == 'S'}

    df = itens.copy()
    for col in ('SALDO', 'MINIMO', 'MAXIMO', 'CUSTO'):
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    df.loc[df.CUSTO.abs() > CUSTO_UNITARIO_MAX, 'CUSTO'] = 0.0
    df['VALOR'] = df.SALDO.clip(lower=0) * df.CUSTO

    # Filiais somadas: saldo, mínimo e valor somam; custo vira médio ponderado.
    df = (df.groupby(['ESTQCOD', 'ESTQNOME', 'ESTQREF', 'ESTQGALM', 'ESPSIGLA'], dropna=False, as_index=False)
            .agg(SALDO=('SALDO', 'sum'), MINIMO=('MINIMO', 'sum'), MAXIMO=('MAXIMO', 'sum'), VALOR=('VALOR', 'sum')))

    df['GALM'] = df.ESTQGALM.map(lambda c: int(_num(c)))
    df['RAIZ'] = df.GALM.map(lambda c: raiz.get(c, c))
    df['RAIZ_NOME'] = df.RAIZ.map(lambda c: nome.get(c, f'Grupo {c}'))
    df['SUB'] = [_filho_da_raiz(g, r, pai) for g, r in zip(df.GALM, df.RAIZ)]
    df['SUB_NOME'] = df.SUB.map(lambda c: nome.get(c, f'Grupo {c}'))

    df = df[~df.RAIZ_NOME.str.upper().isin(RAIZES_FORA)]
    df = df[~df.RAIZ.isin(bloqueados)]

    df['TEM_SALDO'] = df.SALDO > 0
    df['TEM_MIN'] = df.MINIMO > 0
    df['NO_MIN'] = df.TEM_MIN & (df.SALDO >= df.MINIMO)
    df['ABAIXO'] = df.TEM_MIN & (df.SALDO < df.MINIMO)
    df['ZERADO'] = df.TEM_MIN & (df.SALDO <= 0)
    return df


def _contas(df: pd.DataFrame) -> dict:
    com_min = int(df.TEM_MIN.sum())
    no_min = int(df.NO_MIN.sum())
    pct = round(100.0 * no_min / com_min, 1) if com_min else None
    chave, rotulo = situacao(pct)
    return {
        'itens': int(len(df)),
        'com_saldo': int(df.TEM_SALDO.sum()),
        'com_minimo': com_min,
        'no_minimo': no_min,
        'abaixo_minimo': int(df.ABAIXO.sum()),
        'zerados': int(df.ZERADO.sum()),
        # Sem mínimo entre os que importam: os que têm saldo (item morto sem
        # saldo e sem mínimo não é pendência de cadastro).
        'sem_minimo': int((df.TEM_SALDO & ~df.TEM_MIN).sum()),
        'valor': round(float(df.VALOR.sum()), 2),
        'percentual': pct,
        'situacao': chave,
        'situacao_rotulo': rotulo,
    }


def _item(r) -> dict:
    falta = max(0.0, float(r.MINIMO) - float(r.SALDO))
    return {
        'codigo': int(r.ESTQCOD),
        'nome': str(r.ESTQNOME or '').strip(),
        'referencia': str(r.ESTQREF or '').strip(),
        'unidade': str(r.ESPSIGLA or '').strip(),
        'subgrupo': r.SUB_NOME,
        'saldo': round(float(r.SALDO), 3),
        'minimo': round(float(r.MINIMO), 3),
        'maximo': round(float(r.MAXIMO), 3),
        'falta': round(falta, 3),
        'cobertura': round(100.0 * float(r.SALDO) / float(r.MINIMO), 1) if r.MINIMO else None,
    }


def montar_grupos(df: pd.DataFrame) -> list[dict]:
    """Cards: uma entrada por raiz, com subgrupos e os itens abaixo do mínimo."""
    saida = []
    for (cod, nome_raiz), g in df.groupby(['RAIZ', 'RAIZ_NOME']):
        if not g.TEM_SALDO.any() and not g.TEM_MIN.any():
            continue  # grupo sem nada em estoque nem mínimo: card vazio
        subgrupos = []
        for (scod, snome), s in g.groupby(['SUB', 'SUB_NOME']):
            if not s.TEM_SALDO.any() and not s.TEM_MIN.any():
                continue
            subgrupos.append({'codigo': int(scod), 'nome': snome, **_contas(s)})
        subgrupos.sort(key=lambda s: (-s['abaixo_minimo'], -s['valor']))

        criticos = g[g.ABAIXO].copy()
        # Zerados primeiro, depois a menor cobertura do mínimo.
        criticos['ORDEM'] = criticos.SALDO / criticos.MINIMO
        criticos = criticos.sort_values(['ORDEM', 'ESTQNOME']).head(MAX_ITENS_CRITICOS)

        saida.append({
            'codigo': int(cod),
            'nome': nome_raiz,
            **_contas(g),
            'subgrupos': subgrupos,
            'itens_criticos': [_item(r) for r in criticos.itertuples()],
        })
    saida.sort(key=lambda x: -x['valor'])
    return saida


def montar_movimentos(mov: pd.DataFrame, itens: pd.DataFrame, hoje: date) -> dict:
    """Entradas × saídas por dia (valor) e as últimas movimentações."""
    dias = [hoje - timedelta(days=i) for i in range(DIAS_MOVIMENTO - 1, -1, -1)]
    vazio = {'dias': [d.isoformat() for d in dias], 'entradas': [0.0] * len(dias),
             'saidas': [0.0] * len(dias), 'ultimas': []}
    if mov.empty:
        return vazio

    m = mov.copy()
    m['QUANT'] = pd.to_numeric(m.QUANT, errors='coerce').fillna(0.0)
    m['VALOR'] = pd.to_numeric(m.VALOR, errors='coerce').fillna(0.0).abs()
    m.loc[m.VALOR > CUSTO_UNITARIO_MAX * 10, 'VALOR'] = 0.0
    m['DIA'] = pd.to_datetime(m.DATA).dt.date

    # Só itens do almoxarifado (mesmo recorte dos cards).
    info = itens.drop_duplicates('ESTQCOD').set_index('ESTQCOD')
    m = m[m.ESTQ.isin(info.index)]

    entrada = m[m.QUANT > 0].groupby('DIA').VALOR.sum()
    saida = m[m.QUANT < 0].groupby('DIA').VALOR.sum()
    vazio['entradas'] = [round(float(entrada.get(d, 0.0)), 2) for d in dias]
    vazio['saidas'] = [round(float(saida.get(d, 0.0)), 2) for d in dias]

    ult = m.sort_values('DATA', ascending=False).head(15)
    vazio['ultimas'] = [{
        'data': pd.Timestamp(r.DATA).date().isoformat(),
        'tipo': TIPOS_MOVIMENTO.get(int(r.TIPO), str(r.TIPO)),
        'entrada': bool(r.QUANT > 0),
        'codigo': int(r.ESTQ),
        'item': str(info.at[r.ESTQ, 'ESTQNOME'] or '').strip(),
        'grupo': info.at[r.ESTQ, 'RAIZ_NOME'],
        'quantidade': round(abs(float(r.QUANT)), 3),
        'unidade': str(info.at[r.ESTQ, 'ESPSIGLA'] or '').strip(),
        'valor': round(float(r.VALOR), 2),
    } for r in ult.itertuples()]
    return vazio


def resumo(filial: int | None) -> dict:
    """Payload da tela. `filial` None = todas somadas."""
    chave = f'almox:resumo:{"todas" if filial is None else filial}'

    def calcular():
        hoje = date.today()
        filtro = '' if filial is None else 'AND QESTQFIL = :fil'
        params = {'emp': EMPRESA}
        if filial is not None:
            params['fil'] = filial
        grupos = _ler(_SQL_GRUPOS)
        itens = preparar_itens(_ler(_SQL_ITENS.format(filtro_filial=filtro), **params), grupos)

        filtro_mov = '' if filial is None else 'AND MESTQFIL = :fil'
        mov = _ler(_SQL_MOVIMENTOS.format(filtro_filial=filtro_mov),
                   desde=hoje - timedelta(days=DIAS_MOVIMENTO - 1), **params)

        cards = montar_grupos(itens)
        recorte = itens[itens.RAIZ.isin([c['codigo'] for c in cards])]
        return {
            'filial': filial,
            'atualizado_em': pd.Timestamp.now().isoformat(timespec='seconds'),
            'totais': _contas(recorte),
            'grupos': cards,
            'movimentos': montar_movimentos(mov, recorte, hoje),
        }

    return _cacheado(chave, CACHE_SEG, calcular)
