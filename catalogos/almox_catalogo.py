"""
Catálogo de Itens do almoxarifado (17/11/2026) — pesquisa com filtros e
"para onde foi" cada item: as baixas de estoque do SGA.

BAIXAESTOQUE (DICIONARIO_COLUNA do SGA)
- Uma linha por item requisitado/entregue; BESTGRP agrupa a requisição.
- BESTSIT: 0 aprovar, 1 aprovada, 2 reprovada, 3 pendente, 8 ATENDIDA, 9 cancelada,
  10 DEVOLVIDA. Conferido nos dados (17/11): a linha original (8) continua com a
  quantidade cheia em BESTQUANT mesmo depois da devolução (BESTQUANTDEV só acumula);
  a devolução é OUTRA linha (10) com BESTBESTDEV → original e quantidade positiva.
  Líquido = Σ(8) − Σ(10), em quantidade e em custo (BESTCUSTO).
- Destino: BESTCC centro de custo (sempre preenchido; CENTROCUSTO.CCNOMECOMP é o
  caminho com os pais e CCSTCOD '+pai+...+cod+' permite pegar os descendentes com
  LIKE), BESTEQP equipamento (60% das linhas), BESTPEQP parte do equipamento,
  BESTMAN ordem de serviço, BESTCOP contrato pessoal de quem recebeu EPI,
  BESTMOTC motivo de custo, BESTPLACA texto livre.
- Pessoas: BESTFUNREQ requisitante, BESTFUNALMOX almoxarife (FUNCIONARIO).
- BESTDATA data da baixa (BESTDATAAPL = aplicação, pode diferir).
Volume na matriz: ~120 mil linhas/ano, ~10 mil itens; o agregado de 90 dias por
item leva ~1 s no SGA.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date, timedelta

import pandas as pd

from . import almoxarifado as ax

logger = logging.getLogger(__name__)

DIAS_PADRAO = 365              # 26/11/2026: era 90; pedido do usuário (abrir já com 1 ano)
DIAS_MAX = 3 * 366
DIAS_OPCOES = 2 * 365          # centros/equipamentos/requisitantes oferecidos no filtro
MAX_BAIXAS = 1000
POR_PAGINA_MAX = 10000      # a tela pede 48; a exportação para Excel pede tudo
ORDENS = ('nome', 'codigo', 'saldo', 'valor', 'baixado', 'custo_baixado', 'ultima_baixa', 'vezes')

# Sinal da linha: devolução (10) volta para o estoque.
_SINAL = "CASE WHEN B.BESTSIT = 10 THEN -1 ELSE 1 END"

_SQL_BAIXAS_ITEM = f"""
    SELECT B.BESTESTQ ESTQ,
           SUM({_SINAL} * B.BESTQUANT) QUANT,
           SUM({_SINAL} * B.BESTCUSTO) CUSTO,
           SUM(CASE WHEN B.BESTSIT = 8 THEN 1 ELSE 0 END) VEZES,
           MAX(CASE WHEN B.BESTSIT = 8 THEN B.BESTDATA END) ULTIMA,
           COUNT(DISTINCT B.BESTCC) N_CC,
           COUNT(DISTINCT NULLIF(B.BESTEQP, 0)) N_EQP
    FROM BAIXAESTOQUE B
    {{join_cc}}
    WHERE B.BESTEMP = :emp AND B.BESTSIT IN (8, 10)
      AND B.BESTDATA >= :desde AND B.BESTDATA < :ate {{filtros}}
    GROUP BY B.BESTESTQ
"""

# Destino mais frequente de cada item no período (para mostrar no cartão).
_SQL_DESTINO_TOPO = f"""
    SELECT ESTQ, CC_NOME, EQP_NOME FROM (
        SELECT B.BESTESTQ ESTQ, C.CCNOMECOMP CC_NOME, E.EQPNOME EQP_NOME,
               ROW_NUMBER() OVER (PARTITION BY B.BESTESTQ ORDER BY SUM({_SINAL} * B.BESTQUANT) DESC) N
        FROM BAIXAESTOQUE B
        JOIN CENTROCUSTO C ON C.CCCOD = B.BESTCC
        LEFT JOIN EQUIPAMENTO E ON E.EQPCOD = NULLIF(B.BESTEQP, 0)
        WHERE B.BESTEMP = :emp AND B.BESTSIT IN (8, 10)
          AND B.BESTDATA >= :desde AND B.BESTDATA < :ate {{filtros}}
        GROUP BY B.BESTESTQ, C.CCNOMECOMP, E.EQPNOME
    ) X WHERE N = 1
