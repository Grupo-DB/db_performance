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

    response_data = {
            'total_movimentacao': total_movimentacao,
        }

    return JsonResponse(response_data, safe=False)
#---------------------------------CONSULTA CAL ---------------------------#########
@csrf_exempt
@api_view(['POST'])
def calculos_cal_produtos(request):
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
    cal_calcinacao_int = consulta_cal[consulta_cal['ESTQCOD'] == 2621 ].groupby('ESTQCOD')['IBPROQUANT'].sum()
    cal_calcinacao_val = cal_calcinacao_int.item() if not cal_calcinacao_int.empty else 0
    cal_calcinacao_quant = locale.format_string("%.0f",cal_calcinacao_val,grouping=True) if cal_calcinacao_val > 0 else 0
    #Beneficiamento
    cal_hidraulica_int = consulta_cal[consulta_cal['ESTQCOD']==2738].groupby('ESTQCOD')['IBPROQUANT'].sum()
    cal_hidraulica_val = cal_hidraulica_int.item() if not cal_hidraulica_int.empty else 0
    cal_hidraulica_quant = locale.format_string("%.0f",cal_hidraulica_val,grouping=True) if cal_hidraulica_val > 0 else 0        
    #Beneficiamento
    cal_cvc_int = consulta_cal[consulta_cal['ESTQCOD']==2736].groupby('ESTQCOD')['IBPROQUANT'].sum()
    cal_cvc_val = cal_cvc_int.item() if not cal_cvc_int.empty else 0
    cal_cvc_quant = locale.format_string("%.0f",cal_cvc_val,grouping=True) if cal_cvc_val > 0 else 0
    #Beneficiamento
    cal_ch2_int = consulta_cal[consulta_cal['ESTQCOD']==2737].groupby('ESTQCOD')['IBPROQUANT'].sum()
    cal_ch2_val = cal_ch2_int.item() if not cal_ch2_int.empty else 0
    cal_ch2_quant = locale.format_string("%.0f",cal_ch2_val,grouping=True) if cal_ch2_val > 0 else 0

    #ENSACADOS
    cvc_ensacado_int = consulta_cal[consulta_cal['ESTQCOD'].isin([2740,2741])]['IBPROQUANT'].sum()
    cvc_ensacado_val = cvc_ensacado_int if cvc_ensacado_int > 0 else 0
    cvc_ensacado_quant = locale.format_string("%.0f", cvc_ensacado_val, grouping=True) if cvc_ensacado_val > 0 else 0

    ch2_ensacado_int = consulta_cal[consulta_cal['ESTQCOD'].isin([2744,2833])]['IBPROQUANT'].sum()
    ch2_ensacado_val = ch2_ensacado_int if ch2_ensacado_int > 0 else 0
    ch2_ensacado_quant = locale.format_string("%.0f", ch2_ensacado_val, grouping=True) if ch2_ensacado_val > 0 else 0

    hidraulica_ensacado_int = consulta_cal[consulta_cal['ESTQCOD'].isin([2742,2743])]['IBPROQUANT'].sum()
    hidraulica_ensacado_val = hidraulica_ensacado_int if hidraulica_ensacado_int > 0 else 0
    hidraulica_ensacado_quant = locale.format_string("%.0f", hidraulica_ensacado_val, grouping=True) if hidraulica_ensacado_val > 0 else 0

    response_data = {
        #------ENSACADOS------------#########
            'cvc_ensacado_quant': cvc_ensacado_quant,
            'ch2_ensacado_quant' : ch2_ensacado_quant,
            'hidraulica_ensacado_quant': hidraulica_ensacado_quant,
        #-------TOTAL DOS FORNOS------------    
            'total_fornos':cal_calcinacao_quant,
        #----------PRODUÇÃO--------------#########    
            'cal_hidraulica_quant': cal_hidraulica_quant,
            'cal_cvc_quant': cal_cvc_quant,
            'cal_ch2_quant': cal_ch2_quant,
            
        }
    return JsonResponse(response_data, safe=False)
