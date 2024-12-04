from datetime import datetime, timedelta  # Importa as classes necessárias
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
from sqlalchemy import create_engine
import pandas as pd
import locale

locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')  # Exemplo de locale brasileiro

 # String de conexão
connection_string = 'mssql+pyodbc://DBCONSULTA:DB%40%402023**@172.50.10.5/DB?driver=ODBC+Driver+17+for+SQL+Server'
# Cria a engine
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['POST'])
def calculos_calcario(request):
    #connection_name = 'sga'
    fabrica = request.data.get('fabrica')
    # Recuperando o tipo de cálculo do corpo da requisição
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

    consulta_fcm = pd.read_sql(f"""

            SELECT BPROCOD, BPRODATA, ESTQCOD, ESTQNOMECOMP,BPROEQP,BPROHRPROD,BPROHROPER,BPROFPROQUANT,BPROFPRO,
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
                AND BPROEP = 6
                AND EQPLOC = '{fabrica}'

                ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD
            """,engine)

    #KPI´S
    total_fcm = consulta_fcm['PESO'].sum()
    total_fcm_formatado = locale.format_string("%.0f",total_fcm,grouping=True)

    #HS
    tot_hs = consulta_fcm['BPROHRPROD'].sum()
    if tot_hs != 0 :
        tn_hora = total_fcm / tot_hs
    else:
        tn_hora = 0
    tn_hora = locale.format_string("%.2f",tn_hora,grouping=True)
    tot_hs = locale.format_string("%.2f",tot_hs,grouping=True)

