"""
Visão geral do almoxarifado: estoque do SGA agrupado por GRUPO DE ITENS.

Lê saldo, custo, árvore de grupos e movimentações do ERP (somente leitura) e
devolve, por grupo-raiz de GRUPOALMOXARIFADO: itens, itens com saldo, valor em
estoque e a situação contra o estoque mínimo. Mais as movimentações dos últimos
dias (MOVESTOQUE) e o detalhe de cada grupo (subgrupos e listas de itens).

ESTOQUE MÍNIMO (13/11/2026): por padrão vale o do SGA (QESTQESTMIN). Com
?fonte=manager vale o cadastrado no Manager (models.MinimoEstoque, por item e
filial) onde existir — item × filial sem cadastro continua com o do SGA. Mínimo
0 gravado no Manager anula o do SGA. E entrou o ATENÇÃO: item que ainda não está abaixo do
mínimo mas cujo saldo cobre só até o prazo do grupo pelo consumo médio
(requisições dos últimos DIAS_CONSUMO dias). Prazo por grupo em
models.PrazoAtencaoGrupo, herdado pelos subgrupos; sem cadastro: 45 dias para
embalagens e 7 para o resto (pedido do almoxarifado em 12/11/2026).

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

COMPRA EM ANDAMENTO (16/11/2026): cada item mostra as requisições de compra
abertas e em que pé está o processo. Regras do dicionário do SGA
(DICIONARIO_COLUNA):

- PENDENCIACOMPRA é a requisição (PCOMCOD = número mostrado ao usuário;
  PCOMSIT 0 pendente, 1 concluída, 2 cancelada, 3 bloqueada) e
  ITEMPENDENCIACOMPRA o item (IPCOMSIT 0 pendente, 1 coleta de preço, 2 ordem
  de compra, 3 comprado/recebido, 4 cancelado, 5 desclassificado). Aberto =
  item 0/1/2 em requisição 0/3. A filial é a da requisição (PCOMFIL).
- PROCESSOCOMPRA é a coleta/ordem (PCOSIT 0 coleta, 1 ordem, 2 coleta
  desclassificada, 3 coleta cancelada, 4 contrato; PCOSITAPROV 0 pendente,
  1 aprovada, 2 reprovada, 9 não se aplica). ITEMPROCESSOCOMPRA.IPCOIPCOM liga
  ao item da requisição; IPCOQUANTFAT é o que já entrou por nota.
- Previsão de entrega = IPCOMDATA + IPCOMPRAZO dias (o que o SGA mostra no
  acompanhamento); sem prazo no item vale o da ordem (IPCOPRENT/PCOPRENT sobre
  PCODATAPED). Mais da metade das ordens abertas não tem prazo nenhum: aí não
  há previsão nem "atrasada". Ordem já recebida por inteiro não conta.
- Só entram os dos últimos DIAS_COMPRA (30) dias: requisição aberta no período
  ou ordem emitida no período (17/11/2026).
- PCOMSITAPROV (aprovação da requisição) está sempre 0 — a empresa não usa.

FOTO (16/11/2026): a foto do item fica em ESTOQUEFOTO.ESTQFFOTO (BMP no banco,
~2 a 5 MB cada; 3.288 itens têm). A lista marca quem tem (só a chave, leitura
leve) e a foto vem sob demanda reduzida para JPEG (miniatura ~12 KB, cache 1 dia).
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta

import pandas as pd
from django.core.cache import cache
from sqlalchemy import text

from pedidosVenda.erp import engine

logger = logging.getLogger(__name__)

EMPRESA = 1
CACHE_SEG = 600
DIAS_MOVIMENTO = 30
DIAS_CONSUMO = 90          # janela do consumo médio diário
PRAZO_PADRAO = 7           # dias de cobertura que acendem o atenção
PRAZO_EMBALAGEM = 45       # grupo cujo nome começa com EMBALAG (e os de baixo); a raiz
                           # "MATERIA PRIMA / EMBALAGEM" não, senão a matéria-prima herdava
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

# Itens com a linha de saldo da(s) filial(is), com o mínimo do SGA. Item sem linha em QUANTESTOQUE
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

# Consumo = requisições do almoxarifado (tipo 2) líquidas de devolução. Acerto
# (3) é inventário e saída por nota (6) é venda/transferência: não entram.
_SQL_CONSUMO = """
    SELECT MESTQESTQ ESTQ, -SUM(MESTQQUANT) CONSUMO
    FROM MOVESTOQUE
    WHERE MESTQEMP = :emp AND MESTQDATA >= :desde AND MESTQREFTIPO = 2 {filtro_filial}
    GROUP BY MESTQESTQ
