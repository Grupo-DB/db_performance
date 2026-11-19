"""Leitura do SGA (Minerion) para o Comercial Agro. Só leitura: o app nunca grava no SGA.

Conexão, busca de cliente, preço de tabela e financeiro vêm de pedidosVenda.erp.
Levantado em 19/11/2026:

- Produto agro = ESTOQUE.ESTQGALM em regras.GRUPOS_AGRO. Cotação é em toneladas, então só
  entram os produtos vendidos em TN (granel, big bag); os ensacados (SC) ficam de fora.
- Toneladas do pedido = IPEDQUANT × ESTQPESO ÷ 1000 (ESTQPESO em kg por unidade; TN = 1000).
- Vendido = pedidos ativos (PEDSIT = 0, o único que gera nota) do ano, pelo PEDREP.
- Saldo a carregar = IPEDQUANT − IPEDQUANTDESP − IPEDQUANTCANC, só de pedido dos últimos
  12 meses (há saldo de 2024 nunca baixado); "carregando" = há carregamento pendente
  (NFSIT = 0, NFNUM < 0, como no painel de cargas) para o pedido.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.cache import cache

from pedidosVenda import erp as base

from . import regras

CACHE_SEG = 300
SALDO_DIAS = 365
_AGRO = ','.join(str(g) for g in regras.GRUPOS_AGRO)
_TONS = "(I.IPEDQUANT * CASE WHEN E.ESTQPESO > 0 THEN E.ESTQPESO ELSE 1000 END / 1000.0)"
_SALDO_TONS = ("((I.IPEDQUANT - I.IPEDQUANTDESP - ISNULL(I.IPEDQUANTCANC, 0))"
               " * CASE WHEN E.ESTQPESO > 0 THEN E.ESTQPESO ELSE 1000 END / 1000.0)")


def _reps(repcods) -> str:
    r = base._inteiros(repcods)
    return ','.join(str(x) for x in r) if r else '-1'


def _d(v: date) -> str:
    return v.strftime('%Y%m%d')  # o SQL Server do SGA recusa '2026-01-01' (erro 242)


# ── Produtos e preço padrão ─────────────────────────────────────────────────

def produtos(filial: int = 0, cliente: int | None = None) -> list[dict]:
    """Produtos agro vendidos em tonelada, com o preço padrão (tabela do SGA) na unidade."""
    itens = [p for p in base.catalogo(filial, cliente)
             if p.get('grupo_cod') in regras.GRUPOS_AGRO and (p.get('unidade') or '').upper() in ('TN', 'TON', 'T')]
    return [{'cod': p['cod'], 'descricao': p['descricao'], 'unidade': p['unidade'],
             'preco_padrao': float(p['preco_tabela']), 'preco_cliente': p['preco_cliente']} for p in itens]


def preco_padrao(produto: int, filial: int = 0, cliente: int | None = None) -> float | None:
    return base.precos_vigentes(filial, cliente, [int(produto)]).get(int(produto))


# ── Pedidos agro ────────────────────────────────────────────────────────────

_SQL_PEDIDOS = f"""
    SELECT G.*,
           CASE WHEN EXISTS (SELECT 1 FROM NOTAFISCAL N WHERE N.NFPED = G.pedido AND N.NFSIT = 0 AND N.NFNUM < 0
                               AND N.NFDATACHEGADA >= DATEADD(day, -30, GETDATE())) THEN 1 ELSE 0 END carregando
    FROM (
        SELECT P.PEDNUM pedido, P.PEDCLI cliente, C.CLINOME nome, P.PEDREP repcod, CAST(P.PEDDATA AS DATE) data,
               SUM({_TONS}) toneladas, SUM(I.IPEDQUANT * I.IPEDUNIT) valor, SUM({_SALDO_TONS}) saldo_t
        FROM PEDIDO P
        JOIN ITEMPEDIDO I ON I.IPEDPED = P.PEDNUM
        JOIN ESTOQUE E ON E.ESTQCOD = I.IPEDESTQ
        JOIN CLIENTE C ON C.CLICOD = P.PEDCLI
        WHERE P.PEDSIT = 0 AND E.ESTQGALM IN ({_AGRO}) AND P.PEDREP IN ({{reps}})
          AND P.PEDDATA >= :desde AND P.PEDDATA < :ate
        GROUP BY P.PEDNUM, P.PEDCLI, C.CLINOME, P.PEDREP, CAST(P.PEDDATA AS DATE)
    ) G