###---------------------------------CONSULTA EQUIPAMENTOS --------------------##########
@csrf_exempt
@api_view(['POST'])
def calculos_cal_equipamentos(request):
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
    
    consulta_equipamentos = pd.read_sql(f"""
        SELECT 
        CASE
            WHEN EPNOME LIKE '%ARGAMASSA%' THEN 7
            WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM1%' THEN 1
            WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM2%' THEN 2
            WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM3%' THEN 3
            WHEN EPNOME LIKE '%CAL%' AND EQPAUTOMTAG LIKE '%FCC%' THEN 5
            WHEN EPNOME LIKE '%CAL%' AND EQPAUTOMTAG NOT LIKE '%FCC%' THEN 6
            WHEN EPNOME LIKE '%FERTILIZANTE%' THEN 4
            ELSE 999
        END ORDEM,
        CASE
            WHEN EPNOME LIKE '%ARGAMASSA%' THEN 'ARGAMASSA'
            WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM1%' THEN 'CALCARIO 1'
            WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM2%' THEN 'CALCARIO 2'
            WHEN EPNOME LIKE '%CALCARIO%' AND EQPAUTOMTAG LIKE '%FCM3%' THEN 'CALCARIO 3'
            WHEN EPNOME LIKE '%CAL%' AND EQPAUTOMTAG LIKE '%FCC%' THEN 'CALCINACAO'
            WHEN EPNOME LIKE '%CAL%' AND EQPAUTOMTAG NOT LIKE '%FCC%' THEN 'CAL'
            WHEN EPNOME LIKE '%FERTILIZANTE%' THEN 'FERTILIZANTE'
            ELSE EPNOME 
        END FABRICA,
        EPNOME ETAPA, 
        BPROCOD DIARIA,
        CASE 
            WHEN EQPAUTOMTAG = '' OR EQPAUTOMTAG IS NULL THEN EQPNOME
            ELSE EQPAUTOMTAG
        END EQUIPAMENTO, 
        BPROEQP EQUIPAMENTO_CODIGO, 
        CASE
            WHEN BPROEQP = 0 OR BPROEQP IS NULL THEN DATEPART(HOUR, BPRODATA2 - BPRODATA1) + 
                                                    (CAST(DATEPART(MINUTE, BPRODATA2 - BPRODATA1) AS DOUBLE PRECISION) / 60)
            ELSE BPROHRTOT
        END HRTOT, 
        CASE
            WHEN BPROEQP = 0 OR BPROEQP IS NULL THEN DATEPART(HOUR, BPRODATA2 - BPRODATA1) + 
                                                    (CAST(DATEPART(MINUTE, BPRODATA2 - BPRODATA1) AS DOUBLE PRECISION) / 60)
            ELSE BPROHRPROD
        END HRPRO, 
        CASE
            WHEN BPROEQP = 0 OR BPROEQP IS NULL THEN DATEPART(HOUR, BPRODATA2 - BPRODATA1) + 
                                                    (CAST(DATEPART(MINUTE, BPRODATA2 - BPRODATA1) AS DOUBLE PRECISION) / 60)
            ELSE BPROHROPER
        END HROPER,
        (SELECT SUM(EDPRHRTOT) FROM EVENTODIARIAPROD WHERE EDPRBPRO = BPRO.BPROCOD) HREVENTO,
        IBPROQUANT QUANT, 
        ESPSIGLA SIGLA,
        (SELECT PPDADOCHAR FROM PESPARAMETRO WHERE PPTPP = 7 AND PPREF = BPRO.BPROCOD) CONDICAO,
        (SELECT PPDADOCHAR FROM PESPARAMETRO WHERE PPTPP = 8 AND PPREF = BPRO.BPROCOD) MATERIAL,
        (SELECT PPDADOCHAR FROM PESPARAMETRO WHERE PPTPP = 584 AND PPREF = BPRO.BPROCOD) TELA
        FROM BAIXAPRODUCAO BPRO
        JOIN ETAPAPRODUCAO ON EPCOD = BPROEP
        LEFT OUTER JOIN FICHAPRODUTO ON FPROCOD = BPROFPRO
        LEFT OUTER JOIN EQUIPAMENTO ON EQPCOD = BPROEQP
        LEFT OUTER JOIN ITEMBAIXAPRODUCAO ON IBPROTIPO = 'D' AND IBPROBPRO = BPROCOD
        LEFT OUTER JOIN ESTOQUE ON ESTQCOD = IBPROREF
        LEFT OUTER JOIN ESPECIE ON ESPCOD = ESTQESP
        WHERE BPROSIT = 1
        AND BPROEMP = 1
        AND BPROFIL = 0
        AND CAST(BPRODATA1 as datetime2) BETWEEN '{data_inicio}' AND '{data_fim}'
        AND BPROEP = 2
        AND BPROEQP IN (369,370,371,372,373,374,375)
        ORDER BY BPRO.BPROCOD

        """,engine)
     #KPI'S
    azbe_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 375 ].groupby('EQUIPAMENTO_CODIGO')['QUANT'].sum()
    azbe_val = azbe_int.item() if not azbe_int.empty else 0
    azbe_quant = locale.format_string("%.0f",azbe_val,grouping=True) if azbe_val > 0 else 0

    metalicos_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'].isin([369, 370, 371, 372, 373, 374])]['QUANT'].sum()
    metalicos_val = metalicos_int if metalicos_int > 0 else 0
    metalicos_quant = locale.format_string("%.0f", metalicos_val, grouping=True) if metalicos_val > 0 else 0

    response_data = {
            'azbe_quant': azbe_quant,
            'metalicos_quant': metalicos_quant
        }

