"""
Leituras do ERP (SQL Server, usuário só-leitura) usadas pelo pedido de venda.

Onde mora cada coisa (levantado em 01/10/2026):

- **Tabela de preço = PRECOCLIENTE.** `PRCCLI = 0` é o preço geral; `PRCCLI > 0`
  é o preço combinado com aquele cliente e vence o geral. `PRCFIL` é a unidade de
  expedição — o mesmo produto tem preço diferente por unidade. Validade
  `1899-12-30` é o "vazio" do ERP (sem vencimento). `ESTQPRECO` e
  `QUANTESTOQUE.QESTQPRECO` NÃO são preço de venda (custo ou zero).
- **Cliente**: CLIENTE (+ CIDADE/ESTADO); endereços de entrega em ENDERECOCLIENTE.
  `CLIDATAULTNOTA` não é mantido pelo ERP — a última compra sai de PEDIDO.
- **Vendedor**: REPRESENTANTE; `CLIREP` é o vendedor da carteira do cliente.
"""
import os
import re
from datetime import date, datetime, timedelta

from django.core.cache import cache
from sqlalchemy import create_engine, text

# Mesma string das comissões. De fora da rede (máquina do dev) exportar
# ERP_ODBC_URL com o IP externo 45.6.118.50,65530.
ERP_ODBC_URL = os.environ.get(
    'ERP_ODBC_URL',
    'mssql+pyodbc://DBCONSULTA:%21%40%23123qweQWE@172.10.27.51:1433/DB'
    '?driver=ODBC+Driver+17+for+SQL+Server',
)
EMPRESA = 1
DATA_VAZIA = date(1900, 1, 1)
CACHE_PRODUTOS_SEG = 600

_engine = None


def engine():
    """Engine preguiçosa: o import do módulo não pode depender do ERP no ar."""
    global _engine
    if _engine is None:
        _engine = create_engine(ERP_ODBC_URL, pool_pre_ping=True)
    return _engine


def _rows(sql: str, **params) -> list[dict]:
    with engine().connect() as conn:
        res = conn.execute(text(sql), params)
        return [dict(r._mapping) for r in res]


def _limpo(valor):
    if isinstance(valor, str):
        valor = valor.strip()
        # Máscara de telefone vazia que o ERP grava: "(   )       -".
        return '' if valor and not re.search(r'[0-9A-Za-z]', valor) else valor
    if isinstance(valor, datetime):
        return None if valor.date() <= DATA_VAZIA else valor.date().isoformat()
    return valor


def _limpar(linhas: list[dict]) -> list[dict]:
    return [{k: _limpo(v) for k, v in linha.items()} for linha in linhas]


def _inteiros(valores) -> list[int]:
    saida = []
    for v in valores or []:
        try:
            saida.append(int(v))
        except (TypeError, ValueError):
            continue
    return saida


# ── Clientes ────────────────────────────────────────────────────────────────

_CIDADE_UF = "(SELECT CI.CIDNOME + '-' + ES.ESTUF FROM CIDADE CI JOIN ESTADO ES ON ES.ESTCOD = CI.CIDEST WHERE CI.CIDCOD = {col})"

# CNPJ/CPF é gravado com pontuação ("15.378.298/0001-45"): a busca por dígitos
# compara contra a coluna sem ela.
_DOC_SEM_PONTUACAO = "REPLACE(REPLACE(REPLACE(C.CLICNPJCPF, '.', ''), '/', ''), '-', '')"


