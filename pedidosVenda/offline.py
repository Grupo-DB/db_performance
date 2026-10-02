"""
Pacote para o vendedor trabalhar sem internet (02/10/2026).

O app baixa tudo de uma vez quando está online e guarda no aparelho: os
clientes da carteira (com endereços, últimas compras e o resumo do
financeiro), o catálogo de cada unidade com os preços combinados com esses
clientes, e os prazos usuais. O pedido feito offline é refeito no servidor na
sincronização (preço de tabela e financeiro conferidos de novo no envio),
então o pacote é só para montar o pedido — não decide nada.
"""
from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone

from . import carteira, erp, fluxo
from .models import FILIAL_CHOICES

FILIAIS = [f for f, _ in FILIAL_CHOICES]
LOTE_IN = 900  # o IN do SQL Server aguenta ~2.100 parâmetros literais; folga

_SQL_CLIENTES = """
    SELECT C.CLICOD cod, C.CLINOME nome, C.CLINOMEFANT fantasia, C.CLICNPJCPF documento,
           C.CLIIEPR inscricao_estadual, C.CLIENDERECO endereco, C.CLIENDERECONUM numero,
           C.CLIENDERECOCOMP complemento, C.CLIBAIRRO bairro, C.CLICEP cep,
           {cidade} cidade, C.CLITELEFONE telefone, C.CLICELULAR celular, C.CLIEMAIL email,
           C.CLIREP repcod, R.REPNOME vendedor_carteira, C.CLIPGTOPRAZOST prazo_padrao,
           C.CLICOBTIPO cobranca_tipo, C.CLIBLOQVENDA bloqueado_venda, C.CLIBLOQTOTAL bloqueado_total
    FROM CLIENTE C
    LEFT JOIN REPRESENTANTE R ON R.REPCOD = C.CLIREP
    WHERE C.CLICOD IN ({cods})
"""

_SQL_ENDERECOS = """
    SELECT E.ECLICLI cliente, E.ECLICOD cod, E.ECLINOME nome, E.ECLIENDERECO endereco, E.ECLIENDERECONUM numero,
           E.ECLIENDERECOCOMP complemento, E.ECLIBAIRRO bairro, E.ECLICEP cep, {cidade} cidade,
           E.ECLICONTATO contato, E.ECLITELEFONE telefone, E.ECLIREFERENCIA referencia
    FROM ENDERECOCLIENTE E
    WHERE E.ECLICLI IN ({cods}) AND ISNULL(E.ECLIBLOQ, 'N') <> 'S'
"""

_SQL_COMPRAS = """
    WITH X AS (
        SELECT P.PEDCLI cliente, P.PEDNUM pedido, P.PEDDATA data, P.PEDFIL filial, P.PEDPGTOPRAZOST prazo,
               I.IPEDESTQ produto_cod, E.ESTQNOME descricao, ESP.ESPSIGLA unidade,
               I.IPEDQUANT quantidade, I.IPEDUNIT preco_unitario,
               ROW_NUMBER() OVER (PARTITION BY P.PEDCLI ORDER BY P.PEDDATA DESC, P.PEDNUM DESC) rn
        FROM PEDIDO P
        JOIN ITEMPEDIDO I ON I.IPEDPED = P.PEDNUM
        JOIN ESTOQUE E ON E.ESTQCOD = I.IPEDESTQ
        JOIN ESPECIE ESP ON ESP.ESPCOD = E.ESTQESP
        WHERE P.PEDCLI IN ({cods}) AND P.PEDSIT <> 2 AND P.PEDDATA >= :desde
    )
    SELECT * FROM X WHERE rn <= 15
"""

# Financeiro de todos os clientes numa consulta: o mesmo critério de erp.situacao_financeira.
_SQL_FINANCEIRO = """
    SELECT CR.CRCODREF cliente, COUNT(*) qtd_aberto, SUM(CR.CRTOTAL - CR.CRTOTALREC) aberto,
           SUM(CASE WHEN CR.CRVENC < CAST(GETDATE() AS DATE) THEN CR.CRTOTAL - CR.CRTOTALREC ELSE 0 END) vencido,
           SUM(CASE WHEN CR.CRVENC < CAST(GETDATE() AS DATE) THEN 1 ELSE 0 END) qtd_vencido,
           MAX(CASE WHEN CR.CRVENC < CAST(GETDATE() AS DATE) THEN DATEDIFF(day, CR.CRVENC, GETDATE()) ELSE 0 END) maior_atraso,
           MAX(CASE WHEN CR.CRNEGATIVADO = 'S' THEN 1 ELSE 0 END) negativado,
           MAX(CASE WHEN CR.CRPROTDATA IS NOT NULL THEN 1 ELSE 0 END) protestado
    FROM CONTARECEBER CR
    WHERE CR.CRTIPO = 0 AND CR.CRCODREF IN ({cods}) AND CR.CRTOTAL - CR.CRTOTALREC > 0.01
    GROUP BY CR.CRCODREF
"""


def _lotes(cods):
    cods = erp._inteiros(cods)
    for i in range(0, len(cods), LOTE_IN):
        yield ','.join(map(str, cods[i:i + LOTE_IN]))