########----------------MOVIMENTACAO DE CARGA----------############################################

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
        AND ESTQCOD IN (1,4,5,104,37,2785)

    ORDER BY NFDATA, NFNUM
                 """,engine)

    #KPI'S
    total_movimentacao = consulta_movimentacao['QUANT'].sum()
    total_movimentacao = locale.format_string("%.0f",total_movimentacao, grouping=True)

    response_data = {
        'total_fcm':total_fcm_formatado,
        'tn_hora':tn_hora,
        'total_movimentacao':total_movimentacao,
        'tot_hs':tot_hs
    }

    return JsonResponse(response_data)


#################################-----------------CALCULOS PARA OS GRÁFICOS--------------############################

@csrf_exempt
@api_view(['POST'])
def calculos_graficos_calcario(request):
    connection_name = 'sga'

    fabrica = request.data.get('fabrica')
    # Recuperando o tipo de cálculo do corpo da requisição
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

    consulta_fcm = pd.read_sql(f"""

            SELECT BPROCOD, BPRODATA, ESTQCOD,EQPLOC, ESTQNOMECOMP,BPROEQP,BPROHRPROD,BPROHROPER,BPROFPROQUANT,BPROFPRO,
                IBPROQUANT, ((ESTQPESO*IBPROQUANT) /1000) PESO

                FROM BAIXAPRODUCAO
                JOIN ITEMBAIXAPRODUCAO ON BPROCOD = IBPROBPRO
                JOIN ESTOQUE ON ESTQCOD = IBPROREF
                LEFT OUTER JOIN EQUIPAMENTO ON EQPCOD = BPROEQP

                WHERE CAST(BPRODATA1 as date) BETWEEN '{data_inicio}' AND '{data_fim}'

                AND BPROEMP = 1
                AND BPROFIL =0
                AND BPROSIT = 1
                AND IBPROTIPO = 'D'
                AND BPROEP = 6
                
                ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD
            """,engine)

    # Inicializar variáveis
    volume_diario = None
    volume_mensal = None

    if 'BPRODATA' in consulta_fcm.columns:
        consulta_fcm['BPRODATA'] = pd.to_datetime(consulta_fcm['BPRODATA'],errors='coerce')
        consulta_fcm = consulta_fcm.dropna(subset=['BPRODATA']) # remove as linhas onde a data é nula

    # Quebrando o cálculo mensal em dias
    if tipo_calculo == 'mensal':
        consulta_fcm['DIA'] = consulta_fcm['BPRODATA'].dt.day

        #Função para preencher em caso de dias faltantes
        def preencher_dias_faltantes(volume_df):
            dias_completos = pd.DataFrame({'DIA': range(1, 32)})
            return dias_completos.merge(volume_df, on='DIA', how='left').fillna(0).infer_objects(copy=False)

        #calculo do volume acumulado das tres fabricas
        volume_diario_fcmi_df = consulta_fcm[consulta_fcm['EQPLOC'] == 23].groupby('DIA')['PESO'].sum().reset_index()
        volume_diario_fcmii_df = consulta_fcm[consulta_fcm['EQPLOC'] == 24].groupby('DIA')['PESO'].sum().reset_index()
        volume_diario_fcmiii_df = consulta_fcm[consulta_fcm['EQPLOC'] == 25].groupby('DIA')['PESO'].sum().reset_index()

        # Preencher dias faltantes com 0 para cada fábrica
        volume_diario_fcmi_df = preencher_dias_faltantes(volume_diario_fcmi_df)
        volume_diario_fcmii_df = preencher_dias_faltantes(volume_diario_fcmii_df)
        volume_diario_fcmiii_df = preencher_dias_faltantes(volume_diario_fcmiii_df)

        #médias diárias
        media_diaria_fcmi = volume_diario_fcmi_df['PESO'].mean()
        media_diaria_fcmi = locale.format_string("%.0f",media_diaria_fcmi, grouping=True)

        media_diaria_fcmii = volume_diario_fcmii_df['PESO'].mean()
        media_diaria_fcmii = locale.format_string("%.0f",media_diaria_fcmii, grouping=True)

        media_diaria_fcmiii = volume_diario_fcmiii_df['PESO'].mean()
        media_diaria_fcmiii = locale.format_string("%.0f",media_diaria_fcmiii, grouping=True) 


        # Somando os volumes diários de todas as fábricas
        volume_diario_total = int(volume_diario_fcmi_df['PESO'].sum() + volume_diario_fcmii_df['PESO'].sum() + volume_diario_fcmiii_df['PESO'].sum())
        
       # Obter o dia atual
        hoje = datetime.now().day -1

        # Calculando a média agregada de todas as fábricas
        if hoje > 0:
            media_diaria_agregada = volume_diario_total / hoje
            media_diaria_agregada = locale.format_string("%.0f", media_diaria_agregada, grouping=True)
        else:
            media_diaria_agregada = 0

         # Calculando projeção
        dias_corridos = consulta_fcm['DIA'].max()  # Último dia do mês em que houve produção
        dias_no_mes = (consulta_fcm['BPRODATA'].max().replace(day=1) + pd.DateOffset(months=1) - pd.DateOffset(days=1)).day

        if dias_corridos > 0:
            volume_ultimo_dia_fcmi = consulta_fcm[(consulta_fcm['EQPLOC'] == 23) & (consulta_fcm['DIA'] == dias_corridos)]
            volume_ultimo_dia_fcmii = consulta_fcm[(consulta_fcm['EQPLOC'] == 24) & (consulta_fcm['DIA'] == dias_corridos)]
            volume_ultimo_dia_fcmiii = consulta_fcm[(consulta_fcm['EQPLOC'] == 25) & (consulta_fcm['DIA'] == dias_corridos)]
            
            #volume total
            volume_ultimo_dia_total_fcmi = volume_ultimo_dia_fcmi['PESO'].sum()
            volume_ultimo_dia_total_fcmii = volume_ultimo_dia_fcmii['PESO'].sum()
            volume_ultimo_dia_total_fcmiii = volume_ultimo_dia_fcmiii['PESO'].sum()

            volume_ultimo_dia_total = volume_ultimo_dia_total_fcmi + volume_ultimo_dia_total_fcmii + volume_ultimo_dia_total_fcmiii
            volume_ultimo_dia_total = locale.format_string("%.0f",volume_ultimo_dia_total, grouping=True)
                
            #PROJEÇÂO
           
            producao_acumulada_fcmi = volume_diario_fcmi_df['PESO'].sum()
            projecao_fcmi = (producao_acumulada_fcmi / dias_corridos) * dias_no_mes
            projecao_fcmi = locale.format_string("%.0f", projecao_fcmi, grouping=True)

            
            producao_acumulada_fcmii = volume_diario_fcmii_df['PESO'].sum()
            projecao_fcmii = (producao_acumulada_fcmii / dias_corridos) * dias_no_mes
            projecao_fcmii = locale.format_string("%.0f", projecao_fcmii, grouping=True)

            
            producao_acumulada_fcmiii = volume_diario_fcmiii_df['PESO'].sum()
            projecao_fcmiii = (producao_acumulada_fcmiii / dias_corridos) * dias_no_mes
            projecao_fcmiii = locale.format_string("%.0f", projecao_fcmiii, grouping=True)
        else:
            projecao_fcmi = 0
            projecao_fcmii = 0
            projecao_fcmiii = 0
            producao_acumulada_fcmi = 0
            producao_acumulada_fcmii = 0
            producao_acumulada_fcmiii = 0
            volume_ultimo_dia_total_fcmi = 0
            volume_ultimo_dia_total_fcmii = 0
            volume_ultimo_dia_total_fcmiii = 0
            volume_ultimo_dia_total = 0

        producao_acumulada_total = producao_acumulada_fcmi + producao_acumulada_fcmii + producao_acumulada_fcmiii
        # Projeção anual agregada
        if dias_corridos > 0:
            projecao_total = (producao_acumulada_total /dias_corridos) * dias_no_mes
            projecao_total = locale.format_string("%.0f", projecao_total, grouping=True)
        else:
            projecao_total = 0        
            
        volume_diario = {
             'volume_ultimo_dia_total_fcmi':volume_ultimo_dia_total_fcmi,
             'volume_ultimo_dia_total_fcmii': volume_ultimo_dia_total_fcmii,
             'volume_ultimo_dia_total_fcmiii':volume_ultimo_dia_total_fcmiii,
             'projecao_fcmi':projecao_fcmi,
             'projecao_fcmii':projecao_fcmii,
             'projecao_fcmiii':projecao_fcmiii,
             'media_diaria_fcmi': media_diaria_fcmi,
             'media_diaria_fcmii': media_diaria_fcmii,
             'media_diaria_fcmiii': media_diaria_fcmiii,
             'volume_ultimo_dia_total': volume_ultimo_dia_total,
             'media_diaria_agregada': media_diaria_agregada,
             'projecao_total': projecao_total,
             'volume_diario_total': volume_diario_total,
             'fcmi': volume_diario_fcmi_df.to_dict(orient='records'),
             'fcmii': volume_diario_fcmii_df.to_dict(orient='records'),
             'fcmiii': volume_diario_fcmiii_df.to_dict(orient='records'),
        }

    elif tipo_calculo == 'anual':
        consulta_fcm['MES'] = consulta_fcm['BPRODATA'].dt.month

        # Função para preencher os meses faltantes com 0
        def preencher_meses_faltantes(volume_df):
            meses_completos = pd.DataFrame({'MES': range(1, 13)})
            return meses_completos.merge(volume_df, on='MES', how='left').fillna(0).infer_objects(copy=False)

        #calculo do volume acumulado das tres fabricas
        volume_mensal_fcmi_df = consulta_fcm[consulta_fcm['EQPLOC'] == 23].groupby('MES')['PESO'].sum().reset_index()
        volume_mensal_fcmii_df = consulta_fcm[consulta_fcm['EQPLOC'] == 24].groupby('MES')['PESO'].sum().reset_index()
        volume_mensal_fcmiii_df = consulta_fcm[consulta_fcm['EQPLOC'] == 25].groupby('MES')['PESO'].sum().reset_index()
    
         # Preencher meses faltantes com 0 para cada fábrica
        volume_mensal_fcmi_df = preencher_meses_faltantes(volume_mensal_fcmi_df)
        volume_mensal_fcmii_df = preencher_meses_faltantes(volume_mensal_fcmii_df)
        volume_mensal_fcmiii_df = preencher_meses_faltantes(volume_mensal_fcmiii_df)

        # Pegando o mês atual (corridos)
        mes_corrente = datetime.now().month

        # Somar o volume mensal sem incluir os meses futuros
        volume_mensal_fcmi_df_filtrado = volume_mensal_fcmi_df[volume_mensal_fcmi_df['MES'] <= mes_corrente]
        volume_mensal_fcmii_df_filtrado = volume_mensal_fcmii_df[volume_mensal_fcmii_df['MES'] <= mes_corrente]
        volume_mensal_fcmiii_df_filtrado = volume_mensal_fcmiii_df[volume_mensal_fcmiii_df['MES'] <= mes_corrente]

        # Médias mensais baseadas nos meses já passados
        media_mensal_fcmi = volume_mensal_fcmi_df_filtrado['PESO'].sum() / mes_corrente
        media_mensal_fcmi = locale.format_string("%.0f", media_mensal_fcmi, grouping=True)

        media_mensal_fcmii = volume_mensal_fcmii_df_filtrado['PESO'].sum() / mes_corrente
        media_mensal_fcmii = locale.format_string("%.0f", media_mensal_fcmii, grouping=True)

        media_mensal_fcmiii = volume_mensal_fcmiii_df_filtrado['PESO'].sum() / mes_corrente
        media_mensal_fcmiii = locale.format_string("%.0f", media_mensal_fcmiii, grouping=True)

        # Somando os volumes mensais de todas as fábricas
        volume_mensal_total = volume_mensal_fcmi_df['PESO'].sum() + volume_mensal_fcmii_df['PESO'].sum() + volume_mensal_fcmiii_df['PESO'].sum()

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
            volume_ultimo_mes_fcmi = consulta_fcm[(consulta_fcm['EQPLOC'] == 23) & (consulta_fcm['MES'] == meses_corridos)]
            volume_ultimo_mes_fcmii = consulta_fcm[(consulta_fcm['EQPLOC'] == 24) & (consulta_fcm['MES'] == meses_corridos)]
            volume_ultimo_mes_fcmiii = consulta_fcm[(consulta_fcm['EQPLOC'] == 25) & (consulta_fcm['MES'] == meses_corridos)]
            
            #volume total
            volume_ultimo_mes_total_fcmi = volume_ultimo_mes_fcmi['PESO'].sum()
            volume_ultimo_mes_total_fcmii = volume_ultimo_mes_fcmii['PESO'].sum()
            volume_ultimo_mes_total_fcmiii = volume_ultimo_mes_fcmiii['PESO'].sum()

            volume_ultimo_mes_total = volume_ultimo_mes_total_fcmi + volume_ultimo_mes_total_fcmii + volume_ultimo_mes_total_fcmiii
            volume_ultimo_mes_total = locale.format_string("%.0f",volume_ultimo_mes_total, grouping=True)
                
            #PROJEÇÂO
            producao_mensal_acumulada_fcmi = volume_mensal_fcmi_df['PESO'].sum()
            projecao_anual_fcmi = (producao_mensal_acumulada_fcmi / meses_corridos) * meses_no_ano
            projecao_anual_fcmi = locale.format_string("%.0f", projecao_anual_fcmi, grouping=True)

            producao_mensal_acumulada_fcmii = volume_mensal_fcmii_df['PESO'].sum()
            projecao_anual_fcmii = (producao_mensal_acumulada_fcmii / meses_corridos) * meses_no_ano
            projecao_anual_fcmii = locale.format_string("%.0f", projecao_anual_fcmii, grouping=True)

            producao_mensal_acumulada_fcmiii = volume_mensal_fcmiii_df['PESO'].sum()
            projecao_anual_fcmiii = (producao_mensal_acumulada_fcmiii / meses_corridos) * meses_no_ano
            projecao_anual_fcmiii = locale.format_string("%.0f", projecao_anual_fcmiii, grouping=True)
         
        else:
            projecao_anual_fcmi = 0
            projecao_anual_fcmii = 0
            projecao_anual_fcmiii = 0

        producao_mensal_acumulada_total = producao_mensal_acumulada_fcmi + producao_mensal_acumulada_fcmii + producao_mensal_acumulada_fcmiii
        # Projeção anual agregada
        if meses_corridos > 0:
            projecao_anual_total = (producao_mensal_acumulada_total / meses_corridos) * meses_no_ano
            projecao_anual_total = locale.format_string("%.0f", projecao_anual_total, grouping=True)
        else:
            projecao_anual_total = 0    

        volume_mensal = {
            'projecao_anual_fcmi':projecao_anual_fcmi,
            'projecao_anual_fcmii':projecao_anual_fcmii,
            'projecao_anual_fcmiii':projecao_anual_fcmiii,
            'media_mensal_fcmi': media_mensal_fcmi,
            'media_mensal_fcmii': media_mensal_fcmii,
            'media_mensal_fcmiii': media_mensal_fcmiii,
            'volume_ultimo_mes_total': volume_ultimo_mes_total,
            'media_mensal_agregada': media_mensal_agregada,
            'projecao_anual_total': projecao_anual_total,
            'fcmi': volume_mensal_fcmi_df.to_dict(orient='records'),
            'fcmii': volume_mensal_fcmii_df.to_dict(orient='records'),
            'fcmiii': volume_mensal_fcmiii_df.to_dict(orient='records'),
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

#######################################------------CALCULOS---DETALHES--------EQUIPAMENTOS------------##############
@csrf_exempt
@api_view(['POST'])
def calculos_equipamentos_detalhes(request):
    data = request.data.get('data')
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
        AND CAST(BPRODATA1 as date) = '{data}'
        AND BPROEP = 6
        AND BPROEQP IN (110,111,169,18,19,20)
        ORDER BY BPRO.BPROCOD

    """,engine)

    ####################---------FCMI --- MG01---------------###############################################
    fcmi_mg01_hora_producao_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 110].groupby('EQUIPAMENTO_CODIGO')['HRPRO'].sum() #soma
    fcmi_mg01_hora_producao_val = fcmi_mg01_hora_producao_int.item() if not fcmi_mg01_hora_producao_int.empty else 0 #converte o series para um valor
    fcmi_mg01_hora_producao = locale.format_string("%.1f",fcmi_mg01_hora_producao_val, grouping=True) if fcmi_mg01_hora_producao_val > 0 else 0 #formata o valor
    

    fcmi_mg01_hora_parado_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 110 ].groupby('EQUIPAMENTO_CODIGO')['HREVENTO'].sum()
    fcmi_mg01_hora_parado_val = fcmi_mg01_hora_parado_int.item() if not fcmi_mg01_hora_parado_int.empty  else 0
    fcmi_mg01_hora_parado = locale.format_string("%.1f",fcmi_mg01_hora_parado_val, grouping=True) if fcmi_mg01_hora_parado_val > 0 else 0


    fcmi_mg01_producao_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 110 ].groupby('EQUIPAMENTO_CODIGO')['QUANT'].sum()
    fcmi_mg01_producao_val = fcmi_mg01_producao_int.item() if not fcmi_mg01_producao_int.empty else 0
    fcmi_mg01_producao = locale.format_string("%.1f",fcmi_mg01_producao_val, grouping=True) if fcmi_mg01_producao_val > 0 else 0

    if fcmi_mg01_hora_producao_val > 0:
        fcmi_mg01_produtividade = fcmi_mg01_producao_val / fcmi_mg01_hora_producao_val
        #fcmi_mg01_produtividade = locale.format_string("%.1f",fcmi_mg01_produtividade_int, grouping=True)
    else:
        fcmi_mg01_produtividade = 0    
    

    ####################---------FCMI-MG02---------------###############################################
    fcmi_mg02_hora_producao_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 111].groupby('EQUIPAMENTO_CODIGO')['HRPRO'].sum() #soma
    fcmi_mg02_hora_producao_val = fcmi_mg02_hora_producao_int.item() if not fcmi_mg02_hora_producao_int.empty else 0 #converte o series para um valor
    fcmi_mg02_hora_producao = locale.format_string("%.1f",fcmi_mg02_hora_producao_val, grouping=True) if fcmi_mg02_hora_producao_val > 0 else 0
   
    fcmi_mg02_hora_parado_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 111 ].groupby('EQUIPAMENTO_CODIGO')['HREVENTO'].sum()
    fcmi_mg02_hora_parado_val = fcmi_mg02_hora_parado_int.item() if not fcmi_mg02_hora_parado_int.empty else 0
    fcmi_mg02_hora_parado = locale.format_string("%.1f",fcmi_mg02_hora_parado_val, grouping=True) if fcmi_mg02_hora_parado_val > 0 else 0

    fcmi_mg02_producao_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 111 ].groupby('EQUIPAMENTO_CODIGO')['QUANT'].sum()
    fcmi_mg02_producao_val = fcmi_mg02_producao_int.item() if not fcmi_mg02_producao_int.empty else 0
    fcmi_mg02_producao = locale.format_string("%.1f",fcmi_mg02_producao_val, grouping=True) if fcmi_mg02_producao_val >0 else 0

    if fcmi_mg02_hora_producao_val > 0:
        fcmi_mg02_produtividade = fcmi_mg02_producao_val / fcmi_mg02_hora_producao_val
        #fcmi_mg02_produtividade = locale.format_string("%.1f", fcmi_mg02_produtividade, grouping=True)
    else:
        fcmi_mg02_produtividade = 0

    ##################---------TOTAIS FCMI-----------------####################################
    fcmi_produtividade_geral_val = 0 #inicializando a variavel
    if fcmi_mg01_produtividade or fcmi_mg02_produtividade > 0:
        fcmi_produtividade_geral_val = fcmi_mg01_produtividade + fcmi_mg02_produtividade / 2
        fcmi_produtividade_geral = locale.format_string("%.1f",fcmi_produtividade_geral_val, grouping=True)
    else:      
        fcmi_produtividade_geral = 0

    fcmi_producao_geral_val = fcmi_mg01_producao_val + fcmi_mg02_producao_val
    fcmi_producao_geral = locale.format_string("%.1f",fcmi_producao_geral_val,grouping=True)    

    ####################---------FCMII --- MG01---------------###############################################
    fcmii_mg01_hora_prod_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 169].groupby('EQUIPAMENTO_CODIGO')['HRPRO'].sum() #soma
    fcmii_mg01_hora_prod_val = fcmii_mg01_hora_prod_int.item() if not fcmii_mg01_hora_prod_int.empty else 0 #converte o serires do pandas em valor
    fcmii_mg01_hora_prod = locale.format_string("%.1f",fcmii_mg01_hora_prod_val,grouping=True) if fcmii_mg01_hora_prod_val > 0 else 0

    fcmii_mg01_hora_parado_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 169].groupby('EQUIPAMENTO_CODIGO')['HREVENTO'].sum()
    fcmii_mg01_hora_parado_val = fcmii_mg01_hora_parado_int.item() if not fcmii_mg01_hora_parado_int.empty else 0
    fcmii_mg01_hora_parado = locale.format_string("%.1f",fcmii_mg01_hora_parado_val,grouping=True) if fcmii_mg01_hora_parado_val > 0 else 0

    fcmii_mg01_producao_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 169].groupby('EQUIPAMENTO_CODIGO')['QUANT'].sum()
    fcmii_mg01_producao_val = fcmii_mg01_producao_int.item() if not fcmii_mg01_producao_int.empty else 0
    fcmii_mg01_producao = locale.format_string("%.1f",fcmii_mg01_producao_val, grouping=True) if fcmii_mg01_producao_val > 0 else 0

    fcmii_produtividade_geral_val = 0
    if fcmii_mg01_hora_prod_val > 0:
        fcmii_produtividade_geral_val = fcmii_mg01_producao_val / fcmii_mg01_hora_prod_val
        fcmii_produtividade_geral = locale.format_string("%.1f",fcmii_produtividade_geral_val,grouping=True)
    else:
        fcmii_produtividade_geral = 0    

     ####################---------FCMIII --- MG01---------------###############################################
    fcmiii_mg01_hora_prod_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 18 ].groupby('EQUIPAMENTO_CODIGO')['HRPRO'].sum() #soma
    fcmiii_mg01_hora_prod_val = fcmiii_mg01_hora_prod_int.item() if not fcmiii_mg01_hora_prod_int.empty else 0   #conversão do series do panda para valor
    fcmiii_mg01_hora_prod = locale.format_string("%.1f",fcmiii_mg01_hora_prod_val,grouping=True) if fcmiii_mg01_hora_prod_val > 0 else 0

    fcmiii_mg01_hora_parado_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 18 ].groupby('EQUIPAMENTO_CODIGO')['HREVENTO'].sum()
    fcmiii_mg01_hora_parado_val = fcmiii_mg01_hora_parado_int.item() if not fcmiii_mg01_hora_parado_int.empty else 0
    fcmiii_mg01_hora_parado = locale.format_string("%.1f",fcmiii_mg01_hora_parado_val,grouping=True) if fcmiii_mg01_hora_parado_val > 0 else 0

    fcmiii_mg01_producao_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 18].groupby('EQUIPAMENTO_CODIGO')['QUANT'].sum()
    fcmiii_mg01_producao_val = fcmiii_mg01_producao_int.item() if not fcmiii_mg01_producao_int.empty else 0
    fcmiii_mg01_producao = locale.format_string("%.1f",fcmiii_mg01_producao_val,grouping=True) if fcmiii_mg01_producao_val > 0 else 0

    fcmiii_mg01_produtividade_val = 0
    if fcmiii_mg01_hora_prod_val > 0:
        fcmiii_mg01_produtividade_val = fcmiii_mg01_producao_val / fcmiii_mg01_hora_prod_val
        #fcmiii_mg01_produtividade = locale.format_string("%.1f",fcmiii_mg01_produtividade_val, grouping=True)
    else:
        fcmiii_mg01_produtividade= 0     

    ####################---------FCMIII --- MG02---------------###############################################  
    fcmiii_mg02_hora_prod_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 19 ].groupby('EQUIPAMENTO_CODIGO')['HRPRO'].sum() #soma
    fcmiii_mg02_hora_prod_val = fcmiii_mg02_hora_prod_int.item() if not fcmiii_mg02_hora_prod_int.empty else 0   #conversão do series do panda para valor
    fcmiii_mg02_hora_prod = locale.format_string("%.1f",fcmiii_mg02_hora_prod_val,grouping=True) if fcmiii_mg02_hora_prod_val > 0 else 0

    fcmiii_mg02_hora_parado_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 19 ].groupby('EQUIPAMENTO_CODIGO')['HREVENTO'].sum()
    fcmiii_mg02_hora_parado_val = fcmiii_mg02_hora_parado_int.item() if not fcmiii_mg02_hora_parado_int.empty else 0
    fcmiii_mg02_hora_parado = locale.format_string("%.1f",fcmiii_mg02_hora_parado_val,grouping=True) if fcmiii_mg02_hora_parado_val > 0 else 0

    fcmiii_mg02_producao_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 19].groupby('EQUIPAMENTO_CODIGO')['QUANT'].sum()
    fcmiii_mg02_producao_val = fcmiii_mg02_producao_int.item() if not fcmiii_mg02_producao_int.empty else 0
    fcmiii_mg02_producao = locale.format_string("%.1f",fcmiii_mg02_producao_val,grouping=True) if fcmiii_mg02_producao_val > 0 else 0

    fcmiii_mg02_produtividade_val = 0
    if fcmiii_mg02_hora_prod_val > 0:
        fcmiii_mg02_produtividade_val = fcmiii_mg02_producao_val / fcmiii_mg02_hora_prod_val
        #fcmiii_mg02_produtividade = locale.format_string("%.1f",fcmiii_mg02_produtividade_val, grouping=True)
    else:
        fcmiii_mg02_produtividade = 0 

     ####################---------FCMIII --- MG03---------------###############################################  
    fcmiii_mg03_hora_prod_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 20 ].groupby('EQUIPAMENTO_CODIGO')['HRPRO'].sum() #soma
    fcmiii_mg03_hora_prod_val = fcmiii_mg03_hora_prod_int.item() if not fcmiii_mg03_hora_prod_int.empty else 0   #conversão do series do panda para valor
    fcmiii_mg03_hora_prod = locale.format_string("%.1f",fcmiii_mg03_hora_prod_val,grouping=True) if fcmiii_mg03_hora_prod_val > 0 else 0

    fcmiii_mg03_hora_parado_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 20 ].groupby('EQUIPAMENTO_CODIGO')['HREVENTO'].sum()
    fcmiii_mg03_hora_parado_val = fcmiii_mg03_hora_parado_int.item() if not fcmiii_mg03_hora_parado_int.empty else 0
    fcmiii_mg03_hora_parado = locale.format_string("%.1f",fcmiii_mg03_hora_parado_val,grouping=True) if fcmiii_mg03_hora_parado_val > 0 else 0

    fcmiii_mg03_producao_int = consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 20 ].groupby('EQUIPAMENTO_CODIGO')['QUANT'].sum()
    fcmiii_mg03_producao_val = fcmiii_mg03_producao_int.item() if not fcmiii_mg03_producao_int.empty else 0
    fcmiii_mg03_producao = locale.format_string("%.1f",fcmiii_mg03_producao_val,grouping=True) if fcmiii_mg03_producao_val > 0 else 0

    fcmiii_mg03_produtividade_val =0
    if fcmiii_mg03_hora_prod_val > 0:
        fcmiii_mg03_produtividade_val = fcmiii_mg03_producao_val / fcmiii_mg03_hora_prod_val
        #fcmiii_mg03_produtividade = locale.format_string("%.1f",fcmiii_mg03_produtividade_val, grouping=True)
    else:
        fcmiii_mg03_produtividade = 0 

    fcmiii_produtividade_geral_val = 0
    if fcmiii_mg01_produtividade_val or fcmiii_mg02_produtividade_val or fcmiii_mg03_produtividade_val > 0 :
        fcmiii_produtividade_geral_val = (fcmiii_mg01_produtividade_val + fcmiii_mg02_produtividade_val + fcmiii_mg03_produtividade_val) / 3
        fcmiii_produtividade_geral = locale.format_string("%.1f",fcmiii_produtividade_geral_val,grouping=True)
    else:
        fcmiii_produtividade_geral = 0  

    fcmiii_producao_geral_val =   fcmiii_mg01_producao_val + fcmiii_mg02_producao_val  + fcmiii_mg03_producao_val
    fcmiii_producao_geral = locale.format_string("%.1f",fcmiii_producao_geral_val,grouping=True)  

    ##########------------------------TOTAIS DAS FABRICAS-------------------------------#############################
    if fcmi_producao_geral_val or fcmii_mg01_producao_val or fcmiii_producao_geral_val > 0 : 
        producao_geral_fabricas_val = fcmi_producao_geral_val + fcmii_mg01_producao_val + fcmiii_producao_geral_val   
        producao_geral_fabricas = locale.format_string("%.1f",producao_geral_fabricas_val, grouping=True)
    else:
        producao_geral_fabricas = 0    

    produtividade_geral_fabricas_val = 0
    if fcmi_produtividade_geral_val or fcmii_produtividade_geral_val or fcmiii_produtividade_geral_val > 0 :
        produtividade_geral_fabricas_val = (fcmi_produtividade_geral_val + fcmii_produtividade_geral_val + fcmiii_produtividade_geral_val) / 3
        produtividade_geral_fabricas = locale.format_string("%.1f",produtividade_geral_fabricas_val, grouping=True)
    else:
        produtividade_geral_fabricas = 0