def buscar_clientes(busca: str, repcods: list[int], limite: int = 30, campo: str = '') -> list[dict]:
    """
    `campo` diz onde procurar: 'nome' (razão social e fantasia), 'documento'
    (CNPJ/CPF pelo começo dos dígitos) ou 'codigo' (CLICOD exato). Sem campo,
    procura em tudo — mas aí "105" casa com o código 105 E com todo CNPJ que
    começa com 105, que é o que confundia o vendedor.
    """
    busca = (busca or '').strip()
    digitos = re.sub(r'\D', '', busca)
    params = {'limite': max(1, min(int(limite), 50))}
    condicoes = []

    if campo == 'codigo':
        if not digitos or len(digitos) > 9:
            return []
        condicoes.append('C.CLICOD = :cod')
        params['cod'] = int(digitos)
    elif campo == 'documento':
        if len(digitos) < 3:
            return []
        condicoes.append(f'{_DOC_SEM_PONTUACAO} LIKE :doc')
        params['doc'] = f'{digitos}%'
    else:
        if len(busca) < 2:
            return []
        condicoes += ['C.CLINOME LIKE :nome', 'C.CLINOMEFANT LIKE :nome']
        params['nome'] = f'%{busca}%'
        if campo != 'nome':
            if len(digitos) >= 3:
                condicoes.append(f'{_DOC_SEM_PONTUACAO} LIKE :doc')
                params['doc'] = f'{digitos}%'
            if digitos and digitos == busca and len(digitos) <= 7:
                condicoes.append('C.CLICOD = :cod')
                params['cod'] = int(digitos)

    reps = _inteiros(repcods)
    carteira = f"CASE WHEN C.CLIREP IN ({','.join(str(r) for r in reps)}) THEN 1 ELSE 0 END" if reps else '0'

    sql = f"""
        SELECT TOP (:limite)
            C.CLICOD cod, C.CLINOME nome, C.CLINOMEFANT fantasia, C.CLICNPJCPF documento,
            {_CIDADE_UF.format(col='C.CLICIDADE')} cidade,
            C.CLIREP repcod, R.REPNOME vendedor_carteira,
            C.CLIBLOQVENDA bloqueado_venda, C.CLIBLOQTOTAL bloqueado_total,
            {carteira} da_carteira
        FROM CLIENTE C
        LEFT JOIN REPRESENTANTE R ON R.REPCOD = C.CLIREP
        WHERE ({' OR '.join(condicoes)})
        ORDER BY da_carteira DESC, C.CLINOME
    """
    linhas = _limpar(_rows(sql, **params))
    for l in linhas:
        l['da_carteira'] = bool(l['da_carteira'])
        l['bloqueado'] = l.pop('bloqueado_venda') == 'S' or l.pop('bloqueado_total') == 'S'
    return linhas


def detalhar_cliente(cod: int, repcods: list[int]) -> dict | None:
    dados = _limpar(_rows(f"""
        SELECT C.CLICOD cod, C.CLINOME nome, C.CLINOMEFANT fantasia, C.CLICNPJCPF documento,
               C.CLIIEPR inscricao_estadual,
               C.CLIENDERECO endereco, C.CLIENDERECONUM numero, C.CLIENDERECOCOMP complemento,
               C.CLIBAIRRO bairro, C.CLICEP cep, {_CIDADE_UF.format(col='C.CLICIDADE')} cidade,
               C.CLITELEFONE telefone, C.CLICELULAR celular, C.CLIEMAIL email,
               C.CLIREP repcod, R.REPNOME vendedor_carteira,
               C.CLIPGTOPRAZOST prazo_padrao, C.CLICOBTIPO cobranca_tipo,
               C.CLILIMCRED limite_credito, C.CLISALDO saldo,
               C.CLIBLOQVENDA bloqueado_venda, C.CLIBLOQTOTAL bloqueado_total
        FROM CLIENTE C
        LEFT JOIN REPRESENTANTE R ON R.REPCOD = C.CLIREP
        WHERE C.CLICOD = :cod
    """, cod=int(cod)))
    if not dados:
        return None
    cli = dados[0]
    # CLICELULAR costuma vir com bytes nulos (13 × \x00): parece preenchido e sai em branco.
    for campo in ('celular', 'telefone'):
        valor = str(cli.get(campo) or '').replace('\x00', '').strip()
        cli[campo] = valor if sum(ch.isdigit() for ch in valor) >= 8 else ''
    cli['bloqueado'] = cli.pop('bloqueado_venda') == 'S' or cli.pop('bloqueado_total') == 'S'
    cli['da_carteira'] = cli['repcod'] in _inteiros(repcods)

    cli['enderecos'] = _limpar(_rows(f"""
        SELECT E.ECLICOD cod, E.ECLINOME nome, E.ECLIENDERECO endereco, E.ECLIENDERECONUM numero,
               E.ECLIENDERECOCOMP complemento, E.ECLIBAIRRO bairro, E.ECLICEP cep,
               {_CIDADE_UF.format(col='E.ECLICIDADE')} cidade, E.ECLICONTATO contato,
               E.ECLITELEFONE telefone, E.ECLIREFERENCIA referencia
        FROM ENDERECOCLIENTE E
        WHERE E.ECLICLI = :cod AND ISNULL(E.ECLIBLOQ, 'N') <> 'S'
        ORDER BY E.ECLICOD
    """, cod=int(cod)))

    # Últimas compras: base do "repetir pedido" — o vendedor de campo quase sempre
    # vende o mesmo mix ao mesmo cliente.
    cli['ultimas_compras'] = _limpar(_rows("""
        SELECT TOP 40 P.PEDNUM pedido, P.PEDDATA data, P.PEDFIL filial, P.PEDPGTOPRAZOST prazo,
               I.IPEDESTQ produto_cod, E.ESTQNOME descricao, ESP.ESPSIGLA unidade,
               I.IPEDQUANT quantidade, I.IPEDUNIT preco_unitario
        FROM PEDIDO P
        JOIN ITEMPEDIDO I ON I.IPEDPED = P.PEDNUM
        JOIN ESTOQUE E ON E.ESTQCOD = I.IPEDESTQ
        JOIN ESPECIE ESP ON ESP.ESPCOD = E.ESTQESP
        WHERE P.PEDCLI = :cod AND P.PEDSIT <> 2
        ORDER BY P.PEDDATA DESC, P.PEDNUM DESC
    """, cod=int(cod)))
    return cli