"""


_SQL_MOVIMENTOS = """
    SELECT MESTQDATA DATA, MESTQREFTIPO TIPO, MESTQESTQ ESTQ, MESTQQUANT QUANT,
           MESTQCUSTO VALOR, MESTQFIL FIL
    FROM MOVESTOQUE
    WHERE MESTQEMP = :emp AND MESTQDATA >= :desde AND MESTQREFTIPO IN (1, 2, 3, 6)
      AND MESTQQUANT <> 0 {filtro_filial}
"""


# Itens de requisição de compra em aberto, com a ordem (se já houver) e quantas
# coletas de preço estão abertas. Uma linha por item de requisição.
_SQL_COMPRAS = """
    SELECT I.IPCOMITEM ESTQ, PC.PCOMFIL FIL, PC.PCOMCOD REQ, PC.PCOMDATA DATA_REQ,
           I.IPCOMQUANT QUANT, I.IPCOMSIT SIT, PC.PCOMPRIORIDADE PRIORIDADE,
           COALESCE(FR.FUNNOME, '') REQUISITANTE, COALESCE(FC.FUNNOME, '') COMPRADOR,
           O.PCOCOD ORDEM, O.PCODATAORDEM DATA_ORDEM, O.PCOSITAPROV APROV_ORDEM,
           COALESCE(O.FORNOME, '') FORNECEDOR, O.IPCOQUANT QUANT_ORDEM,
           O.IPCOQUANTFAT QUANT_RECEBIDA, O.IPCOQUANTCANC QUANT_CANCELADA,
           CASE WHEN COALESCE(NULLIF(I.IPCOMPRAZO, 0), NULLIF(O.IPCOPRENT, 0), NULLIF(O.PCOPRENT, 0)) IS NOT NULL
                THEN DATEADD(day, COALESCE(NULLIF(I.IPCOMPRAZO, 0), NULLIF(O.IPCOPRENT, 0), NULLIF(O.PCOPRENT, 0)),
                             CASE WHEN I.IPCOMDATA > '19000101' THEN I.IPCOMDATA ELSE O.PCODATAPED END) END PREVISAO,
           (SELECT COUNT(*) FROM ITEMPROCESSOCOMPRA IC JOIN PROCESSOCOMPRA C ON C.PCOCOD = IC.IPCOPCO
             WHERE IC.IPCOIPCOM = I.IPCOMCOD AND C.PCOSIT = 0) COLETAS
    FROM ITEMPENDENCIACOMPRA I
    JOIN PENDENCIACOMPRA PC ON PC.PCOMCOD = I.IPCOMPCOM
    LEFT JOIN FUNCIONARIO FR ON FR.FUNCOD = COALESCE(NULLIF(I.IPCOMFUNREQ, 0), PC.PCOMFUNREQ)
    LEFT JOIN FUNCIONARIO FC ON FC.FUNCOD = PC.PCOMCOMPRADOR
    OUTER APPLY (
        SELECT TOP 1 P.PCOCOD, P.PCODATAORDEM, P.PCOSITAPROV, F.FORNOME, P.PCODATAPED, P.PCOPRENT,
               IP.IPCOQUANT, IP.IPCOQUANTFAT, IP.IPCOQUANTCANC, IP.IPCOPRENT
        FROM ITEMPROCESSOCOMPRA IP
        JOIN PROCESSOCOMPRA P ON P.PCOCOD = IP.IPCOPCO
        LEFT JOIN FORNECEDOR F ON F.FORCOD = P.PCOFOR
        WHERE IP.IPCOIPCOM = I.IPCOMCOD AND P.PCOSIT IN (1, 4)
        ORDER BY P.PCODATAORDEM DESC
    ) O
    WHERE PC.PCOMEMP = :emp AND I.IPCOMSIT IN (0, 1, 2) AND PC.PCOMSIT IN (0, 3)
      AND I.IPCOMITEM > 0 {filtro_filial}
      AND (PC.PCOMDATA >= :desde OR O.PCODATAORDEM >= :desde)
