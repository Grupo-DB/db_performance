from django.http import JsonResponse
from datetime import datetime,timedelta
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from django.shortcuts import render
from django.db import connections
import pandas as pd
import locale
from sqlalchemy import create_engine

locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')

connection_string = 'mssql+pyodbc://DBCONSULTA:DB%40%402023**@172.50.10.5/DB?driver=ODBC+Driver+17+for+SQL+Server'
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['POST'])
def calculos_cal(request):
    tipo_calculo = request.data.get('tipo_calculo')
    # Definindo as datas com base no tipo de cálculo
    if tipo_calculo == 'atual':
        data_inicio = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d 07:10:00')
        data_fim = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d 07:10:00')
    elif tipo_calculo == 'mensal':
        data_inicio = datetime.now().strftime('%Y-%m-01 07:10:00')  # Início do mês
        data_fim = datetime.now().strftime('%Y-%m-%d 07:10:00')  # Data atual
    elif tipo_calculo == 'anual':
        data_inicio = datetime.now().strftime('%Y-01-01 07:10:00')  # Início do ano
        data_fim = datetime.now().strftime('%Y-%m-%d 07:10:00')  # Data atual
    else:
        return JsonResponse({'error': 'Tipo de cálculo inválido'}, status=400)

 ##--------------------------------------TOTAL DO CARREGAMENTO ----------------------######################   
    consulta_movimentacao = pd.read_sql(f"""
    SELECT CLINOME, CLICOD, TRANNOME, TRANCOD, NFPLACA, ESTUF, NFPED, NFNUM, SDSSERIE, NFDATA,
        ESTQCOD, ESTQNOME, ESPSIGLA,
        ((INFQUANT * INFPESO) /1000) QUANT,
        (INFTOTAL / (NFTOTPRO + NFTOTSERV) * (NFTOTPRO + NFTOTSERV)) TOTAL_PRODUTO,
        (INFTOTAL / (NFTOTPRO + NFTOTSERV) * NFTOTAL) TOTAL,
        INFDAFRETE FRETE
        FROM NOTAFISCAL
        JOIN SERIEDOCSAIDA ON SDSCOD = NFSNF
        JOIN NATUREZAOPERACAO ON NOPCOD = NFNOP
        JOIN CLIENTE ON CLICOD = NFCLI
        JOIN ITEMNOTAFISCAL ON INFNFCOD = NFCOD
        JOIN ESTOQUE ON ESTQCOD = INFESTQ
        JOIN ESPECIE ON ESPCOD = ESTQESP
        LEFT OUTER JOIN TRANSPORTADOR ON TRANCOD = NFTRAN
        LEFT OUTER JOIN PEDIDO ON PEDNUM = INFPED
        LEFT OUTER JOIN ESTADO ON ESTCOD = NFEST
        WHERE NFSIT = 1
        AND NFSNF NOT IN (8) -- Serie Acerto
        AND NFEMP = 1
        AND NFFIL = 0
        AND NOPFLAGNF LIKE '_S%'
        AND CAST (NFDATA as datetime2) BETWEEN '{data_inicio}' AND '{data_fim}'
        AND ESTQCOD IN (2833,2744,2738,2742,2743,2741,2740,2736,2737)

    ORDER BY NFDATA, NFNUM
                 """,engine)
        #KPI´S
    total_movimentacao = consulta_movimentacao['QUANT'].sum()
    total_movimentacao = locale.format_string("%.0f",total_movimentacao, grouping=True)

#---------------------------------CONSULTA CAL ---------------------------#########
    etapa = request.data.get('etapa')
    consulta_cal = pd.read_sql(f"""
            SELECT BPROCOD, BPRODATA, ESTQCOD,EQPLOC, ESTQNOMECOMP,BPROEQP,BPROHRPROD,BPROHROPER,BPROFPROQUANT,BPROFPRO,
                IBPROQUANT, ((ESTQPESO*IBPROQUANT) /1000) PESO

                FROM BAIXAPRODUCAO
                JOIN ITEMBAIXAPRODUCAO ON BPROCOD = IBPROBPRO
                JOIN ESTOQUE ON ESTQCOD = IBPROREF
                LEFT OUTER JOIN EQUIPAMENTO ON EQPCOD = BPROEQP

                WHERE CAST(BPRODATA1 as datetime2) BETWEEN '{data_inicio}' AND '{data_fim}'

                AND BPROEMP = 1
                AND BPROFIL =0
                AND BPROSIT = 1
                AND IBPROTIPO = 'D'
                AND BPROEP = '{etapa}'
                
                ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD
            """,engine)
    
    #KPI's ensacados
    #Calcinação
    cal_calcinacao_int = consulta_cal[consulta_cal['ESTQCOD'] == 8].groupby('ESTQCOD')['IBPROQUANT'].sum()
    cal_calcinacao_val = cal_calcinacao_int.item() if not cal_calcinacao_int.empty else 0
    cal_calcinacao_quant = locale.format_string("%.1f",cal_calcinacao_val,grouping=True) if cal_calcinacao_val > 0 else 0