##---------------------------------MOVIMENTAÇÃO DE CARGAS---------------------------------------------######        
    data = request.data.get('data')
    consulta_carregamento= pd.read_sql(f"""
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
        AND CAST (NFDATA as date) = '{data}' 
        AND ESTQCOD IN (1,4,5,104,37,2785)

    ORDER BY NFDATA, NFNUM
                 """,engine)

    #KPI'S
    total_carregamento = consulta_carregamento['QUANT'].sum()
    total_carregamento = locale.format_string("%.0f",total_carregamento, grouping=True)

##-------------------------------CONSULTA ESTOQUE CALCARIO--------------------------------------############
    data = request.data.get('data')
    consulta_estoque = pd.read_sql (f"""
        SELECT DISTINCT ESTQNOME, ESTQCOD, DADOS.DT DATA, EMPCOD EMPRESA, QESTQFIL FILIAL,
        QUANTESTOQUE, QUANTMOV, (QUANTESTOQUE - QUANTMOV) SALDO,
        ((QUANTESTOQUE * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000) QUANTESTOQUETN,
        ((QUANTMOV * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000) QUANTMOVTN,
        ((QUANTESTOQUE * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000) -
        ((QUANTMOV * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000) SALDOTN
        FROM (
            SELECT CAST('{data}' AS DATE) AS DT
            FROM master..spt_values
            WHERE type = 'P'
        ) DADOS
        JOIN ESTOQUE EQ ON 1=1  
        JOIN EMPRESA EE ON 1=1  
        JOIN GRUPOALMOXARIFADO G1 ON G1.GALMCOD = ESTQGALM
        LEFT OUTER JOIN GRUPOALMOXARIFADO G2 ON G2.GALMCOD = G1.GALMGALMPAI
        LEFT OUTER JOIN GRUPOALMOXARIFADO G3 ON G3.GALMCOD = G2.GALMGALMPAI
        LEFT OUTER JOIN GRUPOALMOXARIFADO G4 ON G4.GALMCOD = G3.GALMGALMPAI
        LEFT OUTER JOIN GRUPOALMOXARIFADO G5 ON G5.GALMCOD = G4.GALMGALMPAI
        LEFT OUTER JOIN GRUPOALMOXARIFADO G6 ON G6.GALMCOD = G5.GALMGALMPAI
        OUTER APPLY (SELECT QESTQFIL, COALESCE(SUM(QESTQESTOQUE),0) QUANTESTOQUE
                    FROM QUANTESTOQUE
                    WHERE QESTQESTQ = EQ.ESTQCOD AND QESTQEMP = EE.EMPCOD GROUP BY QESTQFIL) QESTQ
        OUTER APPLY (SELECT COALESCE(SUM(MESTQQUANT),0) QUANTMOV 
                    FROM MOVESTOQUE 
                    WHERE MESTQESTQ = EQ.ESTQCOD 
                    AND MESTQEMP = EE.EMPCOD AND MESTQFIL = QESTQ.QESTQFIL AND MESTQDATA > DADOS.DT) QUANTMOV
        -- Novo JOIN com MOVESTOQUE para verificar o movimento
        LEFT JOIN (
            SELECT MESTQESTQ, MESTQEMP, MESTQFIL, COUNT(*) AS MOVCOUNT
            FROM MOVESTOQUE
            WHERE MESTQREFTIPO < 10
            AND CAST(MESTQDATA AS DATE) = '{data}'
            GROUP BY MESTQESTQ, MESTQEMP, MESTQFIL
        ) MOV ON MOV.MESTQESTQ = EQ.ESTQCOD
            AND MOV.MESTQEMP = EE.EMPCOD 
            AND MOV.MESTQFIL = QESTQ.QESTQFIL

        WHERE EE.EMPCOD = 1
        AND COALESCE(QESTQFIL, 0) = 0 
        AND ESTQGALM = 1587
        AND ESTQCOD IN (1,2785)
        AND MOV.MOVCOUNT > 0 -- Usa o resultado do JOIN ao invés da subquery
        AND (SELECT COUNT(*) FROM GRUPOALMOXARIFADO WHERE GALMCOD = EQ.ESTQGALM AND GALMPRODVENDA = 'S') > 0  /*&PRODVENDA*/
        ORDER BY ESTQNOME, DATA;
                """,engine)
    
    estoque_total = 0
    estoque_total = consulta_estoque['SALDO'].sum()
    estoque_total = locale.format_string("%.0f",estoque_total,grouping=True)


    response_data = {
        ##-----------FCMI--MG01------------------------
        'fcmi_mg01_hora_producao': fcmi_mg01_hora_producao,
        'fcmi_mg01_hora_parado': fcmi_mg01_hora_parado,
        'fcmi_mg01_producao': fcmi_mg01_producao,
        'fcmi_mg01_produtividade': fcmi_mg01_produtividade,
        ##----------FCMI--MG02-----------------
        'fcmi_mg02_hora_producao': fcmi_mg02_hora_producao,
        'fcmi_mg02_hora_parado': fcmi_mg02_hora_parado,
        'fcmi_mg02_producao': fcmi_mg02_producao,
        'fcmi_mg02_produtividade': fcmi_mg02_produtividade,
        ##------------FCMI--GERAL---------------
         'fcmi_produtividade_geral': fcmi_produtividade_geral,
         'fcmi_producao_geral' : fcmi_producao_geral,
        ##-----------FCMII--MG01------------------------
         'fcmii_mg01_hora_prod': fcmii_mg01_hora_prod,
         'fcmii_mg01_hora_parado':fcmii_mg01_hora_parado,
         'fcmii_mg01_producao':fcmii_mg01_producao,
        ##------------FCMII--GERAL---------------
        'fcmii_produtividade_geral':fcmii_produtividade_geral,
        ##-----------FCMIII--MG01------------------------
        'fcmiii_mg01_hora_prod': fcmiii_mg01_hora_prod,
        'fcmiii_mg01_hora_parado':fcmiii_mg01_hora_parado,
        'fcmiii_mg01_producao': fcmiii_mg01_producao,
        ##-----------FCMIII--MG02------------------------
        'fcmiii_mg02_hora_prod': fcmiii_mg02_hora_prod,
        'fcmiii_mg02_hora_parado':fcmiii_mg02_hora_parado,
        'fcmiii_mg02_producao': fcmiii_mg02_producao,
        ##-----------FCMIII--MG03------------------------
        'fcmiii_mg03_hora_prod': fcmiii_mg03_hora_prod,
        'fcmiii_mg03_hora_parado':fcmiii_mg03_hora_parado,
        'fcmiii_mg03_producao': fcmiii_mg03_producao,
        ##-----------FCMIII--Totais------------------------
        'fcmiii_produtividade_geral': fcmiii_produtividade_geral,
        'fcmiii_producao_geral': fcmiii_producao_geral,
        ##-----------TOTAIS DAS FABRICAS--------------------------------
        'producao_geral_fabricas': producao_geral_fabricas,
        'produtividade_geral_fabricas': produtividade_geral_fabricas,
        ##-----------TOTAIS DO CARREGAMENTO--------------------------------
        'total_carregamento': total_carregamento,
        ##------------ESTOQUE--TOTAL--------------------------------
        'estoque_total': estoque_total
    }

    return JsonResponse(response_data,safe=False)

