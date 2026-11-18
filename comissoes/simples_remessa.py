"""Notas de simples remessa (relatório em Comissões › Simples Remessa).

Pedido de 18/11/2026: um item próprio no menu de Vendas e Comissões só com a
natureza de simples remessa, com relatório em PDF e Excel.

Regras levantadas no SGA em 18/11/2026:

- **Simples remessa** = entrega da mercadoria de uma venda já faturada antes por
  "SIMPLES FATURAMENTO" (venda para entrega futura). Natureza 3 "SIMPLES
  REMESSA", CFOP 5.116 (6.116 fora do RS). Em 2026, cerca de 500 a 1.900 notas
  por mês, uma linha de item por nota.
- Entram as naturezas cujo nome começa com "SIMPLES REMESSA": 3, 169 "- ACERTO"
  e 156 "- ALMOXARIFADO" (as duas últimas são raras). "DEVOL. DE SIMP. REMESSA"
  é entrada e não entra.
- A natureza não tem operação financeira: a receita é a do simples faturamento.
  Por isso este relatório não passa pelo filtro de views.calculos_comissoes e o
  valor aqui é o da mercadoria entregue, não faturamento novo.
- Toda remessa traz a nota do faturamento em NFNFREF / NFNFREFDATA (100% das
  notas de 2026). INFINFREF aponta para o próprio item e não serve.
- Só nota válida (NFSIT = 1).
- Cidade = endereço de entrega (NFECLI) quando houver; senão a do cliente.
"""
import datetime as dt

import pandas as pd
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .views import engine

DIAS_MAX = 731

_SQL = """
    SELECT
        NF.NFCOD, NF.NFNUM NOTA, CAST(NF.NFDATA AS DATE) DATA,
        CASE WHEN NF.NFFIL = 0 THEN EMPSIGLA ELSE FILSIGLA END EMPRESA_FILIAL,
        NF.NFNFREF NOTA_FATURAMENTO, CAST(NF.NFNFREFDATA AS DATE) DATA_FATURAMENTO,
        INF.INFPED PEDIDO,
        CLICOD CLIENTE_CODIGO, CLINOME CLIENTE,
        COALESCE(
            (SELECT CIDNOME + '-' + ESTUF FROM ENDERECOCLIENTE
                JOIN CIDADE ON CIDCOD = ECLICIDADE
                JOIN ESTADO ON ESTCOD = CIDEST
                WHERE NF.NFECLI > 0 AND ECLICOD = NF.NFECLI AND ECLICLI = NF.NFCLI),
            (SELECT CIDNOME + '-' + ESTUF FROM CIDADE
                JOIN ESTADO ON ESTCOD = CIDEST
                WHERE CIDCOD = CLICIDADE)) CIDADE,
        SEGCNOME SEGMENTO_CLIENTE,
        R.REPNOME REPRESENTANTE, M.REPNOME REPRESENTANTE_MASTER,
        LEFT(CAST(INF.INFCFOP AS VARCHAR(10)), 4) CFOP, NOPNOME NATUREZA,
        ESTQCOD PRODUTO_CODIGO, ESTQNOME PRODUTO, ESPSIGLA UNIDADE,
        CASE WHEN ESTQGRP = 0 THEN GALMNOME ELSE GRPNOME END GRUPO,
        CASE WHEN ESTQGALM IN (1974, 1587, 1828) THEN 'AGRONEGOCIO' ELSE 'CONSTRUCAO CIVIL' END SEGMENTO_PRODUTO,
        INF.INFQUANT QUANTIDADE,
        (INF.INFQUANT * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000.0 TONELADAS,
        INF.INFTOTAL VALOR
    FROM NOTAFISCAL NF
    JOIN ITEMNOTAFISCAL INF ON INF.INFNFCOD = NF.NFCOD
    JOIN NATUREZAOPERACAO ON NOPCOD = INF.INFNOP
    JOIN CLIENTE ON CLICOD = NF.NFCLI
    LEFT JOIN SEGMENTOCLIENTE ON SEGCREF = 1 AND SEGCCOD = CLISEGC
    JOIN ESTOQUE ON ESTQCOD = INF.INFESTQ
    JOIN ESPECIE ON ESPCOD = ESTQESP
    JOIN GRUPOALMOXARIFADO ON GALMCOD = ESTQGALM
    LEFT JOIN GRUPOPRODUTO ON GRPCOD = ESTQGRP
    JOIN EMPRESA ON EMPCOD = NF.NFEMP
    LEFT JOIN FILIAL ON FILCOD = NF.NFFIL
    LEFT JOIN REPRESENTANTE R ON R.REPCOD = NF.NFREP
    LEFT JOIN REPRESENTANTE M ON M.REPCOD = R.REPREPREF
    WHERE NF.NFSIT = 1
      AND CAST(NF.NFDATA AS DATE) BETWEEN :inicio AND :fim
      AND NOPNOME LIKE 'SIMPLES REMESSA%'
    ORDER BY NF.NFDATA, NF.NFNUM
"""