# ── Financeiro do cliente ──────────────────────────────────────────────────
# Títulos a receber em aberto (CONTARECEBER, levantado 02/10/2026): CRTIPO 0 =
# cliente, CRCODREF = CLICOD, aberto = CRTOTAL − CRTOTALREC. O limite de crédito
# do ERP (CLILIMCRED) e o CLISALDO estão zerados em todos os clientes — não usar.
CACHE_FINANCEIRO_SEG = 300


def situacao_financeira(cod: int) -> dict:
    chave = f'pedidosVenda:financeiro:{int(cod)}'
    dados = cache.get(chave)
    if dados is not None:
        return dados
    titulos = _limpar(_rows("""
        SELECT CR.CRNUM titulo, CR.CRNUMREF documento, CR.CRPARNUM parcela, CR.CRPARTOT parcelas,
               CR.CRDATA emissao, CR.CRVENC vencimento, CR.CRTOTAL - CR.CRTOTALREC aberto,
               CR.CRNEGATIVADO negativado, CR.CRPROTDATA protesto
        FROM CONTARECEBER CR
        WHERE CR.CRTIPO = 0 AND CR.CRCODREF = :cod AND CR.CRTOTAL - CR.CRTOTALREC > 0.01
        ORDER BY CR.CRVENC
    """, cod=int(cod)))
    hoje = date.today()
    aberto = vencido = 0.0
    maior_atraso = 0
    for t in titulos:
        t['aberto'] = round(float(t['aberto'] or 0), 2)
        venc = date.fromisoformat(t['vencimento']) if t['vencimento'] else None
        t['dias_atraso'] = max((hoje - venc).days, 0) if venc else 0
        t['negativado'] = t['negativado'] == 'S'
        t['protestado'] = bool(t.pop('protesto'))
        aberto += t['aberto']
        if t['dias_atraso'] > 0:
            vencido += t['aberto']
            maior_atraso = max(maior_atraso, t['dias_atraso'])
    vencidos = [t for t in titulos if t['dias_atraso'] > 0]
    bloq = _rows("SELECT CLIBLOQVENDA v, CLIBLOQTOTAL t FROM CLIENTE WHERE CLICOD = :cod", cod=int(cod))
    dados = {
        'bloqueado': bool(bloq) and ('S' in (bloq[0]['v'], bloq[0]['t'])),
        'aberto': round(aberto, 2),
        'vencido': round(vencido, 2),
        'a_vencer': round(aberto - vencido, 2),
        'qtd_aberto': len(titulos),
        'qtd_vencido': len(vencidos),
        'maior_atraso': maior_atraso,
        'negativado': any(t['negativado'] for t in titulos),
        'protestado': any(t['protestado'] for t in titulos),
        # Os vencidos mais antigos primeiro; o resto só conta.
        'titulos_vencidos': vencidos[:15],
        'proximos': [t for t in titulos if t['dias_atraso'] == 0][:5],
    }
    cache.set(chave, dados, CACHE_FINANCEIRO_SEG)
    return dados


# ── Estoque ─────────────────────────────────────────────────────────────────
# QUANTESTOQUE (levantado 02/10/2026): saldo físico por produto e unidade na
# linha QESTQREF = 0 — produto fabricado fica no QESTQTIPO 1, revenda no 0, nunca
# nos dois. A produção não é apontada em dia: vários fabricados ficam NEGATIVOS
# (argamassa multiuso −2.599 sc vendendo 35 mil/mês), então o número é só
# informação para o vendedor, nunca trava a venda.
CACHE_ESTOQUE_SEG = 120