####----------------------------GRAFICOS CARREGAMENTO-------------------------------------###############
@csrf_exempt
@api_view(['POST'])
def calculos_calcario_graficos_carregamento(request):

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
    
    consulta_carregamento= pd.read_sql(f"""
        SELECT 
            CLINOME, 
            CLICOD, 
            TRANNOME, 
            TRANCOD, 
            NFPLACA, 
            ESTUF, 
            NFPED, 
            NFNUM, 
            SDSSERIE, 
            NFDATA, 
            INFQUANT,
            ESTQCOD, 
            ESTQNOME, 
            ESPSIGLA,
            ((INFQUANT * INFPESO) /1000) QUANT,
            (INFTOTAL / (NFTOTPRO + NFTOTSERV) * (NFTOTPRO + NFTOTSERV)) TOTAL_PRODUTO,
            INFLOC,  -- O local do item de pedido
            (INFTOTAL / (NFTOTPRO + NFTOTSERV) * NFTOTAL) TOTAL,
            INFDAFRETE FRETE
                FROM 
                    NOTAFISCAL
                JOIN 
                    SERIEDOCSAIDA ON SDSCOD = NFSNF
                JOIN 
                    NATUREZAOPERACAO ON NOPCOD = NFNOP
                JOIN 
                    CLIENTE ON CLICOD = NFCLI
                JOIN 
                    ITEMNOTAFISCAL ON INFNFCOD = NFCOD
                JOIN 
                    ESTOQUE ON ESTQCOD = INFESTQ
                JOIN 
                    ESPECIE ON ESPCOD = ESTQESP
                LEFT OUTER JOIN 
                    TRANSPORTADOR ON TRANCOD = NFTRAN
                LEFT OUTER JOIN 
                    PEDIDO ON PEDNUM = INFPED

                LEFT OUTER JOIN 
                    ESTADO ON ESTCOD = NFEST
                WHERE 
                    NFSIT = 1
                    AND NFSNF NOT IN (8) -- Serie Acerto
                    AND NFEMP = 1
                    AND NFFIL = 0
                    AND NOPFLAGNF LIKE '_S%'
                    AND CAST(NFDATA AS date)  BETWEEN '{data_inicio}' AND '{data_fim}' 
                    AND INFLOC IN (23,24,25)
                    AND ESTQCOD IN (1,4,5,104,37,2785)
                ORDER BY 
                    NFDATA, NFNUM
                 """,engine)
    
    # Inicializar variáveis
    volume_diario = None
    volume_mensal = None

    if 'NFDATA' in consulta_carregamento.columns:
        consulta_carregamento['NFDATA'] = pd.to_datetime(consulta_carregamento['NFDATA'],errors='coerce')
        consulta_carregamento = consulta_carregamento.dropna(subset=['NFDATA']) # remove as linhas onde a data é nula                 

     # Quebrando o cálculo mensal em dias
    if tipo_calculo == 'mensal':
        consulta_carregamento['DIA'] = consulta_carregamento['NFDATA'].dt.day

        #Função para preencher em caso de dias faltantes
        def preencher_dias_faltantes(volume_df):
            dias_completos = pd.DataFrame({'DIA': range(1, 32)})
            return dias_completos.merge(volume_df, on='DIA', how='left').fillna(0).infer_objects(copy=False)
        
        #calculo do volume acumulado das tres fabricas
        volume_diario_fcmi_df = consulta_carregamento[consulta_carregamento['INFLOC'] == 23].groupby('DIA')['INFQUANT'].sum().reset_index()
        volume_diario_fcmii_df = consulta_carregamento[consulta_carregamento['INFLOC'] == 24].groupby('DIA')['INFQUANT'].sum().reset_index()
        volume_diario_fcmiii_df = consulta_carregamento[consulta_carregamento['INFLOC'] == 25].groupby('DIA')['INFQUANT'].sum().reset_index()

        # Preencher dias faltantes com 0 para cada fábrica
        volume_diario_fcmi_df = preencher_dias_faltantes(volume_diario_fcmi_df)
        volume_diario_fcmii_df = preencher_dias_faltantes(volume_diario_fcmii_df)
        volume_diario_fcmiii_df = preencher_dias_faltantes(volume_diario_fcmiii_df)

        #médias diárias
        media_diaria_fcmi = volume_diario_fcmi_df['INFQUANT'].mean()
        media_diaria_fcmi = locale.format_string("%.0f",media_diaria_fcmi, grouping=True)

        media_diaria_fcmii = volume_diario_fcmii_df['INFQUANT'].mean()
        media_diaria_fcmii = locale.format_string("%.0f",media_diaria_fcmii, grouping=True)

        media_diaria_fcmiii = volume_diario_fcmiii_df['INFQUANT'].mean()
        media_diaria_fcmiii = locale.format_string("%.0f",media_diaria_fcmiii, grouping=True)

        # Somando os volumes diários de todas as fábricas
        volume_diario_total = volume_diario_fcmi_df['INFQUANT'].sum() + volume_diario_fcmii_df['INFQUANT'].sum() + volume_diario_fcmiii_df['INFQUANT'].sum()

       # Obter o dia atual
        hoje = datetime.now().day -1

        # Calculando a média agregada de todas as fábricas
        if hoje > 0:
            media_diaria_agregada = volume_diario_total / hoje
            media_diaria_agregada = locale.format_string("%.0f", media_diaria_agregada, grouping=True)
        else:
            media_diaria_agregada = 0

         # Calculando projeção
        dias_corridos = consulta_carregamento['DIA'].max()  # Último dia do mês em que houve produção
        dias_no_mes = (consulta_carregamento['NFDATA'].max().replace(day=1) + pd.DateOffset(months=1) - pd.DateOffset(days=1)).day

        if dias_corridos > 0:
            volume_ultimo_dia_fcmi = consulta_carregamento[(consulta_carregamento['INFLOC'] == 23) & (consulta_carregamento['DIA'] == dias_corridos)]
            volume_ultimo_dia_fcmii = consulta_carregamento[(consulta_carregamento['INFLOC'] == 24) & (consulta_carregamento['DIA'] == dias_corridos)]
            volume_ultimo_dia_fcmiii = consulta_carregamento[(consulta_carregamento['INFLOC'] == 25) & (consulta_carregamento['DIA'] == dias_corridos)]
            
            #volume total
            volume_ultimo_dia_total_fcmi = volume_ultimo_dia_fcmi['INFQUANT'].sum()
            volume_ultimo_dia_total_fcmii = volume_ultimo_dia_fcmii['INFQUANT'].sum()
            volume_ultimo_dia_total_fcmiii = volume_ultimo_dia_fcmiii['INFQUANT'].sum()

            volume_ultimo_dia_total = volume_ultimo_dia_total_fcmi + volume_ultimo_dia_total_fcmii + volume_ultimo_dia_total_fcmiii
            volume_ultimo_dia_total = locale.format_string("%.0f",volume_ultimo_dia_total, grouping=True)
                
            #PROJEÇÂO
            producao_acumulada_fcmi = volume_diario_fcmi_df['INFQUANT'].sum()
            projecao_fcmi = (producao_acumulada_fcmi / dias_corridos) * dias_no_mes
            projecao_fcmi = locale.format_string("%.0f", projecao_fcmi, grouping=True)

            producao_acumulada_fcmii = volume_diario_fcmii_df['INFQUANT'].sum()
            projecao_fcmii = (producao_acumulada_fcmii / dias_corridos) * dias_no_mes
            projecao_fcmii = locale.format_string("%.0f", projecao_fcmii, grouping=True)

            producao_acumulada_fcmiii = volume_diario_fcmiii_df['INFQUANT'].sum()
            projecao_fcmiii = (producao_acumulada_fcmiii / dias_corridos) * dias_no_mes
            projecao_fcmiii = locale.format_string("%.0f", projecao_fcmiii, grouping=True)
        else:
            projecao_fcmi = 0
            projecao_fcmii = 0
            projecao_fcmiii = 0

        producao_acumulada_total = producao_acumulada_fcmi + producao_acumulada_fcmii + producao_acumulada_fcmiii
        # Projeção anual agregada
        if dias_corridos > 0:
            projecao_total = (producao_acumulada_total /dias_corridos) * dias_no_mes
            projecao_total = locale.format_string("%.0f", projecao_total, grouping=True)
        else:
            projecao_total = 0        
            
        volume_diario = {
            'volume_ultimo_dia_total_fcmi':volume_ultimo_dia_total_fcmi,
            'volume_ultimo_dia_total_fcmii': volume_ultimo_dia_total_fcmii,
            'volume_ultimo_dia_total_fcmiii':volume_ultimo_dia_total_fcmiii,
            'projecao_fcmi':projecao_fcmi,
            'projecao_fcmii':projecao_fcmii,
            'projecao_fcmiii':projecao_fcmiii,
            'media_diaria_fcmi': media_diaria_fcmi,
            'media_diaria_fcmii': media_diaria_fcmii,
            'media_diaria_fcmiii': media_diaria_fcmiii,
            'volume_ultimo_dia_total': volume_ultimo_dia_total,
            'media_diaria_agregada': media_diaria_agregada,
            'projecao_total': projecao_total,
            'volume_diario_total': volume_diario_total,
            'fcmi': volume_diario_fcmi_df.to_dict(orient='records'),
            'fcmii': volume_diario_fcmii_df.to_dict(orient='records'),
            'fcmiii': volume_diario_fcmiii_df.to_dict(orient='records'),
        }

    elif tipo_calculo == 'anual':
        consulta_carregamento['MES'] = consulta_carregamento['NFDATA'].dt.month

        # Função para preencher os meses faltantes com 0
        def preencher_meses_faltantes(volume_df):
            meses_completos = pd.DataFrame({'MES': range(1, 13)})
            return meses_completos.merge(volume_df, on='MES', how='left').fillna(0).infer_objects(copy=False)
        #calculo do volume acumulado das tres fabricas
        volume_mensal_fcmi_df = consulta_carregamento[consulta_carregamento['INFLOC'] == 23].groupby('MES')['INFQUANT'].sum().reset_index()
        volume_mensal_fcmii_df = consulta_carregamento[consulta_carregamento['INFLOC'] == 24].groupby('MES')['INFQUANT'].sum().reset_index()
        volume_mensal_fcmiii_df = consulta_carregamento[consulta_carregamento['INFLOC'] == 25].groupby('MES')['INFQUANT'].sum().reset_index()
    
         # Preencher meses faltantes com 0 para cada fábrica
        volume_mensal_fcmi_df = preencher_meses_faltantes(volume_mensal_fcmi_df)
        volume_mensal_fcmii_df = preencher_meses_faltantes(volume_mensal_fcmii_df)
        volume_mensal_fcmiii_df = preencher_meses_faltantes(volume_mensal_fcmiii_df)

        # Pegando o mês atual (corridos)
        mes_corrente = datetime.now().month

        # Somar o volume mensal sem incluir os meses futuros
        volume_mensal_fcmi_df_filtrado = volume_mensal_fcmi_df[volume_mensal_fcmi_df['MES'] <= mes_corrente]
        volume_mensal_fcmii_df_filtrado = volume_mensal_fcmii_df[volume_mensal_fcmii_df['MES'] <= mes_corrente]
        volume_mensal_fcmiii_df_filtrado = volume_mensal_fcmiii_df[volume_mensal_fcmiii_df['MES'] <= mes_corrente]

        # Médias mensais baseadas nos meses já passados
        media_mensal_fcmi = volume_mensal_fcmi_df_filtrado['INFQUANT'].sum() / mes_corrente
        media_mensal_fcmi = locale.format_string("%.0f", media_mensal_fcmi, grouping=True)

        media_mensal_fcmii = volume_mensal_fcmii_df_filtrado['INFQUANT'].sum() / mes_corrente
        media_mensal_fcmii = locale.format_string("%.0f", media_mensal_fcmii, grouping=True)

        media_mensal_fcmiii = volume_mensal_fcmiii_df_filtrado['INFQUANT'].sum() / mes_corrente
        media_mensal_fcmiii = locale.format_string("%.0f", media_mensal_fcmiii, grouping=True)

        # Somando os volumes mensais de todas as fábricas
        volume_mensal_total = volume_mensal_fcmi_df['INFQUANT'].sum() + volume_mensal_fcmii_df['INFQUANT'].sum() + volume_mensal_fcmiii_df['INFQUANT'].sum()

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
            volume_ultimo_mes_fcmi = consulta_carregamento[(consulta_carregamento['INFLOC'] == 23) & (consulta_carregamento['MES'] == meses_corridos)]
            volume_ultimo_mes_fcmii = consulta_carregamento[(consulta_carregamento['INFLOC'] == 24) & (consulta_carregamento['MES'] == meses_corridos)]
            volume_ultimo_mes_fcmiii = consulta_carregamento[(consulta_carregamento['INFLOC'] == 25) & (consulta_carregamento['MES'] == meses_corridos)]
            
            #volume total
            volume_ultimo_mes_total_fcmi = volume_ultimo_mes_fcmi['INFQUANT'].sum()
            volume_ultimo_mes_total_fcmii = volume_ultimo_mes_fcmii['INFQUANT'].sum()
            volume_ultimo_mes_total_fcmiii = volume_ultimo_mes_fcmiii['INFQUANT'].sum()

            volume_ultimo_mes_total = volume_ultimo_mes_total_fcmi + volume_ultimo_mes_total_fcmii + volume_ultimo_mes_total_fcmiii
            volume_ultimo_mes_total = locale.format_string("%.0f",volume_ultimo_mes_total, grouping=True)
                
            #PROJEÇÂO
            producao_mensal_acumulada_fcmi = volume_mensal_fcmi_df['INFQUANT'].sum()
            projecao_anual_fcmi = (producao_mensal_acumulada_fcmi / meses_corridos) * meses_no_ano
            projecao_anual_fcmi = locale.format_string("%.0f", projecao_anual_fcmi, grouping=True)

            producao_mensal_acumulada_fcmii = volume_mensal_fcmii_df['INFQUANT'].sum()
            projecao_anual_fcmii = (producao_mensal_acumulada_fcmii / meses_corridos) * meses_no_ano
            projecao_anual_fcmii = locale.format_string("%.0f", projecao_anual_fcmii, grouping=True)

            producao_mensal_acumulada_fcmiii = volume_mensal_fcmiii_df['INFQUANT'].sum()
            projecao_anual_fcmiii = (producao_mensal_acumulada_fcmiii / meses_corridos) * meses_no_ano
            projecao_anual_fcmiii = locale.format_string("%.0f", projecao_anual_fcmiii, grouping=True)
         
        else:
            projecao_anual_fcmi = 0
            projecao_anual_fcmii = 0
            projecao_anual_fcmiii = 0

        producao_mensal_acumulada_total = producao_mensal_acumulada_fcmi + producao_mensal_acumulada_fcmii + producao_mensal_acumulada_fcmiii
        # Projeção anual agregada
        if meses_corridos > 0:
            projecao_anual_total = (producao_mensal_acumulada_total / meses_corridos) * meses_no_ano
            projecao_anual_total = locale.format_string("%.0f", projecao_anual_total, grouping=True)
        else:
            projecao_anual_total = 0    

        volume_mensal = {
            'projecao_anual_fcmi':projecao_anual_fcmi,
            'projecao_anual_fcmii':projecao_anual_fcmii,
            'projecao_anual_fcmiii':projecao_anual_fcmiii,
            'media_mensal_fcmi': media_mensal_fcmi,
            'media_mensal_fcmii': media_mensal_fcmii,
            'media_mensal_fcmiii': media_mensal_fcmiii,
            'volume_ultimo_mes_total': volume_ultimo_mes_total,
            'media_mensal_agregada': media_mensal_agregada,
            'projecao_anual_total': projecao_anual_total,
            'fcmi': volume_mensal_fcmi_df.to_dict(orient='records'),
            'fcmii': volume_mensal_fcmii_df.to_dict(orient='records'),
            'fcmiii': volume_mensal_fcmiii_df.to_dict(orient='records'),
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