"""


def pedidos(repcods, desde: date, ate: date) -> list[dict]:
    chave = f'comercialAgro:pedidos:{_reps(repcods)}:{desde}:{ate}'
    linhas = cache.get(chave)
    if linhas is None:
        linhas = base._limpar(base._rows(_SQL_PEDIDOS.format(reps=_reps(repcods)), desde=_d(desde), ate=_d(ate)))
        for l in linhas:
            l['toneladas'] = round(float(l['toneladas'] or 0), 2)
            l['valor'] = round(float(l['valor'] or 0), 2)
            l['saldo_t'] = round(max(0.0, float(l['saldo_t'] or 0)), 2)
            l['carregando'] = bool(l['carregando'])
        cache.set(chave, linhas, CACHE_SEG)
    return linhas


def vendas(repcods, ano: int, hoje: date | None = None) -> dict:
    """Minhas vendas no ano (safra = ano civil): vendido, valor, clientes, saldo a carregar."""
    hoje = hoje or date.today()
    peds = pedidos(repcods, date(ano, 1, 1), date(ano + 1, 1, 1))
    # Carteira ativa = clientes com pedido agro do vendedor nos 24 meses até hoje.
    carteira = pedidos(repcods, hoje - timedelta(days=730), hoje + timedelta(days=1))
    toneladas = sum(p['toneladas'] for p in peds)
    valor = sum(p['valor'] for p in peds)
    atendidos = {p['cliente'] for p in peds}
    nomes = {p['cliente']: p['nome'] for p in carteira}
    ultima = {}
    for p in carteira:
        ultima[p['cliente']] = max(ultima.get(p['cliente'], p['data']), p['data'])
    sem_compra = sorted(({'cliente': c, 'nome': nomes[c], 'ultima_compra': ultima[c]}
                         for c in nomes if c not in atendidos), key=lambda x: x['ultima_compra'], reverse=True)
    # Saldo só de pedido dos últimos 12 meses: há pedido de 2024 com saldo nunca baixado no SGA.
    corte = hoje - timedelta(days=SALDO_DIAS)
    a_carregar = sorted((p for p in peds + carteira if p['saldo_t'] > 0.01 and p['data'] >= corte),
                        key=lambda p: (not p['carregando'], p['data']))
    vistos, saldo = set(), []
    for p in a_carregar:
        if p['pedido'] not in vistos:
            vistos.add(p['pedido'])
            saldo.append(p)
    return {
        'ano': ano,
        'toneladas': round(toneladas, 1),
        'valor': round(valor, 2),
        'preco_medio_t': round(valor / toneladas, 2) if toneladas else None,
        'pedidos': len(peds),
        'clientes_atendidos': len(atendidos),
        'carteira_ativa': len(nomes),
        'saldo_t': round(sum(p['saldo_t'] for p in saldo), 1),
        'a_carregar': saldo,
        'sem_compra': sem_compra,
    }


def media_preco(repcods, produto: int, ano: int) -> float | None:
    """Preço médio ponderado (R$/t) do produto nos pedidos do vendedor no ano."""
    chave = f'comercialAgro:media:{_reps(repcods)}:{int(produto)}:{ano}'
    v = cache.get(chave)
    if v is None:
        linhas = base._rows(f"""
            SELECT SUM(I.IPEDQUANT * I.IPEDUNIT) valor, SUM(I.IPEDQUANT) qt
            FROM PEDIDO P JOIN ITEMPEDIDO I ON I.IPEDPED = P.PEDNUM
            WHERE P.PEDSIT = 0 AND P.PEDREP IN ({_reps(repcods)}) AND I.IPEDESTQ = :prod
              AND P.PEDDATA >= :desde AND P.PEDDATA < :ate
        """, prod=int(produto), desde=_d(date(ano, 1, 1)), ate=_d(date(ano + 1, 1, 1)))
        l = linhas[0] if linhas else {}
        v = round(float(l['valor']) / float(l['qt']), 2) if l.get('qt') else 0
        cache.set(chave, v, CACHE_SEG)
    return v or None


def historico_cliente(cliente: int, anos: int = 3, hoje: date | None = None) -> list[dict]:
    """Toneladas agro compradas por ano (pedidos ativos), do ano atual para trás."""
    hoje = hoje or date.today()
    linhas = base._rows(f"""
        SELECT YEAR(P.PEDDATA) ano, SUM({_TONS}) toneladas, SUM(I.IPEDQUANT * I.IPEDUNIT) valor
        FROM PEDIDO P JOIN ITEMPEDIDO I ON I.IPEDPED = P.PEDNUM JOIN ESTOQUE E ON E.ESTQCOD = I.IPEDESTQ
        WHERE P.PEDSIT = 0 AND P.PEDCLI = :cli AND E.ESTQGALM IN ({_AGRO}) AND P.PEDDATA >= :desde
        GROUP BY YEAR(P.PEDDATA)
    """, cli=int(cliente), desde=_d(date(hoje.year - anos + 1, 1, 1)))
    por_ano = {int(l['ano']): l for l in linhas}
    return [{'ano': a, 'toneladas': round(float(por_ano[a]['toneladas']), 1) if a in por_ano else 0.0,
             'valor': round(float(por_ano[a]['valor']), 2) if a in por_ano else 0.0}
            for a in range(hoje.year, hoje.year - anos, -1)]


def cliente(cod: int) -> dict | None:
    c = base.detalhar_cliente(int(cod), [])
    if not c:
        return None
    return {'cod': c['cod'], 'nome': (c.get('nome') or '').strip(), 'fantasia': (c.get('fantasia') or '').strip(),
            'documento': c.get('documento') or '', 'cidade': c.get('cidade') or '',
            'celular': c.get('celular') or c.get('telefone') or '', 'repcod': c.get('repcod'),
            'vendedor_carteira': c.get('vendedor_carteira') or '', 'bloqueado': c.get('bloqueado', False)}


def buscar(texto: str, repcods) -> list[dict]:
    return base.buscar_clientes(texto, list(repcods), limite=20)


def financeiro(cod: int) -> dict:
    return base.situacao_financeira(int(cod))


# ── Conferência do pedido lançado ───────────────────────────────────────────

def pedido(numero: int) -> dict | None:
    """Pedido do SGA com os itens, para conferir com a cotação."""
    cab = base._limpar(base._rows("""
        SELECT P.PEDNUM numero, P.PEDCLI cliente, C.CLINOME nome, P.PEDREP repcod, CAST(P.PEDDATA AS DATE) data,
               P.PEDSIT situacao, P.PEDPGTOPRAZOST prazo_texto, P.PEDFIL filial
        FROM PEDIDO P JOIN CLIENTE C ON C.CLICOD = P.PEDCLI WHERE P.PEDNUM = :n
    """, n=int(numero)))
    if not cab:
        return None
    p = cab[0]
    p['prazo_texto'] = (p.get('prazo_texto') or '').strip()
    p['prazo'] = regras.prazo_em_dias(p['prazo_texto'])
    p['itens'] = base._limpar(base._rows(f"""
        SELECT I.IPEDESTQ produto, E.ESTQNOME descricao, {_TONS} toneladas, I.IPEDUNIT preco
        FROM ITEMPEDIDO I JOIN ESTOQUE E ON E.ESTQCOD = I.IPEDESTQ WHERE I.IPEDPED = :n
    """, n=int(numero)))
    for i in p['itens']:
        i['toneladas'] = round(float(i['toneladas'] or 0), 2)
        i['preco'] = round(float(i['preco'] or 0), 2)
    return p


# ── Mercado por município (cruza com o IBGE pelo CIDADE.CIDCODIBGE do cliente) ──

def vendas_por_municipio(desde: date, ate: date, repcods=None) -> dict[int, dict]:
    """Toneladas agro e clientes por município IBGE (cidade do cadastro do cliente)."""
    filtro = f'AND P.PEDREP IN ({_reps(repcods)})' if repcods else ''
    chave = f'comercialAgro:vendas_mun:{_reps(repcods) if repcods else "todos"}:{desde}:{ate}'
    v = cache.get(chave)
    if v is None:
        linhas = base._rows(f"""
            SELECT CI.CIDCODIBGE ibge, COUNT(DISTINCT P.PEDCLI) clientes, SUM({_TONS}) toneladas,
                   SUM(I.IPEDQUANT * I.IPEDUNIT) valor
            FROM PEDIDO P
            JOIN ITEMPEDIDO I ON I.IPEDPED = P.PEDNUM
            JOIN ESTOQUE E ON E.ESTQCOD = I.IPEDESTQ
            JOIN CLIENTE C ON C.CLICOD = P.PEDCLI
            JOIN CIDADE CI ON CI.CIDCOD = C.CLICIDADE
            WHERE P.PEDSIT = 0 AND E.ESTQGALM IN ({_AGRO}) AND P.PEDDATA >= :desde AND P.PEDDATA < :ate
              AND CI.CIDCODIBGE > 0 {filtro}
            GROUP BY CI.CIDCODIBGE
        """, desde=_d(desde), ate=_d(ate))
        v = {int(l['ibge']): {'clientes': int(l['clientes']), 'toneladas': round(float(l['toneladas'] or 0), 1),
                              'valor': round(float(l['valor'] or 0), 2)} for l in linhas}
        cache.set(chave, v, CACHE_SEG)
    return v


def clientes_do_municipio(ibge: int, desde: date, ate: date, repcods=None) -> list[dict]:
    """Quem comprou produto agro no município (cidade do cadastro do cliente) no período."""
    filtro = f'AND P.PEDREP IN ({_reps(repcods)})' if repcods else ''
    linhas = base._limpar(base._rows(f"""
        SELECT C.CLICOD cliente, C.CLINOME nome, R.REPNOME vendedor, COUNT(DISTINCT P.PEDNUM) pedidos,
               SUM({_TONS}) toneladas, SUM(I.IPEDQUANT * I.IPEDUNIT) valor, MAX(CAST(P.PEDDATA AS DATE)) ultima
        FROM PEDIDO P
        JOIN ITEMPEDIDO I ON I.IPEDPED = P.PEDNUM
        JOIN ESTOQUE E ON E.ESTQCOD = I.IPEDESTQ
        JOIN CLIENTE C ON C.CLICOD = P.PEDCLI
        JOIN CIDADE CI ON CI.CIDCOD = C.CLICIDADE
        LEFT JOIN REPRESENTANTE R ON R.REPCOD = C.CLIREP
        WHERE P.PEDSIT = 0 AND E.ESTQGALM IN ({_AGRO}) AND P.PEDDATA >= :desde AND P.PEDDATA < :ate
          AND CI.CIDCODIBGE = :ibge {filtro}
        GROUP BY C.CLICOD, C.CLINOME, R.REPNOME
        ORDER BY SUM({_TONS}) DESC
    """, desde=_d(desde), ate=_d(ate), ibge=int(ibge)))
    for l in linhas:
        l['toneladas'] = round(float(l['toneladas'] or 0), 1)
        l['valor'] = round(float(l['valor'] or 0), 2)
        l['nome'] = (l['nome'] or '').strip()
        l['vendedor'] = (l['vendedor'] or '').strip()
    return linhas


def ultimas_compras(clientes) -> dict[int, date]:
    """Data do último pedido agro (qualquer época) de cada cliente: ativo × ex-cliente × nunca comprou."""
    cods = base._inteiros(clientes)
    if not cods:
        return {}
    linhas = base._rows(f"""
        SELECT P.PEDCLI c, MAX(CAST(P.PEDDATA AS DATE)) u
        FROM PEDIDO P JOIN ITEMPEDIDO I ON I.IPEDPED = P.PEDNUM JOIN ESTOQUE E ON E.ESTQCOD = I.IPEDESTQ
        WHERE P.PEDSIT = 0 AND E.ESTQGALM IN ({_AGRO}) AND P.PEDCLI IN ({','.join(str(c) for c in cods)})
        GROUP BY P.PEDCLI
    """)
    return {int(l['c']): l['u'] for l in linhas if l['u']}