def estoque(filial: int) -> dict[int, dict]:
    chave = f'pedidosVenda:estoque:{int(filial)}'
    dados = cache.get(chave)
    if dados is not None:
        return dados
    linhas = _rows("""
        SELECT Q.QESTQESTQ cod, SUM(Q.QESTQESTOQUE) saldo,
               SUM(CASE WHEN Q.QESTQTIPO = 1 AND Q.QESTQESTOQUE <> 0 THEN 1 ELSE 0 END)
                 + MAX(CASE WHEN E.ESTQMARCA = 'DB' THEN 1 ELSE 0 END) fabricado
        FROM QUANTESTOQUE Q
        JOIN ESTOQUE E ON E.ESTQCOD = Q.QESTQESTQ
        WHERE Q.QESTQEMP = :emp AND Q.QESTQFIL = :fil AND Q.QESTQTIPO IN (0, 1) AND Q.QESTQREF = 0
        GROUP BY Q.QESTQESTQ
    """, emp=EMPRESA, fil=int(filial))
    fisico = {r['cod']: float(r['saldo'] or 0) for r in linhas}
    # Fabricado (marca DB, ou saldo no tipo 1): a fábrica produz contra pedido — o
    # "disponível" dele não quer dizer nada. Só revenda tem disponível de verdade.
    fabricados = {r['cod'] for r in linhas if r['fabricado']}
    # Comprometido: saldo dos pedidos ativos da unidade (o que ainda vai sair).
    comprometido = {r['cod']: float(r['saldo'] or 0) for r in _rows("""
        SELECT I.IPEDESTQ cod, SUM(I.IPEDQUANT - I.IPEDQUANTDESP - ISNULL(I.IPEDQUANTCANC, 0)) saldo
        FROM ITEMPEDIDO I
        JOIN PEDIDO P ON P.PEDNUM = I.IPEDPED
        WHERE P.PEDSIT = 0 AND P.PEDEMP = :emp AND P.PEDFIL = :fil AND P.PEDDATA >= :desde
          AND I.IPEDQUANT - I.IPEDQUANTDESP - ISNULL(I.IPEDQUANTCANC, 0) > 0.001
        GROUP BY I.IPEDESTQ
    """, emp=EMPRESA, fil=int(filial), desde=date.today() - timedelta(days=120))}
    dados = {}
    for cod in set(fisico) | set(comprometido):
        f, c = round(fisico.get(cod, 0.0), 3), round(comprometido.get(cod, 0.0), 3)
        dados[cod] = {
            'fisico': f, 'comprometido': c, 'disponivel': round(f - c, 3),
            'origem': 'FABRICADO' if cod in fabricados else 'REVENDA',
        }
    cache.set(chave, dados, CACHE_ESTOQUE_SEG)
    return dados


# ── Produtos e preços ───────────────────────────────────────────────────────

# Preço vigente por produto: o registro mais recente que não está cancelado,
# bloqueado nem vencido. ROW_NUMBER escolhe um por produto (e por cliente, quando
# há preço específico).
_SQL_PRECOS = """
    WITH P AS (
        SELECT PRC.PRCESTQ, PRC.PRCCLI, PRC.PRCVALOR, PRC.PRCDATA,
               ROW_NUMBER() OVER (PARTITION BY PRC.PRCESTQ, PRC.PRCCLI ORDER BY PRC.PRCDATA DESC, PRC.PRCCOD DESC) rn
        FROM PRECOCLIENTE PRC
        WHERE PRC.PRCEMP = :emp AND PRC.PRCFIL = :fil AND PRC.PRCCLI IN ({clientes})
          AND ISNULL(PRC.PRCCANCELADO, 'N') <> 'S' AND ISNULL(PRC.PRCBLOQ, 'N') <> 'S'
          AND (PRC.PRCVALID IS NULL OR PRC.PRCVALID < '1900-01-02' OR PRC.PRCVALID >= CAST(GETDATE() AS DATE))
          AND PRC.PRCVALOR > 0
          {filtro_produtos}
    )
    SELECT P.PRCESTQ cod, P.PRCCLI cliente, P.PRCVALOR preco, P.PRCDATA data_preco,
           E.ESTQNOME descricao, E.ESTQREF referencia, ESP.ESPSIGLA unidade,
           G.GALMCOD grupo_cod, G.GALMNOME grupo
    FROM P
    JOIN ESTOQUE E ON E.ESTQCOD = P.PRCESTQ
    JOIN ESPECIE ESP ON ESP.ESPCOD = E.ESTQESP
    JOIN GRUPOALMOXARIFADO G ON G.GALMCOD = E.ESTQGALM
    WHERE P.rn = 1 AND ISNULL(E.ESTQBLOQ, 'N') <> 'S'
"""


