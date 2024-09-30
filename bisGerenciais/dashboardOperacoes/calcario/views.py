from datetime import datetime, timedelta  # Importa as classes necessárias
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
import pandas as pd
import locale
from sqlalchemy import create_engine

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
        data_inicio = datetime.now().strftime('%Y-%m-01 00:00:00')  # Início do mês
        data_fim = datetime.now().strftime('%Y-%m-%d 23:59:59')  # Data atual
    elif tipo_calculo == 'anual':
        data_inicio = datetime.now().strftime('%Y-01-01 00:00:00')  # Início do ano
        data_fim = datetime.now().strftime('%Y-%m-%d 23:59:59')  # Data atual
    else:
        return JsonResponse({'error': 'Tipo de cálculo inválido'}, status=400)

    consulta_fcm = pd.read_sql(f"""

            SELECT BPROCOD, BPRODATA, ESTQCOD, ESTQNOMECOMP,BPROEQP,BPROHRPROD,BPROHROPER,BPROFPROQUANT,BPROFPRO,
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
        AND CAST (NFDATA as date) BETWEEN '{data_inicio}' AND '{data_fim}'
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
        data_inicio = datetime.now().strftime('%Y-%m-01 00:00:00')  # Início do mês
        data_fim = datetime.now().strftime('%Y-%m-%d 23:59:59')  # Data atual
    elif tipo_calculo == 'anual':
        data_inicio = datetime.now().strftime('%Y-01-01 00:00:00')  # Início do ano
        data_fim = datetime.now().strftime('%Y-%m-%d 23:59:59')  # Data atual
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
            return dias_completos.merge(volume_df, on='DIA', how='left').fillna(0)

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
        volume_diario_total = volume_diario_fcmi_df['PESO'].sum() + volume_diario_fcmii_df['PESO'].sum() + volume_diario_fcmiii_df['PESO'].sum()

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
            return meses_completos.merge(volume_df, on='MES', how='left').fillna(0)

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