"""

_SQL_BAIXAS_DETALHE = f"""
    SELECT TOP {MAX_BAIXAS}
           B.BESTCOD COD, B.BESTGRP REQ, B.BESTSIT SIT, B.BESTDATA DATA, B.BESTDATAAPL DATA_APL,
           B.BESTFIL FIL, B.BESTQUANT QUANT, B.BESTQUANTDEV QUANT_DEV, B.BESTCUSTO CUSTO,
           B.BESTCUSTOUNIT CUSTO_UNIT, B.BESTBESTDEV ORIGEM,
           B.BESTCC CC, COALESCE(C.CCNOMECOMP, '') CC_NOME,
           COALESCE(B.BESTEQP, 0) EQP, COALESCE(E.EQPNOME, '') EQP_NOME, COALESCE(E.EQPPLACA, '') EQP_PLACA,
           COALESCE(P.PEQPNOME, '') PARTE, COALESCE(B.BESTMAN, 0) OS,
           COALESCE(FR.FUNNOME, '') REQUISITANTE, COALESCE(FA.FUNNOME, '') ALMOXARIFE,
           COALESCE(NULLIF(LTRIM(RTRIM(CP.COPNOME)), ''), FC.FORNOME, '') COLABORADOR,
           COALESCE(M.MOTCNOME, '') MOTIVO, COALESCE(B.BESTPLACA, '') PLACA
    FROM BAIXAESTOQUE B
    LEFT JOIN CENTROCUSTO C ON C.CCCOD = B.BESTCC
    LEFT JOIN EQUIPAMENTO E ON E.EQPCOD = NULLIF(B.BESTEQP, 0)
    LEFT JOIN PARTEEQUIPAMENTO P ON P.PEQPCOD = NULLIF(B.BESTPEQP, 0)
    LEFT JOIN FUNCIONARIO FR ON FR.FUNCOD = NULLIF(B.BESTFUNREQ, 0)
    LEFT JOIN FUNCIONARIO FA ON FA.FUNCOD = NULLIF(B.BESTFUNALMOX, 0)
    LEFT JOIN CONTRATOPESSOAL CP ON CP.COPCOD = NULLIF(B.BESTCOP, 0)
    LEFT JOIN FORNECEDOR FC ON FC.FORCOD = CP.COPFOR
    LEFT JOIN MOTIVOCUSTO M ON M.MOTCCOD = NULLIF(B.BESTMOTC, 0)
    {{join_cc}}
    WHERE B.BESTEMP = :emp AND B.BESTESTQ = :cod AND B.BESTSIT IN (8, 10)
      AND B.BESTDATA >= :desde AND B.BESTDATA < :ate {{filtros}}
    ORDER BY B.BESTDATA DESC, B.BESTCOD DESC
"""

_SQL_OPC_CC = """
    SELECT C.CCCOD COD, C.CCNOMECOMP NOME, C.CCNIVEL NIVEL, C.CCSTCOD CAMINHO, COUNT(*) N
    FROM BAIXAESTOQUE B JOIN CENTROCUSTO C ON C.CCCOD = B.BESTCC
    WHERE B.BESTEMP = :emp AND B.BESTSIT = 8 AND B.BESTDATA >= :desde {filtro_filial}
    GROUP BY C.CCCOD, C.CCNOMECOMP, C.CCNIVEL, C.CCSTCOD