##############-----------------------------------CALCULAR GRÀFICOS CAL------------------------------------####
@csrf_exempt
@api_view(['POST'])
def calculos_cal_graficos(request):

    # Recuperando o tipo de cálculo do corpo da requisição
    tipo_calculo = request.data.get('tipo_calculo')
    etapa = request.data.get('etapa')
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
    # Inicializar variáveis
    volume_diario = None
    volume_mensal = None

    if 'BPRODATA' in consulta_cal.columns:
        consulta_cal['BPRODATA'] = pd.to_datetime(consulta_cal['BPRODATA'],errors='coerce')
        consulta_cal = consulta_cal.dropna(subset=['BPRODATA']) # remove as linhas onde a data é nula

     # Quebrando o cálculo mensal em dias
    if tipo_calculo == 'mensal':
        consulta_cal['DIA'] = consulta_cal['BPRODATA'].dt.day

        #Função para preencher em caso de dias faltantes
        def preencher_dias_faltantes(volume_df):
            dias_completos = pd.DataFrame({'DIA': range(1, 32)})
            return dias_completos.merge(volume_df, on='DIA', how='left').fillna(0)
        
        #calculo do volume acumulado dos ensacados
        volume_diario_cvc_df = consulta_cal[consulta_cal['ESTQCOD'].isin([2740,2741])].groupby('DIA')['PESO'].sum().reset_index()
        volume_diario_ch2_df = consulta_cal[consulta_cal['ESTQCOD'].isin([2744,2833])].groupby('DIA')['PESO'].sum().reset_index()
        volume_diario_hidraulica_df = consulta_cal[consulta_cal['ESTQCOD'].isin([2742,2743])].groupby('DIA')['PESO'].sum().reset_index()
       
        #Preencher dias Faltantes
        volume_diario_cvc_df = preencher_dias_faltantes(volume_diario_cvc_df)
        volume_diario_ch2_df = preencher_dias_faltantes(volume_diario_ch2_df)
        volume_diario_hidraulica_df = preencher_dias_faltantes(volume_diario_hidraulica_df)

        #MediasDiarias
        media_diaria_cvc = volume_diario_cvc_df['PESO'].mean()
        media_diaria_cvc = locale.format_string("%.0f",media_diaria_cvc,grouping=True)

        media_diaria_ch2 = volume_diario_ch2_df['PESO'].mean()
        media_diaria_ch2 = locale.format_string("%.0f",media_diaria_ch2,grouping=True)

        media_diaria_hidraulica = volume_diario_hidraulica_df['PESO'].mean()
        media_diaria_hidraulica = locale.format_string("%.0f",media_diaria_hidraulica,grouping=True)

        #volume Total
        volume_diario_total = volume_diario_cvc_df['PESO'].sum() + volume_diario_ch2_df['PESO'].sum() + volume_diario_hidraulica_df['PESO'].sum()
        #data Atual 
        hoje = datetime.now().day -1

        # Calculo média agregada todos os produtos
        if hoje > 0 :
            media_diaria_agregada = volume_diario_total / hoje
            media_diaria_agregada = locale.format_string("%.0f",media_diaria_agregada,grouping=True)
        else:
            media_diaria_agregada = 0

        #CAlculo de projeção
        dias_corridos = consulta_cal['DIA'].max()  #último dia no mes que teve produção
        dias_no_mes = (consulta_cal['BPRODATA'].max().replace(day=1) + pd.DateOffset(months=1) - pd.DateOffset(days=1)).day        

        if dias_corridos > 0 :
            volume_ultimo_dia_cvc = consulta_cal[consulta_cal['ESTQCOD'].isin([2740,2741]) & (consulta_cal['DIA'] == dias_corridos )]
            volume_ultimo_dia_ch2 = consulta_cal[consulta_cal['ESTQCOD'].isin([2744.2833]) & (consulta_cal['DIA'] == dias_corridos )]    
            volume_ultimo_dia_hidraulica = consulta_cal[consulta_cal['ESTQCOD'].isin([2742,2743]) & (consulta_cal['DIA'] == dias_corridos )]

            #Volume total
            volume_ultimo_dia_total_cvc = volume_ultimo_dia_cvc['PESO'].sum()
            volume_ultimo_dia_total_ch2 = volume_ultimo_dia_ch2['PESO'].sum()
            volume_ultimo_dia_total_hidraulica = volume_ultimo_dia_hidraulica['PESO'].sum()

            volume_ultimo_dia_total = volume_ultimo_dia_total_cvc + volume_ultimo_dia_total_ch2 + volume_ultimo_dia_total_hidraulica
            volume_ultimo_dia_total = locale.format_string("%.0f",volume_ultimo_dia_total,grouping=True)

            #PROJEÇÂO
            producao_acumulada_cvc = volume_diario_cvc_df['PESO'].sum()
            projecao_cvc = (producao_acumulada_cvc / dias_corridos) * dias_no_mes
            projecao_cvc = locale.format_string("%.0f",projecao_cvc,grouping=True)

            producao_acumulada_ch2 = volume_diario_ch2_df['PESO'].sum()
            projecao_ch2 = (producao_acumulada_ch2 / dias_corridos) * dias_no_mes
            projecao_ch2 = locale.format_string("%.0f",projecao_ch2,grouping=True)

            producao_acumulada_hidraulica = volume_diario_hidraulica_df['PESO'].sum()
            projecao_hidraulica = (producao_acumulada_hidraulica / dias_corridos) * dias_no_mes
            projecao_hidraulica = locale.format_string("%.0f",projecao_hidraulica,grouping=True)
        else :
            projecao_cvc = 0
            projecao_ch2 = 0
            projecao_hidraulica = 0

        #Projecao agregada anual
        projecao_acumulada_total = producao_acumulada_cvc + producao_acumulada_ch2 + producao_acumulada_hidraulica
        if dias_corridos > 0 :
            projecao_total = (projecao_acumulada_total / dias_corridos) * dias_no_mes
            projecao_total = locale.format_string("%.0f",projecao_total,grouping=True)
        else:
            projecao_total = 0

        volume_diario = {
            #----------VOLUMES ULTIMO DIA-----------------------#
            'volume_ultimo_dia_total_cvc': volume_ultimo_dia_total_cvc,
            'volume_ultimo_dia_total_ch2': volume_ultimo_dia_total_ch2,
            'volume_ultimo_dia_total_hidraulica': volume_ultimo_dia_total_hidraulica,
            #------------------PROJEÇÕES--------------------------------#
            'projecao_cvc': projecao_cvc,
            'projecao_ch2': projecao_ch2,
            'projecao_hidraulica': projecao_hidraulica,
            'projecao_total': projecao_total,
            #----------------MEDIAS----------------------------------#
            'media_diaria_cvc': media_diaria_cvc,
            'media_diaria_ch2': media_diaria_ch2,
            'media_diaria_hidraulica': media_diaria_hidraulica,
            'media_diaria_agregada': media_diaria_agregada,
            #---------------VOLUME TOTAL---------------#
            'volume_ultimo_dia_total': volume_ultimo_dia_total,
            'volume_diario_total': volume_diario_total,
            #-----------------INDIVIDUAIS-----------------------#
            'cvc': volume_diario_cvc_df.to_dict(orient='records'),
            'ch2': volume_diario_ch2_df.to_dict(orient='records'),
            'hidraulica': volume_diario_hidraulica_df.to_dict(orient='records'),
        }
        return JsonResponse(volume_diario, safe=False)
    elif tipo_calculo == 'anual':
        consulta_cal['MES'] = consulta_cal['BPRODATA'].dt.month

        # Função para preencher os meses faltantes com 0
        def preencher_meses_faltantes(volume_df):
            meses_completos = pd.DataFrame({'MES': range(1, 13)})
            return meses_completos.merge(volume_df, on='MES', how='left').fillna(0)
        
        #calculo do volume acumulado dos ensacados
        volume_mensal_cvc_df = consulta_cal[consulta_cal['ESTQCOD'].isin([2740,2741])].groupby('MES')['PESO'].sum().reset_index()
        volume_mensal_ch2_df = consulta_cal[consulta_cal['ESTQCOD'].isin([2744,2833])].groupby('MES')['PESO'].sum().reset_index()
        volume_mensal_hidraulica_df = consulta_cal[consulta_cal['ESTQCOD'].isin([2742,2743])].groupby('MES')['PESO'].sum().reset_index()
       
        #Preencher dias Faltantes
        volume_mensal_cvc_df = preencher_meses_faltantes(volume_mensal_cvc_df)
        volume_mensal_ch2_df = preencher_meses_faltantes(volume_mensal_ch2_df)
        volume_mensal_hidraulica_df = preencher_meses_faltantes(volume_mensal_hidraulica_df)

        # Pegando o mês atual (corridos)
        mes_corrente = datetime.now().month

        # Somar o volume mensal sem incluir os meses futuros
        volume_mensal_cvc_df_filtrado = volume_mensal_cvc_df[volume_mensal_cvc_df['MES'] <= mes_corrente]
        volume_mensal_ch2_df_filtrado = volume_mensal_ch2_df[volume_mensal_ch2_df['MES'] <= mes_corrente]
        volume_mensal_hidraulica_df_filtrado = volume_mensal_hidraulica_df[volume_mensal_hidraulica_df['MES'] <= mes_corrente]

        # Médias mensais baseadas nos meses já passados
        media_mensal_cvc = volume_mensal_cvc_df_filtrado['PESO'].sum() / mes_corrente
        media_mensal_cvc = locale.format_string("%.0f", media_mensal_cvc, grouping=True)

        media_mensal_ch2 = volume_mensal_ch2_df_filtrado['PESO'].sum() / mes_corrente
        media_mensal_ch2 = locale.format_string("%.0f", media_mensal_ch2, grouping=True)

        media_mensal_hidraulica = volume_mensal_hidraulica_df_filtrado['PESO'].sum() / mes_corrente
        media_mensal_hidraulica = locale.format_string("%.0f", media_mensal_hidraulica, grouping=True)

        #SOma valores mensais 
        volume_mensal_total = volume_mensal_cvc_df['PESO'].sum() + volume_mensal_ch2_df['PESO'].sum() + volume_mensal_hidraulica_df['PESO'].sum() 
        
        # Calculando o número total de entradas (dias de produção)
        mes = datetime.now().month

        # Calculando a média agregada de todas as fábricas
        if mes > 0:
            media_mensal_agregada = volume_mensal_total / mes
            media_mensal_agregada = locale.format_string("%.0f", media_mensal_agregada, grouping=True)
        else:
            media_mensal_agregada = 0

        # Calculando projeção
        #meses_corridos = consulta_fcm['MES'].max()  # Último dia do mês em que houve produção
        meses_corridos = datetime.now().month
        meses_no_ano = 12

        if meses_corridos > 0 :
            volume_ultimo_mes_cvc = consulta_cal[consulta_cal['ESTQCOD'].isin([2740,2741]) & (consulta_cal['MES'] == meses_corridos )]
            volume_ultimo_mes_ch2 = consulta_cal[consulta_cal['ESTQCOD'].isin([2744.2833]) & (consulta_cal['MES'] == meses_corridos )]    
            volume_ultimo_mes_hidraulica = consulta_cal[consulta_cal['ESTQCOD'].isin([2742,2743]) & (consulta_cal['MES'] == meses_corridos )]

            #Volume total
            volume_ultimo_mes_total_cvc = volume_ultimo_mes_cvc['PESO'].sum()
            volume_ultimo_mes_total_ch2 = volume_ultimo_mes_ch2['PESO'].sum()
            volume_ultimo_mes_total_hidraulica = volume_ultimo_mes_hidraulica['PESO'].sum()

            volume_ultimo_mes_total = volume_ultimo_mes_total_cvc + volume_ultimo_mes_total_ch2 + volume_ultimo_mes_total_hidraulica
            volume_ultimo_mes_total = locale.format_string("%.0f",volume_ultimo_mes_total, grouping=True)

            #PROJEÇÂO
            producao_mensal_acumulada_cvc = volume_mensal_cvc_df['PESO'].sum()
            projecao_anual_cvc = (producao_mensal_acumulada_cvc / meses_corridos) * meses_no_ano
            projecao_anual_cvc = locale.format_string("%.0f", projecao_anual_cvc, grouping=True)

            producao_mensal_acumulada_ch2 = volume_mensal_ch2_df['PESO'].sum()
            projecao_anual_ch2 = (producao_mensal_acumulada_ch2 / meses_corridos) * meses_no_ano
            projecao_anual_ch2 = locale.format_string("%.0f", projecao_anual_ch2, grouping=True)

            producao_mensal_acumulada_hidraulica = volume_mensal_hidraulica_df['PESO'].sum()
            projecao_anual_hidraulica = (producao_mensal_acumulada_hidraulica / meses_corridos) * meses_no_ano
            projecao_anual_hidraulica = locale.format_string("%.0f", projecao_anual_hidraulica, grouping=True)

        else:
            projecao_anual_fcmi = 0
            projecao_anual_fcmii = 0
            projecao_anual_fcmiii = 0

        producao_mensal_acumulada_total = producao_mensal_acumulada_cvc + producao_mensal_acumulada_ch2 + producao_mensal_acumulada_hidraulica
        # Projeção anual agregada
        if meses_corridos > 0:
            projecao_anual_total = (producao_mensal_acumulada_total / meses_corridos) * meses_no_ano
            projecao_anual_total = locale.format_string("%.0f", projecao_anual_total, grouping=True)
        else:
            projecao_anual_total = 0

        volume_mensal = {
            #---------PROJECOES-----------------#
            'projecao_anual_cvc': projecao_anual_cvc,
            'projecao_anual_ch2': projecao_anual_ch2,
            'projecao_anual_hidraulica': projecao_anual_hidraulica,
            'projecao_anual_total': projecao_anual_total,
            #------------MEDIAS--------------#####
            'media_mensal_cvc': media_mensal_cvc,
            'media_mensal_ch2': media_mensal_ch2,
            'media_mensal_hidraulica': media_mensal_hidraulica,
            'media_mensal_agregada': media_mensal_agregada,
            #-----------VOLUMES-----------------####
            'volume_ultimo_mes_total': volume_ultimo_mes_total,
            #-----------INDIVIDUAIS------------#
            'cvc': volume_mensal_cvc_df.to_dict(orient='records'),
            'ch2': volume_mensal_ch2_df.to_dict(orient='records'),
            'hidraulica': volume_mensal_hidraulica_df.to_dict(orient='records')
        }

        response_data = {

    }

    # Adicionando o volume diário se o tipo de cálculo for 'mensal'
    if volume_diario is not None:
        response_data['volume_diario'] = volume_diario

    # Adicionando o volume mensal se o tipo de cálculo for 'anual'
    if volume_mensal is not None:
        response_data['volume_mensal'] = volume_mensal                
    
        return JsonResponse(response_data, safe=False)
    