def _precos(filial: int, clientes: list[int], produtos: list[int] | None = None) -> list[dict]:
    filtro = ''
    if produtos is not None:
        prods = _inteiros(produtos) or [-1]
        filtro = f"AND PRC.PRCESTQ IN ({','.join(str(p) for p in prods)})"
    sql = _SQL_PRECOS.format(clientes=','.join(str(c) for c in clientes), filtro_produtos=filtro)
    return _limpar(_rows(sql, emp=EMPRESA, fil=int(filial)))


def catalogo(filial: int, cliente: int | None = None) -> list[dict]:
    """
    Produtos com preço na unidade, já com o preço específico do cliente quando houver.

    O preço geral muda pouco e é igual para todos: fica 10 min em cache por
    unidade. O específico do cliente é consulta pequena e vai sempre ao ERP.
    """
    chave = f'pedidosVenda:catalogo:{int(filial)}'
    geral = cache.get(chave)
    if geral is None:
        geral = _precos(filial, [0])
        cache.set(chave, geral, CACHE_PRODUTOS_SEG)

    por_cod = {p['cod']: {**p, 'preco_tabela': p['preco'], 'preco_cliente': False} for p in geral}
    if cliente:
        for p in _precos(filial, [int(cliente)]):
            base = por_cod.get(p['cod'], {**p})
            por_cod[p['cod']] = {**base, 'preco_tabela': p['preco'], 'preco_cliente': True}
    itens = list(por_cod.values())
    for i in itens:
        i.pop('preco', None)
        i.pop('cliente', None)
    itens.sort(key=lambda i: (i.get('grupo') or '', i.get('descricao') or ''))
    return itens


def vendaveis(filiais: list[int]) -> list[dict]:
    """Todo produto com preço geral em alguma unidade — a lista do cadastro de fotos."""
    por_cod: dict[int, dict] = {}
    for fil in filiais:
        for p in catalogo(fil):
            atual = por_cod.setdefault(p['cod'], {
                'cod': p['cod'], 'descricao': p['descricao'], 'unidade': p['unidade'],
                'grupo': p['grupo'], 'filiais': [],
            })
            atual['filiais'].append(fil)
    return sorted(por_cod.values(), key=lambda p: (p['grupo'] or '', p['descricao'] or ''))


def precos_vigentes(filial: int, cliente: int | None, produtos: list[int]) -> dict[int, float]:
    """Preço de tabela de cada produto como o `catalogo`, para conferir o pedido no envio."""
    clientes = [0] + ([int(cliente)] if cliente else [])
    linhas = _precos(filial, clientes, produtos)
    precos: dict[int, float] = {}
    for l in sorted(linhas, key=lambda l: l['cliente'] != 0):  # específico por último → vence
        precos[l['cod']] = float(l['preco'])
    return precos


# ── Apoio ───────────────────────────────────────────────────────────────────

def prazos_usuais(limite: int = 24) -> list[str]:
    """Prazos de pagamento mais usados nos últimos 6 meses (sugestões do campo)."""
    chave = 'pedidosVenda:prazos'
    prazos = cache.get(chave)
    if prazos is None:
        linhas = _rows("""
            SELECT TOP (:limite) LTRIM(RTRIM(PEDPGTOPRAZOST)) prazo, COUNT(*) n
            FROM PEDIDO
            WHERE PEDDATA >= DATEADD(MONTH, -6, GETDATE()) AND PEDSIT <> 2
              AND LTRIM(RTRIM(ISNULL(PEDPGTOPRAZOST, ''))) <> ''
            GROUP BY LTRIM(RTRIM(PEDPGTOPRAZOST))
            ORDER BY n DESC
        """, limite=int(limite))
        prazos = [l['prazo'] for l in linhas]
        cache.set(chave, prazos, 3600)
    return prazos


def representantes() -> list[dict]:
    return _limpar(_rows("""
        SELECT REPCOD cod, REPNOME nome, ISNULL(REPINATIVO, 'N') inativo
        FROM REPRESENTANTE ORDER BY REPNOME
    """))


def pedido_erp(numero: int) -> dict | None:
    linhas = _limpar(_rows("""
        SELECT PEDNUM numero, PEDCLI cliente, PEDREP repcod, PEDDATA data, PEDSIT situacao, PEDTOTAL total
        FROM PEDIDO WHERE PEDNUM = :n
    """, n=int(numero)))
    return linhas[0] if linhas else None