"""
# Os pais dos centros usados também entram (filtrar por "02 - COMERCIAL" pega os filhos).
_SQL_CC_TODOS = "SELECT CCCOD COD, CCNOMECOMP NOME, CCNIVEL NIVEL, CCSTCOD CAMINHO FROM CENTROCUSTO"
_SQL_OPC_EQP = """
    SELECT E.EQPCOD COD, E.EQPNOME NOME, COALESCE(E.EQPPLACA, '') PLACA, COUNT(*) N
    FROM BAIXAESTOQUE B JOIN EQUIPAMENTO E ON E.EQPCOD = B.BESTEQP
    WHERE B.BESTEMP = :emp AND B.BESTSIT = 8 AND B.BESTDATA >= :desde AND B.BESTEQP > 0 {filtro_filial}
    GROUP BY E.EQPCOD, E.EQPNOME, E.EQPPLACA
"""
_SQL_OPC_REQ = """
    SELECT F.FUNCOD COD, F.FUNNOME NOME, COUNT(*) N
    FROM BAIXAESTOQUE B JOIN FUNCIONARIO F ON F.FUNCOD = B.BESTFUNREQ
    WHERE B.BESTEMP = :emp AND B.BESTSIT = 8 AND B.BESTDATA >= :desde AND B.BESTFUNREQ > 0 {filtro_filial}
    GROUP BY F.FUNCOD, F.FUNNOME