"""

# Só a chave: ler o BLOB de 3 mil fotos levaria minutos. Abaixo de 100 bytes não é imagem.
_SQL_FOTOS = "SELECT ESTQFESTQ ESTQ FROM ESTOQUEFOTO WHERE DATALENGTH(ESTQFFOTO) > 100"
_SQL_FOTO = text("SELECT TOP 1 ESTQFFOTO FROM ESTOQUEFOTO WHERE ESTQFESTQ = :cod")
FOTO_LADO_PADRAO = 360
FOTO_LADO_MAX = 1200

# Só o que andou nos últimos N dias: requisição aberta OU ordem emitida nesse
# período (pedido de 17/11/2026 — ordem velha esquecida no SGA poluía a lista).
DIAS_COMPRA = 30

ETAPAS_COMPRA = {0: ('requisicao', 'Requisição pendente'),
                 1: ('coleta', 'Em coleta de preço'),
                 2: ('ordem', 'Ordem de compra')}
ORDEM_ETAPA = {'requisicao': 0, 'coleta': 1, 'ordem': 2}


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


def filhos_por_grupo(pai: dict) -> dict[int, list[int]]:
    filhos: dict[int, list[int]] = {}
    for cod, p in pai.items():
        if p and p != cod:
            filhos.setdefault(p, []).append(cod)
    return filhos


def descendentes(cod: int, filhos: dict) -> set[int]:
    """O grupo e todos abaixo dele (à prova de ciclo no cadastro)."""
    tudo, pilha = {cod}, [cod]
    while pilha:
        for f in filhos.get(pilha.pop(), []):
            if f not in tudo:
                tudo.add(f)
                pilha.append(f)
    return tudo


def prazos_por_grupo(grupos: pd.DataFrame, configurados: dict[int, int] | None = None) -> dict[int, tuple[int, bool]]:
    """(dias, é_próprio) de cada grupo: o cadastrado nele ou no ancestral mais
    próximo; sem cadastro na linha, 45 se ele ou um ancestral se chama EMBALAGEM…, senão 7."""
    nome, _, pai = arvore(grupos)
    configurados = configurados or {}
    saida = {}
    for cod in nome:
        atual, visto, dias, embalagem = cod, set(), None, False
        while atual and atual not in visto:
            visto.add(atual)
            if dias is None and atual in configurados:
                dias = configurados[atual]
            if nome.get(atual, '').strip().upper().startswith('EMBALAG'):
                embalagem = True
            if pai.get(atual) == atual:
                break
            atual = pai.get(atual)
        if dias is None:
            dias = PRAZO_EMBALAGEM if embalagem else PRAZO_PADRAO
        saida[cod] = (int(dias), cod in configurados)
    return saida


def _filho_da_raiz(cod: int, raiz: int, pai: dict) -> int:
    """O subgrupo de 1º nível (filho direto da raiz) onde o grupo `cod` cai."""
    atual, visto = cod, set()
    while pai.get(atual) and pai[atual] != raiz and atual not in visto:
        visto.add(atual)
        atual = pai[atual]
    return atual


def preparar_itens(itens: pd.DataFrame, grupos: pd.DataFrame,
                   minimos: dict[tuple[int, int], float] | None = None,
                   consumo: dict[int, float] | None = None,
                   prazos: dict[int, int] | None = None) -> pd.DataFrame:
    """Uma linha por item (filiais somadas), com raiz/subgrupo e as contas do card.

    MINIMO vem do SGA. `minimos` ((item, filial) → mínimo do Manager) substitui o
    do SGA naquele item × filial; o resto continua com o do SGA. MINIMO_SGA guarda
    o do SGA para a tela mostrar os dois. `consumo` é a quantidade
    requisitada em DIAS_CONSUMO dias por item; `prazos` os cadastrados por grupo.
    """
    nome, raiz, pai = arvore(grupos)
    bloqueados = {int(c) for c, b in zip(grupos.GALMCOD, grupos.GALMBLOQ) if str(b or '').upper() == 'S'}
    prazo = prazos_por_grupo(grupos, prazos)

    df = itens.copy()
    if 'MINIMO' not in df:
        df['MINIMO'] = 0.0
    for col in ('SALDO', 'MINIMO', 'MAXIMO', 'CUSTO'):
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    df.loc[df.CUSTO.abs() > CUSTO_UNITARIO_MAX, 'CUSTO'] = 0.0
    df['VALOR'] = df.SALDO.clip(lower=0) * df.CUSTO
    df['MINIMO_SGA'] = df.MINIMO
    df['MIN_MANAGER'] = False
    if minimos is not None:
        if 'FIL' not in df:
            df['FIL'] = 0
        fil = pd.to_numeric(df.FIL, errors='coerce').fillna(-1).astype(int)
        cod = pd.to_numeric(df.ESTQCOD, errors='coerce').fillna(-1).astype(int)
        chaves = list(zip(cod, fil))
        df['MIN_MANAGER'] = [k in minimos for k in chaves]
        df['MINIMO'] = [float(minimos[k]) if k in minimos else m for k, m in zip(chaves, df.MINIMO)]

    # Filiais somadas: saldo, mínimo e valor somam; custo vira médio ponderado.
    df = (df.groupby(['ESTQCOD', 'ESTQNOME', 'ESTQREF', 'ESTQGALM', 'ESPSIGLA'], dropna=False, as_index=False)
            .agg(SALDO=('SALDO', 'sum'), MINIMO=('MINIMO', 'sum'), MINIMO_SGA=('MINIMO_SGA', 'sum'),
                 MIN_MANAGER=('MIN_MANAGER', 'any'), MAXIMO=('MAXIMO', 'sum'), VALOR=('VALOR', 'sum')))

    df['GALM'] = df.ESTQGALM.map(lambda c: int(_num(c)))
    df['GALM_NOME'] = df.GALM.map(lambda c: nome.get(c, f'Grupo {c}'))
    df['RAIZ'] = df.GALM.map(lambda c: raiz.get(c, c))
    df['RAIZ_NOME'] = df.RAIZ.map(lambda c: nome.get(c, f'Grupo {c}'))
    df['SUB'] = [_filho_da_raiz(g, r, pai) for g, r in zip(df.GALM, df.RAIZ)]
    df['SUB_NOME'] = df.SUB.map(lambda c: nome.get(c, f'Grupo {c}'))

    df = df[~df.RAIZ_NOME.str.upper().isin(RAIZES_FORA)]
    df = df[~df.RAIZ.isin(bloqueados)].copy()

    consumo = consumo or {}
    df['CONSUMO_DIA'] = df.ESTQCOD.map(lambda c: max(0.0, _num(consumo.get(int(c), 0.0))) / DIAS_CONSUMO)
    df['PRAZO'] = df.GALM.map(lambda c: prazo.get(c, (PRAZO_PADRAO, False))[0])
    # Cobertura em dias pelo consumo médio; sem consumo, não dá para projetar.
    df['COBERTURA_DIAS'] = (df.SALDO.clip(lower=0) / df.CONSUMO_DIA).where(df.CONSUMO_DIA > 0)

    df['TEM_SALDO'] = df.SALDO > 0
    df['TEM_MIN'] = df.MINIMO > 0
    df['NO_MIN'] = df.TEM_MIN & (df.SALDO >= df.MINIMO)
    df['ABAIXO'] = df.TEM_MIN & (df.SALDO < df.MINIMO)
    df['ZERADO'] = df.TEM_MIN & (df.SALDO <= 0)
    # Atenção: tem saldo, ainda não está abaixo do mínimo, mas acaba dentro do
    # prazo do grupo. Saldo zero sem mínimo é item comprado sob demanda, não
    # estoque prestes a acabar (na matriz, 13/11: 1.265 itens com eles, 18 sem).
    df['ATENCAO'] = ~df.ABAIXO & df.TEM_SALDO & (df.CONSUMO_DIA > 0) & (df.COBERTURA_DIAS <= df.PRAZO)
    return df


def _data_iso(v) -> str | None:
    if v is None or pd.isna(v):
        return None
    d = pd.Timestamp(v)
    return None if d.year < 1901 else d.date().isoformat()


def montar_compras(df: pd.DataFrame, hoje: date) -> dict[int, list[dict]]:
    """Requisições de compra em aberto por item (ESTQCOD), mais adiantada primeiro."""
    por_item: dict[int, list[dict]] = {}
    for r in df.itertuples():
        sit = int(_num(r.SIT))
        if sit not in ETAPAS_COMPRA:
            continue
        etapa, rotulo = ETAPAS_COMPRA[sit]
        quant = _num(r.QUANT)
        detalhe = []
        ordem = None if pd.isna(r.ORDEM) else int(r.ORDEM)
        previsao = _data_iso(r.PREVISAO) if sit == 2 else None
        recebido = 0.0
        if sit == 2 and ordem:
            pedido = _num(r.QUANT_ORDEM) - _num(r.QUANT_CANCELADA)
            recebido = _num(r.QUANT_RECEBIDA)
            if pedido > 0 and recebido >= pedido:
                continue        # já entrou tudo por nota; o SGA só não virou o item ainda
            quant = max(pedido - recebido, 0.0) if pedido > 0 else quant
            aprov = None if pd.isna(r.APROV_ORDEM) else int(r.APROV_ORDEM)
            if aprov == 0:
                detalhe.append('aguardando aprovação')
            elif aprov == 2:
                detalhe.append('ordem reprovada')
            if recebido > 0:
                detalhe.append('entrega parcial')
        elif sit == 1:
            n = int(_num(r.COLETAS))
            if n:
                detalhe.append(f'{n} cotaç{"ão" if n == 1 else "ões"}')
        atrasada = bool(previsao and previsao < hoje.isoformat())
        if atrasada:
            detalhe.append('entrega atrasada')
        urgente = int(_num(r.PRIORIDADE)) == 1
        por_item.setdefault(int(r.ESTQ), []).append({
            'requisicao': int(r.REQ),
            'data': _data_iso(r.DATA_REQ),
            'filial': int(_num(r.FIL)),
            'quantidade': round(quant, 3),
            'etapa': etapa,
            'etapa_rotulo': rotulo,
            'detalhe': ', '.join(detalhe),
            'urgente': urgente,
            'ordem': ordem if sit == 2 else None,
            'data_ordem': _data_iso(r.DATA_ORDEM) if sit == 2 else None,
            'fornecedor': str(r.FORNECEDOR or '').strip() if sit == 2 else '',
            'previsao': previsao,
            'atrasada': atrasada,
            'recebido': round(recebido, 3),
            'requisitante': str(r.REQUISITANTE or '').strip(),
            'comprador': str(r.COMPRADOR or '').strip(),
        })
    for lista in por_item.values():
        lista.sort(key=lambda c: (-ORDEM_ETAPA[c['etapa']], c['data'] or ''))
    return por_item


def resumo_compra(compras: list[dict] | None) -> dict:
    """Campos do item: etapa mais adiantada, quantidade em compra, texto curto."""
    if not compras:
        return {'compras': [], 'em_compra': 0.0, 'compra_etapa': None, 'compra_texto': ''}
    topo = compras[0]
    texto = topo['etapa_rotulo']
    if topo['ordem']:
        texto += f" {topo['ordem']}"
    else:
        texto += f" (req. {topo['requisicao']})"
    if topo['detalhe']:
        texto += f" — {topo['detalhe']}"
    if len(compras) > 1:
        texto += f" (+{len(compras) - 1})"
    return {
        'compras': compras,
        'em_compra': round(sum(c['quantidade'] for c in compras), 3),
        'compra_etapa': topo['etapa'],
        'compra_texto': texto,
    }


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
        'atencao': int(df.ATENCAO.sum()) if 'ATENCAO' in df else 0,
        'zerados': int(df.ZERADO.sum()),
        # Sem mínimo entre os que importam: os que têm saldo (item morto sem
        # saldo e sem mínimo não é pendência de cadastro).
        'sem_minimo': int((df.TEM_SALDO & ~df.TEM_MIN).sum()),
        'em_compra': int(df.EM_COMPRA.sum()) if 'EM_COMPRA' in df else 0,
        # Foto só interessa para item de estoque: os que têm saldo.
        'com_foto': int((df.TEM_SALDO & df.TEM_FOTO).sum()) if 'TEM_FOTO' in df else 0,
        'sem_foto': int((df.TEM_SALDO & ~df.TEM_FOTO).sum()) if 'TEM_FOTO' in df else 0,
        'abaixo_em_compra': int((df.ABAIXO & df.EM_COMPRA).sum()) if 'EM_COMPRA' in df else 0,
        'valor': round(float(df.VALOR.sum()), 2),
        'percentual': pct,
        'situacao': chave,
        'situacao_rotulo': rotulo,
    }


def _item(r) -> dict:
    falta = max(0.0, float(r.MINIMO) - float(r.SALDO))
    consumo = float(getattr(r, 'CONSUMO_DIA', 0.0) or 0.0)
    cob = getattr(r, 'COBERTURA_DIAS', None)
    cob = None if cob is None or pd.isna(cob) else round(float(cob), 1)
    if r.ABAIXO:
        sit = 'abaixo'
    elif getattr(r, 'ATENCAO', False):
        sit = 'atencao'
    elif r.TEM_MIN:
        sit = 'ok'
    else:
        sit = 'sem_minimo'
    return {
        'codigo': int(r.ESTQCOD),
        'nome': str(r.ESTQNOME or '').strip(),
        'unidade': str(r.ESPSIGLA or '').strip(),
        'grupo': r.RAIZ_NOME,
        'subgrupo': r.SUB_NOME,
        'grupo_item': getattr(r, 'GALM_NOME', r.SUB_NOME),
        'saldo': round(float(r.SALDO), 3),
        'minimo': round(float(r.MINIMO), 3),
        'minimo_sga': round(float(getattr(r, 'MINIMO_SGA', r.MINIMO)), 3),
        'minimo_manager': bool(getattr(r, 'MIN_MANAGER', False)),
        'falta': round(falta, 3),
        'cobertura': round(100.0 * float(r.SALDO) / float(r.MINIMO), 1) if r.MINIMO else None,
        'consumo_dia': round(consumo, 3),
        'cobertura_dias': cob,
        'prazo': int(getattr(r, 'PRAZO', PRAZO_PADRAO)),
        'valor': round(float(r.VALOR), 2),
        'situacao': sit,
        'tem_foto': bool(getattr(r, 'TEM_FOTO', False)),
        **resumo_compra(getattr(r, 'COMPRAS', None)),
    }


def montar_arvore(raiz: int, df: pd.DataFrame, grupos: pd.DataFrame,
                  prazos: dict[int, int] | None = None) -> list[dict]:
    """Subgrupos da raiz em árvore, como a tela "Grupos dos Itens" do SGA.

    Cada nó soma os itens dele e de todos os descendentes. Entram também os
    subgrupos sem item (o SGA mostra todos); bloqueado só entra se tiver item.
    Cada nó leva o prazo de atenção efetivo e se é próprio ou herdado.
    """
    nome, _, pai = arvore(grupos)
    bloq = {int(c) for c, b in zip(grupos.GALMCOD, grupos.GALMBLOQ) if str(b or '').upper() == 'S'}
    filhos = filhos_por_grupo(pai)
    prazo = prazos_por_grupo(grupos, prazos)

    def no(cod, visto):
        sub = df[df.GALM.isin(descendentes(cod, filhos))]
        ramos = [n for f in sorted(filhos.get(cod, []), key=lambda c: nome.get(c, ''))
                 if f not in visto and (n := no(f, visto | {f})) is not None]
        if cod in bloq and sub.empty:
            return None
        dias, proprio = prazo.get(cod, (PRAZO_PADRAO, False))
        return {'codigo': cod, 'nome': nome.get(cod, f'Grupo {cod}'), **_contas(sub),
                'prazo': dias, 'prazo_proprio': proprio, 'filhos': ramos}

    raiz_no = no(raiz, {raiz})
    return raiz_no['filhos'] if raiz_no else []


def montar_grupos(df: pd.DataFrame, grupos: pd.DataFrame | None = None,
                  prazos: dict[int, int] | None = None) -> list[dict]:
    """Cards: uma entrada por raiz, com subgrupos e os itens abaixo do mínimo."""
    saida = []
    prazo = prazos_por_grupo(grupos, prazos) if grupos is not None else {}
    for (cod, nome_raiz), g in df.groupby(['RAIZ', 'RAIZ_NOME']):
        if not g.TEM_SALDO.any() and not g.TEM_MIN.any():
            continue  # grupo sem nada em estoque nem mínimo: card vazio
        prazo_raiz = prazo.get(int(cod), (PRAZO_PADRAO, False))
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
            'prazo': prazo_raiz[0],
            'prazo_proprio': prazo_raiz[1],
            'arvore': montar_arvore(int(cod), g, grupos, prazos) if grupos is not None else [],
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


# ── Dados do app (mínimos e prazos) ─────────────────────────────────────────

def _versao() -> str:
    """Muda a cada edição de mínimo/prazo, para o resumo em cache não ficar velho."""
    v = cache.get('almox:versao')
    if v is None:
        v = '0'
        cache.set('almox:versao', v, None)
    return v


def invalidar() -> None:
    cache.set('almox:versao', pd.Timestamp.now().isoformat(), None)


FONTES = ('sga', 'manager')


def minimos_app(filial: int | None) -> dict[tuple[int, int], float]:
    """(item, filial) → mínimo cadastrado no Manager; filial None = todas."""
    from .models import MinimoEstoque
    qs = MinimoEstoque.objects.all()
    if filial is not None:
        qs = qs.filter(filial=filial)
    return {(int(i), int(f)): float(m) for i, f, m in qs.values_list('item', 'filial', 'minimo')}


def prazos_app() -> dict[int, int]:
    from .models import PrazoAtencaoGrupo
    return dict(PrazoAtencaoGrupo.objects.values_list('grupo', 'dias'))


# ── Leitura do ERP em cache (o que é do app entra por cima a cada pedido) ────

def _erp(filial: int | None) -> dict:
    def ler():
        hoje = date.today()
        params = {'emp': EMPRESA}
        if filial is not None:
            params['fil'] = filial
        f_q = '' if filial is None else 'AND QESTQFIL = :fil'
        f_m = '' if filial is None else 'AND MESTQFIL = :fil'
        consumo = _ler(_SQL_CONSUMO.format(filtro_filial=f_m), desde=hoje - timedelta(days=DIAS_CONSUMO), **params)
        return {
            'grupos': _ler(_SQL_GRUPOS),
            'itens': _ler(_SQL_ITENS.format(filtro_filial=f_q), **params),
            'consumo': {int(e): _num(c) for e, c in zip(consumo.ESTQ, consumo.CONSUMO)},
            'mov': _ler(_SQL_MOVIMENTOS.format(filtro_filial=f_m),
                        desde=hoje - timedelta(days=DIAS_MOVIMENTO - 1), **params),
            'compras': _ler_compras(filial, hoje),
            'fotos': _ler_fotos(),
            'lido_em': pd.Timestamp.now().isoformat(timespec='seconds'),
        }
    return _cacheado(f'almox:erp:{"todas" if filial is None else filial}', CACHE_SEG, ler)


def _ler_compras(filial: int | None, hoje: date) -> dict[int, list[dict]]:
    """Compra em andamento é informação extra: se a consulta falhar, a tela segue sem ela."""
    params = {'emp': EMPRESA, 'desde': hoje - timedelta(days=DIAS_COMPRA)}
    if filial is not None:
        params['fil'] = filial
    try:
        df = _ler(_SQL_COMPRAS.format(filtro_filial='' if filial is None else 'AND PC.PCOMFIL = :fil'), **params)
    except Exception:
        logger.exception('almoxarifado: falha ao ler requisições de compra')
        return {}
    return montar_compras(df, hoje)


def _ler_fotos() -> set[int] | None:
    try:
        return {int(c) for c in _ler(_SQL_FOTOS).ESTQ}
    except Exception:
        logger.exception('almoxarifado: falha ao ler a lista de fotos')
        return None


def miniatura(raw: bytes, lado: int = FOTO_LADO_PADRAO) -> bytes | None:
    """BMP (ou outro formato do PIL) → JPEG com o maior lado ≤ `lado`."""
    from io import BytesIO
    from PIL import Image
    try:
        img = Image.open(BytesIO(bytes(raw)))
        img.thumbnail((lado, lado))
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=82, optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def foto_item(cod: int, lado: int = FOTO_LADO_PADRAO) -> bytes | None:
    """Foto do item em JPEG reduzido, com cache de 1 dia (None = sem foto)."""
    lado = max(64, min(int(lado), FOTO_LADO_MAX))
    chave = f'almox:foto:{cod}:{lado}'
    valor = cache.get(chave)
    if valor is None:
        with engine().connect() as conn:
            raw = conn.execute(_SQL_FOTO, {'cod': cod}).scalar()
        valor = (miniatura(raw, lado) if raw else None) or b''
        cache.set(chave, valor, 86400)
    return valor or None


def _preparado(filial: int | None, fonte: str = 'sga') -> tuple[pd.DataFrame, dict, dict]:
    erp = _erp(filial)
    prazos = prazos_app()
    minimos = minimos_app(filial) if fonte == 'manager' else None
    df = preparar_itens(erp['itens'], erp['grupos'], minimos, erp['consumo'], prazos)
    juntar_compras(df, erp.get('compras') or {})
    juntar_fotos(df, erp.get('fotos'))
    return df, erp, prazos


def juntar_fotos(df: pd.DataFrame, fotos: set[int] | None) -> pd.DataFrame:
    """fotos None = não deu para ler: a coluna nem entra (a tela não marca nada)."""
    if fotos is not None:
        df['TEM_FOTO'] = [int(c) in fotos for c in df.ESTQCOD]
    return df


def juntar_compras(df: pd.DataFrame, compras: dict[int, list[dict]]) -> pd.DataFrame:
    df['COMPRAS'] = [compras.get(int(c)) for c in df.ESTQCOD]
    df['EM_COMPRA'] = df.COMPRAS.map(bool)
    return df


def resumo(filial: int | None, fonte: str = 'sga') -> dict:
    """Payload da tela. `filial` None = todas somadas; `fonte` do mínimo: sga | manager."""
    chave = f'almox:resumo:{"todas" if filial is None else filial}:{fonte}:{_versao()}'

    def calcular():
        itens, erp, prazos = _preparado(filial, fonte)
        cards = montar_grupos(itens, erp['grupos'], prazos)
        recorte = itens[itens.RAIZ.isin([c['codigo'] for c in cards])]
        return {
            'filial': filial,
            'fonte': fonte,
            'atualizado_em': erp['lido_em'],
            'dias_consumo': DIAS_CONSUMO,
            'dias_compra': DIAS_COMPRA,
            'prazo_padrao': PRAZO_PADRAO,
            'totais': _contas(recorte),
            'grupos': cards,
            'movimentos': montar_movimentos(erp['mov'], recorte, date.today()),
        }

    return _cacheado(chave, CACHE_SEG, calcular)


LISTAS = ('abaixo', 'atencao', 'sem_minimo', 'em_compra', 'sem_foto', 'todos')


def filtrar_itens(df: pd.DataFrame, grupos: pd.DataFrame, grupo: int | None, lista: str) -> pd.DataFrame:
    """Itens de um grupo (qualquer nível, com descendentes) ou de todos, por lista."""
    if grupo is not None:
        _, _, pai = arvore(grupos)
        df = df[df.GALM.isin(descendentes(grupo, filhos_por_grupo(pai)))]
    if lista == 'abaixo':
        df = df[df.ABAIXO].assign(_ORD=lambda d: d.SALDO / d.MINIMO).sort_values(['_ORD', 'ESTQNOME'])
    elif lista == 'atencao':
        df = df[df.ATENCAO].sort_values(['COBERTURA_DIAS', 'ESTQNOME'])
    elif lista == 'sem_minimo':
        df = df[df.TEM_SALDO & ~df.TEM_MIN].sort_values(['ESTQNOME'])
    elif lista == 'sem_foto':
        df = df[df.TEM_SALDO & ~df.TEM_FOTO] if 'TEM_FOTO' in df else df.iloc[0:0]
        df = df.sort_values(['ESTQNOME'])
    elif lista == 'em_compra':
        df = df[df.EM_COMPRA] if 'EM_COMPRA' in df else df.iloc[0:0]
        df = df.sort_values(['ESTQNOME'])
    else:
        # "Todos" sem item morto: sem saldo, sem mínimo e sem consumo não interessa.
        df = df[df.TEM_SALDO | df.TEM_MIN | (df.CONSUMO_DIA > 0)].sort_values(['ESTQNOME'])
    return df


def listar_itens(filial: int | None, grupo: int | None, lista: str, fonte: str = 'sga') -> dict:
    df, erp, _ = _preparado(filial, fonte)
    sel = filtrar_itens(df, erp['grupos'], grupo, lista)
    return {'filial': filial, 'fonte': fonte, 'grupo': grupo, 'lista': lista, 'total': int(len(sel)),
            'itens': [_item(r) for r in sel.itertuples()]}


# ── Edição (mínimos e prazos) ──────────────────────────────────────────────

def salvar_minimos(filial: int, itens: list[dict], usuario) -> int:
    """[{codigo, minimo}] da filial no Manager. Vazio apaga (volta a valer o do
    SGA); 0 grava zero, que anula o mínimo do SGA naquele item."""
    from decimal import Decimal, InvalidOperation
    from .models import MinimoEstoque
    feitos = 0
    for linha in itens:
        try:
            codigo = int(linha['codigo'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('Cada item precisa do código.')
        bruto = linha.get('minimo')
        try:
            minimo = Decimal(str(bruto)) if bruto not in (None, '') else None
        except InvalidOperation:
            raise ValueError(f'Mínimo inválido no item {codigo}.')
        if minimo is not None and minimo < 0:
            raise ValueError(f'Mínimo negativo no item {codigo}.')
        if minimo is None:
            MinimoEstoque.objects.filter(item=codigo, filial=filial).delete()
        else:
            MinimoEstoque.objects.update_or_create(
                item=codigo, filial=filial,
                defaults={'minimo': minimo, 'origem': 'app', 'alterado_por': usuario})
        feitos += 1
    invalidar()
    return feitos


def salvar_prazo(grupo: int, dias: int | None, usuario) -> None:
    """Prazo próprio do grupo; vazio volta a herdar do grupo de cima."""
    from .models import PrazoAtencaoGrupo
    if dias in (None, ''):
        PrazoAtencaoGrupo.objects.filter(grupo=grupo).delete()
    else:
        dias = int(dias)
        if not 1 <= dias <= 365:
            raise ValueError('O prazo vai de 1 a 365 dias.')
        PrazoAtencaoGrupo.objects.update_or_create(grupo=grupo, defaults={'dias': dias, 'alterado_por': usuario})
    invalidar()
