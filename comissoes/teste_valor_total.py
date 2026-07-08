import datetime as _dt
import unicodedata

import pandas as pd
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from sqlalchemy import text

from .views import engine
from .models import MapeamentoMunicipio

VENDEDORES_AGRO = ('ILDOMAR DA FONTE CARVALHO', 'EVERTON MARQUES DORNELES')


def _norm_cidade(s):
    nfkd = unicodedata.normalize('NFKD', str(s) if s else '')
    return nfkd.encode('ascii', 'ignore').decode('ascii').upper().strip()


@csrf_exempt
@api_view(['POST', 'GET'])
def descobrir_colunas_pedido(request):
    """Endpoint de investigação (temporário): lista as colunas de PEDIDO e ITEMPEDIDO
    para eu conseguir montar a consulta de 'pedidos pendentes direto do ERP'."""
    sql = """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME IN ('PEDIDO', 'ITEMPEDIDO')
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(sql)).mappings().all()]
    return Response({'colunas': rows})


@csrf_exempt
@api_view(['POST'])
def teste_total_vendedor_valor_total(request):
    """Endpoint de teste/diagnóstico (leve): recalcula o 'Total Vendedor' do Agronegócio
    (Vendas Diretas + Vendas por Representantes) usando VALOR_TOTAL em vez de VALOR_PRODUTO,
    para comparar contra o 'Confirmado' da conferência de planilha. Não altera comissão nenhuma."""
    data_inicio = request.data.get('dataInicio')
    data_fim = request.data.get('dataFim')
    if not data_inicio or not data_fim:
        return Response({'erro': 'Informe dataInicio e dataFim (YYYY-MM-DD).'}, status=400)

    sql = f"""
        SELECT NF.NFDATA DATA_EMISSAO, NF.NFNUM NOTA_FISCAL, CLINOME CLIENTE_NOME,
        (SELECT CIDNOME + '-' + ESTUF FROM CIDADE JOIN ESTADO ON ESTCOD = CIDEST WHERE CIDCOD = CLICIDADE) CIDADE_FATURAMENTO,
        M.REPNOME REPRESENTANTE_MASTER,
        ((INFTOTAL / NULLIF((NFTOTPRO + NFTOTSERV), 0)) * (NFTOTPRO + NFTOTSERV)) AS VALOR_PRODUTO,
        ((INFTOTAL / NULLIF((NFTOTPRO + NFTOTSERV), 0)) * NFTOTAL) AS VALOR_TOTAL,
        'VENDA' AS TIPO
        FROM NOTAFISCAL NF
        JOIN CLIENTE ON CLICOD = NF.NFCLI
        LEFT JOIN REPRESENTANTE R ON R.REPCOD = NF.NFREP
        LEFT JOIN REPRESENTANTE M ON M.REPCOD = R.REPREPREF
        JOIN ITEMNOTAFISCAL INF ON INF.INFNFCOD = NF.NFCOD
        JOIN NATUREZAOPERACAO NOP ON NOP.NOPCOD = INF.INFNOP
        JOIN ESTOQUE ESTQ ON ESTQ.ESTQCOD = INF.INFESTQ
        JOIN GRUPOALMOXARIFADO ON GALMCOD = ESTQ.ESTQGALM
        WHERE NF.NFSIT = 1
        AND CAST(NF.NFDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
        AND ESTQ.ESTQGALM IN (1974, 1587, 1828)
        AND GALMPRODVENDA = 'S'
        AND (SUBSTRING(NOP.NOPFLAGNF, 1, 1) = 'S' AND SUBSTRING(NOP.NOPFLAGNF, 25, 1) = 'N')
        AND NF.NFSNF NOT IN (8)

        UNION ALL

        SELECT NFE.NFEDATA, NFE.NFENUMNF, CLINOME,
        (SELECT CIDNOME + '-' + ESTUF FROM CIDADE JOIN ESTADO ON ESTCOD = CIDEST WHERE CIDCOD = CLICIDADE),
        M.REPNOME,
        -INFETOTAL,
        -INFTOTAL,
        'DEVOLUCAO'
        FROM NOTAFISCAL NF
        JOIN CLIENTE ON CLICOD = NF.NFCLI
        LEFT JOIN REPRESENTANTE R ON R.REPCOD = NF.NFREP
        LEFT JOIN REPRESENTANTE M ON M.REPCOD = R.REPREPREF
        JOIN ITEMNOTAFISCAL INF ON INF.INFNFCOD = NF.NFCOD
        JOIN ITEMNOTAFISCALENTRADA ON INFEINFNUM = INF.INFNUM
        JOIN NATUREZAOPERACAOENTRADA ON NOPECOD = INFENOPE
        JOIN NATUREZAOPERACAO NOP ON NOP.NOPCOD = INF.INFNOP
        JOIN NOTAFISCALENTRADA NFE ON NFE.NFECOD = INFENFE
        JOIN ESTOQUE ESTQ ON ESTQ.ESTQCOD = INF.INFESTQ
        JOIN GRUPOALMOXARIFADO ON GALMCOD = ESTQ.ESTQGALM
        WHERE NF.NFSIT = 1
        AND CAST(NFE.NFEDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
        AND ESTQ.ESTQGALM IN (1974, 1587, 1828)
        AND GALMPRODVENDA = 'S'
        AND (SUBSTRING(NOP.NOPFLAGNF, 1, 1) = 'S' AND SUBSTRING(NOP.NOPFLAGNF, 25, 1) = 'N')
        AND NF.NFSNF NOT IN (8)
    """
    df = pd.read_sql(sql, engine)

    # Remove notas canceladas no ERP após o fechamento do mês anterior (mesmo critério do endpoint principal)
    dt_inicio = _dt.datetime.strptime(data_inicio, '%Y-%m-%d').date()
    ultimo_dia_mes_ant = dt_inicio.replace(day=1) - _dt.timedelta(days=1)
    canc_inicio = ultimo_dia_mes_ant.replace(day=1).strftime('%Y-%m-%d')
    canc_fim = ultimo_dia_mes_ant.strftime('%Y-%m-%d')
    df_canceladas = pd.read_sql(f"""
        SELECT DISTINCT NFNUM
        FROM NOTAFISCAL NF
        JOIN ITEMNOTAFISCAL ON INFNFCOD = NFCOD
        LEFT JOIN DOCUMENTOELETRONICO ON DEREF = NFCOD
        LEFT JOIN SERIEDOCSAIDA ON SDSCOD = NFSNF
        WHERE NFSIT = 2
          AND SDSNFPROD = 'S' AND SDSELETRONICO = 'S'
          AND DESIT IN (4, 5)
          AND CAST(NFDATA AS DATE) BETWEEN '{canc_inicio}' AND '{canc_fim}'
    """, engine)
    df = df[~df['NOTA_FISCAL'].isin(set(df_canceladas['NFNUM'].dropna()))].copy()

    df['CLIENTE_NOME'] = df['CLIENTE_NOME'].fillna('').str.strip().str.upper()
    df['CIDADE_FATURAMENTO'] = df['CIDADE_FATURAMENTO'].fillna('').str.strip().str.upper()
    df['REPRESENTANTE_MASTER'] = df['REPRESENTANTE_MASTER'].fillna('').str.strip().str.upper()

    mask_yara = df['CLIENTE_NOME'].str.contains('YARA', na=False)
    mask_cotrijal = df['CLIENTE_NOME'].str.contains('COTRIJAL', na=False)
    df_no_yara = df[~mask_yara].copy()

    mapa_municipio = {
        _norm_cidade(m.cidade_estado): m.representante.nome.strip().upper()
        for m in MapeamentoMunicipio.objects.filter(segmento='AGRONEGOCIO').select_related('representante')
    }
    df['_rep_agro_full'] = df['CIDADE_FATURAMENTO'].apply(lambda c: mapa_municipio.get(_norm_cidade(c), ''))
    df_no_yara['_rep_agro'] = df_no_yara['CIDADE_FATURAMENTO'].apply(lambda c: mapa_municipio.get(_norm_cidade(c), ''))

    resultado = {}
    for nome in VENDEDORES_AGRO:
        df_rep = df_no_yara[df_no_yara['_rep_agro'] == nome]
        mask_cotrijal_rep = mask_cotrijal.reindex(df_rep.index, fill_value=False)
        df_rep_valido = df_rep[~mask_cotrijal_rep]
        df_direta = df_rep_valido[df_rep_valido['REPRESENTANTE_MASTER'] == '']
        df_reps = df_rep_valido[df_rep_valido['REPRESENTANTE_MASTER'] != '']

        # Diagnóstico: tudo que cai na cidade do vendedor, SEM excluir YARA/COTRIJAL/devolução
        df_cidade = df[df['_rep_agro_full'] == nome]
        df_yara_na_cidade = df_cidade[mask_yara.reindex(df_cidade.index, fill_value=False)]
        df_devolucao_no_total = df_rep_valido[df_rep_valido['TIPO'] == 'DEVOLUCAO']

        resultado[nome] = {
            'total_vendedor_valor_produto': round(float(df_direta['VALOR_PRODUTO'].sum() + df_reps['VALOR_PRODUTO'].sum()), 2),
            'total_vendedor_valor_total': round(float(df_direta['VALOR_TOTAL'].sum() + df_reps['VALOR_TOTAL'].sum()), 2),
            'direta_valor_produto': round(float(df_direta['VALOR_PRODUTO'].sum()), 2),
            'direta_valor_total': round(float(df_direta['VALOR_TOTAL'].sum()), 2),
            'representantes_valor_produto': round(float(df_reps['VALOR_PRODUTO'].sum()), 2),
            'representantes_valor_total': round(float(df_reps['VALOR_TOTAL'].sum()), 2),
            'qtd_lancamentos': int(len(df_rep_valido)),

            'diagnostico_yara_na_cidade_valor_total': round(float(df_yara_na_cidade['VALOR_TOTAL'].sum()), 2),
            'diagnostico_yara_na_cidade_qtd': int(len(df_yara_na_cidade)),
            'diagnostico_yara_na_cidade_notas': (
                df_yara_na_cidade[['NOTA_FISCAL', 'CLIENTE_NOME', 'VALOR_TOTAL']]
                .round(2).to_dict(orient='records')
            ),

            'diagnostico_devolucao_ja_descontada_valor_total': round(float(df_devolucao_no_total['VALOR_TOTAL'].sum()), 2),
            'diagnostico_devolucao_ja_descontada_qtd': int(len(df_devolucao_no_total)),
            'diagnostico_devolucao_notas': (
                df_devolucao_no_total[['NOTA_FISCAL', 'CLIENTE_NOME', 'VALOR_TOTAL']]
                .round(2).to_dict(orient='records')
            ),

            # Lista completa das notas que compõem o Total Vendedor (para cruzar manualmente
            # com os NFs do "Confirmado" da conferência de planilha).
            'notas_incluidas': (
                df_rep_valido[['NOTA_FISCAL', 'CLIENTE_NOME', 'CIDADE_FATURAMENTO', 'VALOR_PRODUTO', 'VALOR_TOTAL', 'TIPO']]
                .round(2).to_dict(orient='records')
            ),
        }

    return Response(resultado)