def _texto(valor) -> str:
    return str(valor or '').replace('\x00', '').strip()


def _fone(valor) -> str:
    v = _texto(valor)
    return v if sum(ch.isdigit() for ch in v) >= 8 else ''


def clientes_da_carteira(repcods: list[int]) -> list[int]:
    """Quem comprou com o vendedor em 13 meses + quem está no cadastro dele (CLIREP)."""
    reps = erp._inteiros(repcods) or [-1]
    lista = ','.join(map(str, reps))
    cods = {r['cod'] for r in erp._rows(f"""
        SELECT DISTINCT NF.NFCLI cod FROM NOTAFISCAL NF
        WHERE NF.NFSIT = 1 AND NF.NFREP IN ({lista}) AND NF.NFDATA >= :desde
        UNION
        SELECT C.CLICOD FROM CLIENTE C WHERE C.CLIREP IN ({lista}) AND ISNULL(C.CLIBLOQTOTAL, 'N') <> 'S'
    """, desde=date.today() - timedelta(days=carteira.JANELA_DIAS))}
    return sorted(cods)


def pacote(repcods: list[int]) -> dict:
    cods = clientes_da_carteira(repcods)
    clientes: dict[int, dict] = {}
    enderecos = defaultdict(list)
    compras = defaultdict(list)
    financeiro: dict[int, dict] = {}
    cidade = erp._CIDADE_UF
    for lote in _lotes(cods):
        for c in erp._limpar(erp._rows(_SQL_CLIENTES.format(cods=lote, cidade=cidade.format(col='C.CLICIDADE')))):
            c['telefone'], c['celular'] = _fone(c['telefone']), _fone(c['celular'])
            c['bloqueado'] = c.pop('bloqueado_venda') == 'S' or c.pop('bloqueado_total') == 'S'
            c['da_carteira'] = c['repcod'] in repcods
            clientes[c['cod']] = c
        for e in erp._limpar(erp._rows(_SQL_ENDERECOS.format(cods=lote, cidade=cidade.format(col='E.ECLICIDADE')))):
            enderecos[e.pop('cliente')].append(e)
        for p in erp._limpar(erp._rows(_SQL_COMPRAS.format(cods=lote), desde=date.today() - timedelta(days=400))):
            p.pop('rn', None)
            compras[p.pop('cliente')].append(p)
        for f in erp._rows(_SQL_FINANCEIRO.format(cods=lote)):
            financeiro[f['cliente']] = f

    tolerancia = fluxo.TOLERANCIA_ATRASO_DIAS
    for cod, c in clientes.items():
        c['enderecos'] = sorted(enderecos.get(cod, []), key=lambda e: e['cod'])
        c['ultimas_compras'] = sorted(compras.get(cod, []), key=lambda p: (p['data'] or '', p['pedido']), reverse=True)
        f = financeiro.get(cod) or {}
        fin = {
            'bloqueado': c['bloqueado'],
            'aberto': round(float(f.get('aberto') or 0), 2),
            'vencido': round(float(f.get('vencido') or 0), 2),
            'qtd_aberto': int(f.get('qtd_aberto') or 0),
            'qtd_vencido': int(f.get('qtd_vencido') or 0),
            'maior_atraso': int(f.get('maior_atraso') or 0),
            'negativado': bool(f.get('negativado')),
            'protestado': bool(f.get('protestado')),
            'titulos_vencidos': [],
            'proximos': [],
            'tolerancia_dias': tolerancia,
        }
        fin['a_vencer'] = round(fin['aberto'] - fin['vencido'], 2)
        fin['pendencia'] = fluxo.texto_pendencia(fin)
        c['financeiro'] = fin

    # Catálogo geral de cada unidade + preço combinado de cada cliente (PRCCLI).
    catalogos, precos_cliente = {}, defaultdict(dict)
    for fil in FILIAIS:
        try:
            catalogos[fil] = erp.catalogo(fil)
        except Exception:
            catalogos[fil] = []
        try:
            saldos = erp.estoque(fil)
        except Exception:
            saldos = {}
        for p in catalogos[fil]:
            p['estoque'] = saldos.get(p['cod'], {'fisico': 0.0, 'comprometido': 0.0, 'disponivel': 0.0, 'origem': 'REVENDA'})
        for lote in _lotes(cods):
            for p in erp._precos(fil, [int(x) for x in lote.split(',')]):
                precos_cliente[str(p['cliente'])].setdefault(str(fil), {})[str(p['cod'])] = {
                    'preco': p['preco'], 'descricao': p['descricao'], 'unidade': p['unidade'],
                    'grupo_cod': p.get('grupo_cod'), 'grupo': p.get('grupo'), 'referencia': p.get('referencia'),
                    'data_preco': p.get('data_preco'),
                }

    return {
        'gerado_em': timezone.localtime().isoformat(),
        'clientes': sorted(clientes.values(), key=lambda c: c['nome'] or ''),
        'catalogos': {str(f): l for f, l in catalogos.items()},
        'precos_cliente': precos_cliente,
        'prazos': erp.prazos_usuais(),
    }