_TEXTOS = ('EMPRESA_FILIAL', 'CLIENTE', 'CIDADE', 'SEGMENTO_CLIENTE', 'REPRESENTANTE', 'REPRESENTANTE_MASTER',
           'NATUREZA', 'PRODUTO', 'UNIDADE', 'GRUPO', 'SEGMENTO_PRODUTO')


def periodo(inicio_bruto, fim_bruto, hoje: dt.date | None = None) -> tuple[str, str]:
    """Padrão: do dia 1º do mês corrente até hoje. ValueError se inválido."""
    hoje = hoje or dt.date.today()
    fim = dt.date.fromisoformat(str(fim_bruto)[:10]) if fim_bruto else hoje
    inicio = dt.date.fromisoformat(str(inicio_bruto)[:10]) if inicio_bruto else fim.replace(day=1)
    if inicio > fim:
        raise ValueError('A data inicial é depois da final.')
    if (fim - inicio).days > DIAS_MAX:
        raise ValueError('O período pode ter no máximo 2 anos.')
    return inicio.isoformat(), fim.isoformat()


def ler_itens(inicio: str, fim: str) -> pd.DataFrame:
    from sqlalchemy import text
    df = pd.read_sql(text(_SQL), engine, params={'inicio': inicio, 'fim': fim})
    return preparar(df)


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ('QUANTIDADE', 'TONELADAS', 'VALOR'):
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    for col in _TEXTOS:
        df[col] = df[col].fillna('').astype(str).str.strip()
    df['CFOP'] = df['CFOP'].fillna('').astype(str).str.strip()
    df['DATA'] = pd.to_datetime(df['DATA']).dt.strftime('%Y-%m-%d')
    df['DATA_FATURAMENTO'] = pd.to_datetime(df['DATA_FATURAMENTO'], errors='coerce').dt.strftime('%Y-%m-%d')
    return df


def _int(v) -> int | None:
    return None if v is None or pd.isna(v) or int(v) <= 0 else int(v)


def _linha(r) -> dict:
    cfop = r.CFOP
    return {
        'nf': int(r.NFCOD), 'nota': int(r.NOTA), 'data': r.DATA, 'empresa': r.EMPRESA_FILIAL,
        'nota_faturamento': _int(r.NOTA_FATURAMENTO),
        'data_faturamento': r.DATA_FATURAMENTO if isinstance(r.DATA_FATURAMENTO, str) else None,
        'pedido': _int(r.PEDIDO),
        'cliente_codigo': int(r.CLIENTE_CODIGO), 'cliente': r.CLIENTE, 'cidade': r.CIDADE,
        'segmento_cliente': r.SEGMENTO_CLIENTE,
        'representante': r.REPRESENTANTE, 'representante_master': r.REPRESENTANTE_MASTER,
        'cfop': f'{cfop[:1]}.{cfop[1:]}' if len(cfop) == 4 else cfop, 'natureza': r.NATUREZA,
        'produto_codigo': int(r.PRODUTO_CODIGO), 'produto': r.PRODUTO, 'unidade': r.UNIDADE, 'grupo': r.GRUPO,
        'segmento_produto': r.SEGMENTO_PRODUTO,
        'quantidade': round(float(r.QUANTIDADE), 3), 'toneladas': round(float(r.TONELADAS), 3),
        'valor': round(float(r.VALOR), 2),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def simples_remessa(request):
    """
    Itens de notas de simples remessa no período (uma linha por item de nota).
    ?inicio=AAAA-MM-DD (padrão: dia 1º do mês) &fim=AAAA-MM-DD (padrão: hoje); máx. 2 anos.
    Filtros, totais e agrupamentos são feitos na tela, sobre estas linhas.
    """
    try:
        inicio, fim = periodo(request.GET.get('inicio'), request.GET.get('fim'))
    except ValueError as exc:
        msg = str(exc)
        return Response({'erro': msg if 'período' in msg or 'depois' in msg else 'Data inválida (use AAAA-MM-DD).'},
                        status=400)
    try:
        df = ler_itens(inicio, fim)
    except Exception as exc:
        return Response({'erro': f'Falha na consulta ao SGA: {exc}'}, status=502)
    return Response({
        'inicio': inicio,
        'fim': fim,
        'itens': [_linha(r) for r in df.itertuples()],
        'gerado_em': dt.datetime.now().isoformat(timespec='seconds'),
    })