###---------------------------------CONSULTA EQUIPAMENTOS --------------------##########

    # eqpto = request.data.get('eqpto')
    # etapa = request.data.get('etapa')
    # consulta_equipamentos = pd.read_sql(f"""
    #     SELECT 
    #     CASE
    #         WHEN EPNOME LIKE '%ARGAMASSA%' THEN 7
    #         WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM1%' THEN 1
    #         WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM2%' THEN 2
    #         WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM3%' THEN 3
    #         WHEN EPNOME LIKE '%CAL%' AND EQPAUTOMTAG LIKE '%FCC%' THEN 5
    #         WHEN EPNOME LIKE '%CAL%' AND EQPAUTOMTAG NOT LIKE '%FCC%' THEN 6
    #         WHEN EPNOME LIKE '%FERTILIZANTE%' THEN 4
    #         ELSE 999
    #     END ORDEM,
    #     CASE
    #         WHEN EPNOME LIKE '%ARGAMASSA%' THEN 'ARGAMASSA'
    #         WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM1%' THEN 'CALCARIO 1'
    #         WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM2%' THEN 'CALCARIO 2'
    #         WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM3%' THEN 'CALCARIO 3'
    #         WHEN EPNOME LIKE '%CAL%' AND EQPAUTOMTAG LIKE '%FCC%' THEN 'CALCINACAO'
    #         WHEN EPNOME LIKE '%CAL%' AND EQPAUTOMTAG NOT LIKE '%FCC%' THEN 'CAL'
    #         WHEN EPNOME LIKE '%FERTILIZANTE%' THEN 'FERTILIZANTE'
    #         ELSE EPNOME 
    #     END FABRICA,
    #     EPNOME ETAPA, 
    #     BPROCOD DIARIA,
    #     CASE 
    #         WHEN EQPAUTOMTAG = '' OR EQPAUTOMTAG IS NULL THEN EQPNOME
    #         ELSE EQPAUTOMTAG
    #     END EQUIPAMENTO, 
    #     BPROEQP EQUIPAMENTO_CODIGO, 
    #     CASE
    #         WHEN BPROEQP = 0 OR BPROEQP IS NULL THEN DATEPART(HOUR, BPRODATA2 - BPRODATA1) + 
    #                                                 (CAST(DATEPART(MINUTE, BPRODATA2 - BPRODATA1) AS DOUBLE PRECISION) / 60)
    #         ELSE BPROHRTOT
    #     END HRTOT, 
    #     CASE
    #         WHEN BPROEQP = 0 OR BPROEQP IS NULL THEN DATEPART(HOUR, BPRODATA2 - BPRODATA1) + 
    #                                                 (CAST(DATEPART(MINUTE, BPRODATA2 - BPRODATA1) AS DOUBLE PRECISION) / 60)
    #         ELSE BPROHRPROD
    #     END HRPRO, 
    #     CASE
    #         WHEN BPROEQP = 0 OR BPROEQP IS NULL THEN DATEPART(HOUR, BPRODATA2 - BPRODATA1) + 
    #                                                 (CAST(DATEPART(MINUTE, BPRODATA2 - BPRODATA1) AS DOUBLE PRECISION) / 60)
    #         ELSE BPROHROPER
    #     END HROPER,
    #     (SELECT SUM(EDPRHRTOT) FROM EVENTODIARIAPROD WHERE EDPRBPRO = BPRO.BPROCOD) HREVENTO,
    #     IBPROQUANT QUANT, 
    #     ESPSIGLA SIGLA,
    #     (SELECT PPDADOCHAR FROM PESPARAMETRO WHERE PPTPP = 7 AND PPREF = BPRO.BPROCOD) CONDICAO,
    #     (SELECT PPDADOCHAR FROM PESPARAMETRO WHERE PPTPP = 8 AND PPREF = BPRO.BPROCOD) MATERIAL,
    #     (SELECT PPDADOCHAR FROM PESPARAMETRO WHERE PPTPP = 584 AND PPREF = BPRO.BPROCOD) TELA
    #     FROM BAIXAPRODUCAO BPRO
    #     JOIN ETAPAPRODUCAO ON EPCOD = BPROEP
    #     LEFT OUTER JOIN FICHAPRODUTO ON FPROCOD = BPROFPRO
    #     LEFT OUTER JOIN EQUIPAMENTO ON EQPCOD = BPROEQP
    #     LEFT OUTER JOIN ITEMBAIXAPRODUCAO ON IBPROTIPO = 'D' AND IBPROBPRO = BPROCOD
    #     LEFT OUTER JOIN ESTOQUE ON ESTQCOD = IBPROREF
    #     LEFT OUTER JOIN ESPECIE ON ESPCOD = ESTQESP
    #     WHERE BPROSIT = 1
    #     AND BPROEMP = 1
    #     AND BPROFIL = 0
    #     AND CAST(BPRODATA1 as date) BETWEEN '{data_inicio}' AND '{data_fim}'
    #     AND BPROEP = '{etapa}'
    #     AND BPROEQP = '{eqpto}'
    #     ORDER BY BPRO.BPROCOD

    #     """,engine)


    response_data = {
            'total_movimentacao': total_movimentacao,
            'cal_calcinacao_quant':cal_calcinacao_quant
        }

    return JsonResponse(response_data, safe=False)