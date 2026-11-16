"""Faturamento de exportação (relatório + dash em Comissões › Exportação).

Pedido de 16/11/2026: total faturado para exportação de 01/01/2023 a 31/12/2025
(o período é livre; esse é o padrão da tela).

Regras levantadas no SGA em 16/11/2026:

- **Exportação direta** = item de nota com CFOP 7.xxx (7.101 produção própria,
  7.102 mercadoria de terceiros). No período padrão foram 932 notas, todas para o
  Uruguai (clientes com UF "EX"), em reais (NFMOE = 0, NFTOTALMOE zerado).
- **Exportação indireta** = remessa com fim específico de exportação (5.501,
  5.502, 6.501, 6.502), venda para trading/comercial exportadora. Pouca coisa
  (3 notas no período padrão), mas é faturamento para exportação; sai separada.
- Só nota válida (NFSIT = 1; 2 é cancelada) e só natureza com "operação
  financeira" e sem "não representa receita" — o mesmo filtro de
  views.calculos_comissoes. Isso tira a bonificação de exportação (7.949).
- Valor: VALOR_PRODUTO = INFTOTAL; VALOR_TOTAL = rateio do NFTOTAL da nota pelo
  peso do item (mesma conta do acompanhamento de vendas). Na exportação não há
  IPI/ST, então os dois praticamente coincidem.
- Devoluções de exportação: nenhuma no período padrão (ITEMNOTAFISCALENTRADA
  ligada aos itens 7.xxx). O relatório lista o que existir, mas não desconta.
"""
import datetime as dt

import pandas as pd
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .views import engine

INICIO_PADRAO = '2023-01-01'
FIM_PADRAO = '2025-12-31'
CFOPS_INDIRETA = ('5501', '5502', '6501', '6502')

_SQL = """
    SELECT
        NF.NFCOD, NF.NFNUM NOTA, CAST(NF.NFDATA AS DATE) DATA,
        CASE WHEN NF.NFFIL = 0 THEN EMPSIGLA ELSE FILSIGLA END EMPRESA_FILIAL,
        CLICOD CLIENTE_CODIGO, CLINOME CLIENTE, CLICNPJCPF CLIENTE_DOC,
        CIDNOME CIDADE, ESTUF UF,
        LEFT(CAST(INF.INFCFOP AS VARCHAR(10)), 4) CFOP, NOPNOME NATUREZA,
        ESTQCOD PRODUTO_CODIGO, ESTQNOME PRODUTO, ESPSIGLA UNIDADE,
        CASE WHEN ESTQGRP = 0 THEN GALMNOME ELSE GRPNOME END GRUPO,
        INF.INFQUANT QUANTIDADE,
        (INF.INFQUANT * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000.0 TONELADAS,
        INF.INFTOTAL VALOR_PRODUTO,
        (INF.INFTOTAL / NULLIF(NF.NFTOTPRO + NF.NFTOTSERV, 0)) * NF.NFTOTAL VALOR_TOTAL,
        COALESCE(R.REPNOME, '') REPRESENTANTE
    FROM NOTAFISCAL NF
    JOIN ITEMNOTAFISCAL INF ON INF.INFNFCOD = NF.NFCOD
    JOIN NATUREZAOPERACAO ON NOPCOD = INF.INFNOP
    JOIN CLIENTE ON CLICOD = NF.NFCLI
    LEFT JOIN CIDADE ON CIDCOD = CLICIDADE
    LEFT JOIN ESTADO ON ESTCOD = CIDEST
    JOIN ESTOQUE ON ESTQCOD = INF.INFESTQ
    JOIN ESPECIE ON ESPCOD = ESTQESP
    JOIN GRUPOALMOXARIFADO ON GALMCOD = ESTQGALM
    LEFT JOIN GRUPOPRODUTO ON GRPCOD = ESTQGRP
    JOIN EMPRESA ON EMPCOD = NF.NFEMP
    LEFT JOIN FILIAL ON FILCOD = NF.NFFIL
    LEFT JOIN REPRESENTANTE R ON R.REPCOD = NF.NFREP
    WHERE NF.NFSIT = 1
      AND CAST(NF.NFDATA AS DATE) BETWEEN :inicio AND :fim
      AND SUBSTRING(NOPFLAGNF, 1, 1) = 'S' AND SUBSTRING(NOPFLAGNF, 25, 1) = 'N'
      AND (CAST(INF.INFCFOP AS VARCHAR(10)) LIKE '7%%'
           OR LEFT(CAST(INF.INFCFOP AS VARCHAR(10)), 4) IN ({indiretas}))
    ORDER BY NF.NFDATA, NF.NFNUM
"""


def _data(bruto, padrao: str) -> str:
    if not bruto:
        return padrao
    return dt.date.fromisoformat(str(bruto)[:10]).isoformat()


def ler_itens(inicio: str, fim: str) -> pd.DataFrame:
    from sqlalchemy import text
    indiretas = ','.join(f"'{c}'" for c in CFOPS_INDIRETA)
    sql = text(_SQL.format(indiretas=indiretas).replace('%%', '%'))
    df = pd.read_sql(sql, engine, params={'inicio': inicio, 'fim': fim})
    return preparar(df)


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ('QUANTIDADE', 'TONELADAS', 'VALOR_PRODUTO', 'VALOR_TOTAL'):
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    df['CFOP'] = df['CFOP'].astype(str).str.strip()
    df['TIPO'] = df['CFOP'].map(lambda c: 'indireta' if c in CFOPS_INDIRETA else 'direta')
    for col in ('CLIENTE', 'PRODUTO', 'GRUPO', 'CIDADE', 'REPRESENTANTE', 'NATUREZA', 'EMPRESA_FILIAL', 'UNIDADE'):
        df[col] = df[col].fillna('').astype(str).str.strip()
    df['DATA'] = pd.to_datetime(df['DATA']).dt.strftime('%Y-%m-%d')
    return df


def _linha(r) -> dict:
    return {
        'nf': int(r.NFCOD), 'nota': int(r.NOTA), 'data': r.DATA, 'empresa': r.EMPRESA_FILIAL,
        'cliente_codigo': int(r.CLIENTE_CODIGO), 'cliente': r.CLIENTE,
        'cidade': r.CIDADE, 'uf': (r.UF or '').strip(),
        'cfop': f'{r.CFOP[:1]}.{r.CFOP[1:]}', 'natureza': r.NATUREZA, 'tipo': r.TIPO,
        'produto_codigo': int(r.PRODUTO_CODIGO), 'produto': r.PRODUTO, 'unidade': r.UNIDADE, 'grupo': r.GRUPO,
        'quantidade': round(float(r.QUANTIDADE), 3), 'toneladas': round(float(r.TONELADAS), 3),
        'valor_produto': round(float(r.VALOR_PRODUTO), 2), 'valor_total': round(float(r.VALOR_TOTAL), 2),
        'representante': r.REPRESENTANTE,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def faturamento_exportacao(request):
    """
    Itens faturados para exportação no período (uma linha por item de nota).
    ?inicio=AAAA-MM-DD (padrão 2023-01-01) &fim=AAAA-MM-DD (padrão 2025-12-31)
    Os totais e agrupamentos do dash são feitos na tela, sobre estas linhas.
    """
    try:
        inicio = _data(request.GET.get('inicio'), INICIO_PADRAO)
        fim = _data(request.GET.get('fim'), FIM_PADRAO)
    except ValueError:
        return Response({'erro': 'Data inválida (use AAAA-MM-DD).'}, status=400)
    if inicio > fim:
        return Response({'erro': 'A data inicial é depois da final.'}, status=400)
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