"""


# ── Filtros comuns ──────────────────────────────────────────────────────────

def periodo(desde: date | None, ate: date | None, hoje: date | None = None) -> tuple[date, date]:
    """[desde, ate] inclusivo; padrão últimos DIAS_PADRAO dias; no máximo DIAS_MAX."""
    hoje = hoje or date.today()
    ate = ate or hoje
    desde = desde or (ate - timedelta(days=DIAS_PADRAO - 1))
    if desde > ate:
        desde, ate = ate, desde
    if (ate - desde).days > DIAS_MAX:
        desde = ate - timedelta(days=DIAS_MAX)
    return desde, ate


def _filtros_sql(filial: int | None, cc: int | None, eqp: int | None, req: int | None) -> tuple[str, str, dict]:
    """(join_cc, filtros, params) para as consultas de BAIXAESTOQUE."""
    partes, params, join_cc = [], {}, ''
    if filial is not None:
        partes.append('AND B.BESTFIL = :fil')
        params['fil'] = filial
    if cc is not None:
        # Centro escolhido e todos os de baixo.
        join_cc = 'JOIN CENTROCUSTO CF ON CF.CCCOD = B.BESTCC'
        partes.append('AND CF.CCSTCOD LIKE :cc_caminho')
        params['cc_caminho'] = f'%+{int(cc)}+%'
    if eqp is not None:
        partes.append('AND B.BESTEQP = :eqp')
        params['eqp'] = eqp
    if req is not None:
        partes.append('AND B.BESTFUNREQ = :req')
        params['req'] = req
    return join_cc, ' '.join(partes), params


def _params(desde: date, ate: date, extra: dict) -> dict:
    # `ate` exclusivo no SQL: BESTDATA tem hora.
    return {'emp': ax.EMPRESA, 'desde': desde, 'ate': ate + timedelta(days=1), **extra}


def _chave(*partes) -> str:
    return 'almox:cat:' + ':'.join('-' if p is None else str(p) for p in partes)


def baixas_por_item(filial, desde, ate, cc=None, eqp=None, req=None) -> pd.DataFrame:
    """ESTQ, QUANT, CUSTO, VEZES, ULTIMA, N_CC, N_EQP, CC_TOPO, EQP_TOPO (cache 10 min)."""
    def ler():
        join_cc, filtros, extra = _filtros_sql(filial, cc, eqp, req)
        p = _params(desde, ate, extra)
        df = ax._ler(_SQL_BAIXAS_ITEM.format(join_cc=join_cc, filtros=filtros), **p)
        try:
            topo = ax._ler(_SQL_DESTINO_TOPO.format(filtros=filtros.replace('CF.', 'C.')), **p)
            df = df.merge(topo.rename(columns={'CC_NOME': 'CC_TOPO', 'EQP_NOME': 'EQP_TOPO'}), on='ESTQ', how='left')
        except Exception:
            logger.exception('catálogo: falha ao ler o destino principal')
        return df
    return ax._cacheado(_chave('baixas', filial, desde, ate, cc, eqp, req), ax.CACHE_SEG, ler)


# ── Lista ───────────────────────────────────────────────────────────────────

def _sem_acento(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s or '')) if not unicodedata.combining(c)).lower()


def juntar_baixas(df: pd.DataFrame, baixas: pd.DataFrame) -> pd.DataFrame:
    cols = ['ESTQ', 'QUANT', 'CUSTO', 'VEZES', 'ULTIMA', 'N_CC', 'N_EQP', 'CC_TOPO', 'EQP_TOPO']
    b = baixas.reindex(columns=cols).rename(columns={
        'ESTQ': 'ESTQCOD', 'QUANT': 'B_QUANT', 'CUSTO': 'B_CUSTO', 'VEZES': 'B_VEZES', 'ULTIMA': 'B_ULTIMA',
        'N_CC': 'B_NCC', 'N_EQP': 'B_NEQP', 'CC_TOPO': 'B_CC', 'EQP_TOPO': 'B_EQP'})
    b['ESTQCOD'] = pd.to_numeric(b.ESTQCOD, errors='coerce')
    out = df.copy()
    out['ESTQCOD'] = pd.to_numeric(out.ESTQCOD, errors='coerce')
    out = out.merge(b, on='ESTQCOD', how='left')
    for c in ('B_QUANT', 'B_CUSTO', 'B_VEZES', 'B_NCC', 'B_NEQP'):
        out[c] = pd.to_numeric(out[c], errors='coerce').fillna(0.0)
    out['TEM_BAIXA'] = out.B_VEZES > 0
    return out


def filtrar(df: pd.DataFrame, grupos: pd.DataFrame, *, q: str = '', grupo: int | None = None,
            saldo: str = '', situacao: str = '', foto: str = '', compra: str = '', baixa: str = '',
            parados: bool = False, destino: bool = False, modo: str = 'contem') -> pd.DataFrame:
    """Aplica os filtros da tela. `destino` = filtrou centro/equipamento/requisitante:
    só ficam os itens que foram para lá."""
    if grupo is not None:
        _, _, pai = ax.arvore(grupos)
        df = df[df.GALM.isin(ax.descendentes(grupo, ax.filhos_por_grupo(pai)))]
    termos = _sem_acento(q).split()
    if termos and modo == 'igual':
        # Igual (23/11/2026): o texto inteiro bate com o código, a referência ou o nome
        # (sem acento/maiúsculas) — "2446" traz só o item 2446, não 12446 nem "…2446…".
        inteiro = ' '.join(termos)
        campos = (df.ESTQCOD.astype('Int64').astype(str), df.ESTQREF.fillna('').astype(str), df.ESTQNOME.fillna('').astype(str))
        casa = pd.Series(False, index=df.index)
        for c in campos:
            casa |= c.map(lambda v: ' '.join(_sem_acento(v).split())) == inteiro
        df = df[casa]
    elif termos:
        alvo = (df.ESTQCOD.astype('Int64').astype(str) + ' ' + df.ESTQNOME.fillna('').astype(str) + ' '
                + df.ESTQREF.fillna('').astype(str) + ' ' + df.GALM_NOME.fillna('').astype(str)).map(_sem_acento)
        for t in termos:
            df = df[alvo[df.index].str.contains(t, regex=False)]
    if saldo == 'com':
        df = df[df.TEM_SALDO]
    elif saldo == 'sem':
        df = df[~df.TEM_SALDO]
    if situacao == 'abaixo':
        df = df[df.ABAIXO]
    elif situacao == 'atencao':
        df = df[df.ATENCAO]
    elif situacao == 'ok':
        df = df[df.NO_MIN & ~df.ATENCAO]
    elif situacao == 'sem_minimo':
        df = df[~df.TEM_MIN]
    if foto in ('com', 'sem') and 'TEM_FOTO' in df:
        df = df[df.TEM_FOTO == (foto == 'com')]
    if compra in ('com', 'sem') and 'EM_COMPRA' in df:
        df = df[df.EM_COMPRA == (compra == 'com')]
    if destino or baixa == 'com':
        df = df[df.TEM_BAIXA]
    elif baixa == 'sem':
        df = df[~df.TEM_BAIXA]
    if not parados and not termos:
        # Item morto (sem saldo, sem mínimo, sem baixa no período, sem compra) só
        # aparece pesquisando por nome/código ou pedindo os parados.
        vivo = df.TEM_SALDO | df.TEM_MIN | df.TEM_BAIXA
        if 'EM_COMPRA' in df:
            vivo = vivo | df.EM_COMPRA
        df = df[vivo]
    return df


def ordenar(df: pd.DataFrame, ordem: str) -> pd.DataFrame:
    chave, desc = {
        'codigo': ('ESTQCOD', False), 'saldo': ('SALDO', True), 'valor': ('VALOR', True),
        'baixado': ('B_QUANT', True), 'custo_baixado': ('B_CUSTO', True),
        'ultima_baixa': ('B_ULTIMA', True), 'vezes': ('B_VEZES', True),
    }.get(ordem, ('ESTQNOME', False))
    return df.sort_values([chave, 'ESTQNOME'], ascending=[not desc, True], na_position='last')


def _item_catalogo(r) -> dict:
    d = ax._item(r)
    d.pop('compras', None)          # o detalhe da compra fica na gaveta do almoxarifado
    d['referencia'] = str(r.ESTQREF or '').strip()
    d['baixa'] = {
        'quantidade': round(float(r.B_QUANT), 3),
        'custo': round(float(r.B_CUSTO), 2),
        'vezes': int(r.B_VEZES),
        'ultima': ax._data_iso(r.B_ULTIMA),
        'centros': int(r.B_NCC),
        'equipamentos': int(r.B_NEQP),
        'centro_principal': _nome_cc(getattr(r, 'B_CC', '')),
        'equipamento_principal': str(getattr(r, 'B_EQP', '') or '').strip() if not pd.isna(getattr(r, 'B_EQP', None)) else '',
    }
    return d


def _nome_cc(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    return str(v).strip()


def listar(filial: int | None, *, desde: date | None = None, ate: date | None = None,
           q: str = '', grupo: int | None = None, saldo: str = '', situacao: str = '', foto: str = '',
           compra: str = '', baixa: str = '', parados: bool = False, modo: str = 'contem',
           cc: int | None = None, eqp: int | None = None, req: int | None = None,
           ordem: str = 'nome', pagina: int = 1, por_pagina: int = 48, fonte: str = 'sga') -> dict:
    desde, ate = periodo(desde, ate)
    df, erp, _ = ax._preparado(filial, fonte)
    df = juntar_baixas(df, baixas_por_item(filial, desde, ate, cc, eqp, req))
    sel = filtrar(df, erp['grupos'], q=q, grupo=grupo, saldo=saldo, situacao=situacao, foto=foto,
                  compra=compra, baixa=baixa, parados=parados, modo=modo,
                  destino=any(x is not None for x in (cc, eqp, req)))
    sel = ordenar(sel, ordem)
    por_pagina = max(1, min(int(por_pagina), POR_PAGINA_MAX))
    total = int(len(sel))
    paginas = max(1, -(-total // por_pagina))
    pagina = max(1, min(int(pagina), paginas))
    fatia = sel.iloc[(pagina - 1) * por_pagina: pagina * por_pagina]
    return {
        'filial': filial, 'desde': desde.isoformat(), 'ate': ate.isoformat(),
        'total': total, 'pagina': pagina, 'paginas': paginas, 'por_pagina': por_pagina,
        'totais': {
            'baixado_custo': round(float(sel.B_CUSTO.sum()), 2),
            'com_baixa': int(sel.TEM_BAIXA.sum()),
            'valor_estoque': round(float(sel.VALOR.sum()), 2),
        },
        'atualizado_em': erp['lido_em'],
        'itens': [_item_catalogo(r) for r in fatia.itertuples()],
    }


# ── Opções dos filtros ─────────────────────────────────────────────────────

def montar_centros(usados: pd.DataFrame, todos: pd.DataFrame) -> list[dict]:
    """Centros usados nas baixas + os pais deles (filtrar um pai pega os filhos)."""
    por_cod = {int(r.COD): r for r in todos.itertuples()}
    n_por = {int(r.COD): int(r.N) for r in usados.itertuples()}
    cods: set[int] = set()
    for r in usados.itertuples():
        for p in str(r.CAMINHO or '').strip('+').split('+'):
            if p.strip().isdigit():
                cods.add(int(p))
    saida = []
    for c in cods:
        r = por_cod.get(c)
        if r is None:
            continue
        nome = str(r.NOME or '').strip()
        saida.append({'codigo': c, 'nome': nome.split(',')[-1].strip() or nome, 'caminho': nome,
                      'nivel': int(ax._num(r.NIVEL, 1)), 'baixas': n_por.get(c, 0)})
    saida.sort(key=lambda x: [s.strip() for s in x['caminho'].split(',')])
    return saida


def opcoes(filial: int | None) -> dict:
    def ler():
        desde = date.today() - timedelta(days=DIAS_OPCOES)
        f = '' if filial is None else 'AND B.BESTFIL = :fil'
        p = {'emp': ax.EMPRESA, 'desde': desde, **({} if filial is None else {'fil': filial})}
        centros = montar_centros(ax._ler(_SQL_OPC_CC.format(filtro_filial=f), **p), ax._ler(_SQL_CC_TODOS))
        eqp = ax._ler(_SQL_OPC_EQP.format(filtro_filial=f), **p)
        req = ax._ler(_SQL_OPC_REQ.format(filtro_filial=f), **p)
        grupos = ax._ler(ax._SQL_GRUPOS)
        return {
            'centros': centros,
            'equipamentos': sorted(({'codigo': int(r.COD), 'nome': str(r.NOME or '').strip(),
                                     'placa': str(r.PLACA or '').strip(), 'baixas': int(r.N)} for r in eqp.itertuples()),
                                   key=lambda x: x['nome']),
            'requisitantes': sorted(({'codigo': int(r.COD), 'nome': str(r.NOME or '').strip(), 'baixas': int(r.N)}
                                     for r in req.itertuples()), key=lambda x: x['nome']),
            'grupos': montar_grupos_filtro(grupos),
            'filiais': ax.filiais(),
            'dias_padrao': DIAS_PADRAO,
        }
    return ax._cacheado(_chave('opcoes', filial), 3600, ler)


def montar_grupos_filtro(grupos: pd.DataFrame) -> list[dict]:
    """Árvore de grupos achatada em ordem (pai antes dos filhos), sem as raízes fora do almoxarifado."""
    nome, raiz, pai = ax.arvore(grupos)
    filhos = ax.filhos_por_grupo(pai)
    bloqueados = {int(c) for c, b in zip(grupos.GALMCOD, grupos.GALMBLOQ) if str(b or '').upper() == 'S'}
    saida: list[dict] = []

    def visita(cod: int, nivel: int):
        saida.append({'codigo': cod, 'nome': nome.get(cod, f'Grupo {cod}'), 'nivel': nivel})
        for f in sorted(filhos.get(cod, []), key=lambda c: nome.get(c, '')):
            if f not in bloqueados:
                visita(f, nivel + 1)

    raizes = sorted((c for c in nome if raiz.get(c, c) == c), key=lambda c: nome.get(c, ''))
    for r in raizes:
        if str(nome.get(r, '')).upper() in ax.RAIZES_FORA or r in bloqueados:
            continue
        visita(r, 0)
    return saida


# ── Detalhe: para onde foi ─────────────────────────────────────────────────

def montar_detalhe(df: pd.DataFrame) -> dict:
    """Linhas de baixa → totais, agrupamentos por destino e por mês, e a lista."""
    linhas = []
    for r in df.itertuples():
        dev = int(ax._num(r.SIT)) == 10
        sinal = -1 if dev else 1
        cc = str(r.CC_NOME or '').strip()
        linhas.append({
            'codigo': int(r.COD),
            'requisicao': int(ax._num(r.REQ)) or None,
            'data': ax._data_iso(r.DATA),
            'data_aplicacao': ax._data_iso(r.DATA_APL),
            'filial': int(ax._num(r.FIL)),
            'devolucao': dev,
            'quantidade': round(sinal * ax._num(r.QUANT), 3),
            'devolvido': round(ax._num(r.QUANT_DEV), 3) if not dev else 0.0,
            'custo': round(sinal * ax._num(r.CUSTO), 2),
            'custo_unitario': round(ax._num(r.CUSTO_UNIT), 4),
            'centro_codigo': int(ax._num(r.CC)) or None,
            'centro': cc.split(',')[-1].strip() if cc else '',
            'centro_caminho': cc,
            'equipamento_codigo': int(ax._num(r.EQP)) or None,
            'equipamento': str(r.EQP_NOME or '').strip(),
            'placa': str(r.EQP_PLACA or '').strip() or str(r.PLACA or '').strip(),
            'parte': str(r.PARTE or '').strip(),
            'os': int(ax._num(r.OS)) or None,
            'requisitante': str(r.REQUISITANTE or '').strip(),
            'almoxarife': str(r.ALMOXARIFE or '').strip(),
            'colaborador': str(r.COLABORADOR or '').strip(),
            'motivo': str(r.MOTIVO or '').strip(),
        })

    def agrupar(chave, rotulo, extra=None):
        g: dict = {}
        for l in linhas:
            k = l[chave]
            if not k:
                continue
            a = g.setdefault(k, {'codigo': k, 'nome': l[rotulo], 'quantidade': 0.0, 'custo': 0.0, 'vezes': 0,
                                 **({e: l[e] for e in extra} if extra else {})})
            a['quantidade'] += l['quantidade']
            a['custo'] += l['custo']
            a['vezes'] += 0 if l['devolucao'] else 1
        lista = [{**a, 'quantidade': round(a['quantidade'], 3), 'custo': round(a['custo'], 2)} for a in g.values()]
        return sorted([a for a in lista if a['quantidade'] or a['vezes']], key=lambda a: -a['quantidade'])

    meses: dict[str, dict] = {}
    for l in linhas:
        if l['data']:
            m = meses.setdefault(l['data'][:7], {'mes': l['data'][:7], 'quantidade': 0.0, 'custo': 0.0})
            m['quantidade'] += l['quantidade']
            m['custo'] += l['custo']
    return {
        'totais': {
            'quantidade': round(sum(l['quantidade'] for l in linhas), 3),
            'custo': round(sum(l['custo'] for l in linhas), 2),
            'vezes': sum(1 for l in linhas if not l['devolucao']),
            'devolvido': round(-sum(l['quantidade'] for l in linhas if l['devolucao']), 3),
            'limite': len(linhas) >= MAX_BAIXAS,
        },
        'por_centro': agrupar('centro_codigo', 'centro', ['centro_caminho']),
        'por_equipamento': agrupar('equipamento_codigo', 'equipamento', ['placa']),
        'por_requisitante': agrupar('requisitante', 'requisitante'),
        'por_colaborador': agrupar('colaborador', 'colaborador'),
        'por_mes': sorted(({**m, 'quantidade': round(m['quantidade'], 3), 'custo': round(m['custo'], 2)}
                           for m in meses.values()), key=lambda m: m['mes']),
        'baixas': linhas,
    }


def detalhe(cod: int, filial: int | None, *, desde: date | None = None, ate: date | None = None,
            cc: int | None = None, eqp: int | None = None, req: int | None = None,
            fonte: str = 'sga') -> dict:
    desde, ate = periodo(desde, ate)

    def ler():
        join_cc, filtros, extra = _filtros_sql(filial, cc, eqp, req)
        return ax._ler(_SQL_BAIXAS_DETALHE.format(join_cc=join_cc, filtros=filtros),
                       cod=int(cod), **_params(desde, ate, extra))
    linhas = ax._cacheado(_chave('det', cod, filial, desde, ate, cc, eqp, req), ax.CACHE_SEG, ler)
    df, _, _ = ax._preparado(filial, fonte)
    sel = df[pd.to_numeric(df.ESTQCOD, errors='coerce') == int(cod)]
    item = None
    if len(sel):
        r = next(juntar_baixas(sel, pd.DataFrame()).itertuples())
        item = _item_catalogo(r)
        item.pop('baixa', None)
        compras = sel.iloc[0].get('COMPRAS') if 'COMPRAS' in sel else None
        item.update(ax.resumo_compra(compras))
    return {'codigo': int(cod), 'filial': filial, 'desde': desde.isoformat(), 'ate': ate.isoformat(),
            'item': item, **montar_detalhe(linhas)}
