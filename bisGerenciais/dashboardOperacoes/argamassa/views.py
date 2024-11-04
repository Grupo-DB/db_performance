from datetime import datetime, timedelta
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
from sqlalchemy import create_engine
import pandas as pd
import locale

locale.setlocale(locale.LC_ALL,'pt_BR.UTF-8')

connection_string = 'mssql+pyodbc://DBCONSULTA:DB%40%402023**@172.50.10.5/DB?driver=ODBC+Driver+17+for+SQL+Server'
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['POST'])
def calculos_argamassa(request):
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
    
#-------------------------TOTAL DO CARREGAMENTO --------------------------------------------###############
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
            AND ESTQCOD IN (
                2728, 22089, 2708, 2709, 2710, 2730, 23987, 23988, 23989, 24021, 24022, 24023, 24019, 
                24020, 24024, 2715, 2716, 2711, 2714, 24222, 2717, 2718, 25878, 25877, 2719, 2729
                )
        ORDER BY NFDATA, NFNUM
                    """,engine)
       #KPI´S
    total_movimentacao = consulta_movimentacao['QUANT'].sum()
    total_movimentacao = locale.format_string("%.0f",total_movimentacao, grouping=True)

    response_data = {
            'total_movimentacao': total_movimentacao,
        }
    return JsonResponse(response_data, safe=False)
#---------------------------------CONSULTA ARGAMASSA ---------------------------#########
@csrf_exempt
@api_view(['POST'])
def calculos_argamassa_produtos(request):
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
    produto = request.data.get('produto')
    consulta_argamassa = pd.read_sql(f"""
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
                AND ESTQCOD <> 5594

                ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD
            """,engine)
    #KPIs
    producao_total = consulta_argamassa['PESO'].sum()
    producao_total = int(producao_total)
    producao_total = locale.format_string("%.0f",producao_total,grouping=True)

    ensacado_total = consulta_argamassa['IBPROQUANT'].sum()
    ensacado_total = int(ensacado_total)
    ensacado_total = locale.format_string("%.0f",ensacado_total, grouping=True)

    concrecal_cimento_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2728].groupby('ESTQCOD')['IBPROQUANT'].sum()
    concrecal_cimento_val = concrecal_cimento_int.item() if not concrecal_cimento_int.empty else 0
    concrecal_cimento_quant = locale.format_string("%.0f",concrecal_cimento_val,grouping=True) if concrecal_cimento_val > 0 else 0

    arg_assent_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 22089].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_assent_val = arg_assent_int.item() if not arg_assent_int.empty else 0
    arg_assent_quant = locale.format_string("%.0f",arg_assent_val,grouping=True) if arg_assent_val > 0 else 0

    arg_colante_ac1_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2708].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_colante_ac1_val = arg_colante_ac1_int.item() if not arg_colante_ac1_int.empty else 0
    arg_colante_ac1_quant = locale.format_string("%.0f",arg_colante_ac1_val,grouping=True) if arg_colante_ac1_val > 0 else 0

    arg_colante_ac2_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2709].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_colante_ac2_val = arg_colante_ac2_int.item() if not arg_colante_ac2_int.empty else 0
    arg_colante_ac2_quant = locale.format_string("%.0f",arg_colante_ac2_val,grouping=True) if arg_colante_ac2_val > 0 else 0

    arg_colante_ac3_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2710].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_colante_ac3_val = arg_colante_ac3_int.item() if not arg_colante_ac3_int.empty else 0
    arg_colante_ac3_quant = locale.format_string("%.0f",arg_colante_ac3_val,grouping=True) if arg_colante_ac3_val > 0 else 0

    arg_projecao_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2730].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_projecao_val = arg_projecao_int.item() if not arg_projecao_int.empty else 0
    arg_projecao_quant = locale.format_string("%.0f",arg_projecao_val,grouping=True) if arg_projecao_val > 0 else 0

    arg_rev_arv1_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 23987].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_rev_arv1_val = arg_rev_arv1_int.item() if not arg_rev_arv1_int.empty else 0
    arg_rev_arv1_quant = locale.format_string("%.0f",arg_rev_arv1_val,grouping=True) if arg_rev_arv1_val > 0 else 0

    arg_rev_arv2_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 23988].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_rev_arv2_val = arg_rev_arv2_int.item() if not arg_rev_arv2_int.empty else 0
    arg_rev_arv2_quant = locale.format_string("%.0f",arg_rev_arv2_val,grouping=True) if arg_rev_arv2_val > 0 else 0

    arg_rev_arv3_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 23989].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_rev_arv3_val = arg_rev_arv3_int.item() if not arg_rev_arv3_int.empty else 0
    arg_rev_arv3_quant = locale.format_string("%.0f",arg_rev_arv3_val,grouping=True) if arg_rev_arv3_val > 0 else 0

    arg_est_aae12_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24021].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae12_val = arg_est_aae12_int.item() if not arg_est_aae12_int.empty else 0
    arg_est_aae12_quant = locale.format_string("%.0f",arg_est_aae12_val,grouping=True) if arg_est_aae12_val > 0 else 0

    arg_est_aae16_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24022].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae16_val = arg_est_aae16_int.item() if not arg_est_aae16_int.empty else 0
    arg_est_aae16_quant = locale.format_string("%.0f",arg_est_aae16_val,grouping=True) if arg_est_aae16_val > 0 else 0

    arg_est_aae20_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24023].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae20_val = arg_est_aae20_int.item() if not arg_est_aae20_int.empty else 0
    arg_est_aae20_quant = locale.format_string("%.0f",arg_est_aae20_val,grouping=True) if arg_est_aae20_val > 0 else 0

    arg_est_aae5_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24019].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae5_val = arg_est_aae5_int.item() if not arg_est_aae5_int.empty else 0
    arg_est_aae5_quant = locale.format_string("%.0f",arg_est_aae5_val,grouping=True) if arg_est_aae5_val > 0 else 0

    arg_est_aae8_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24020].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae8_val = arg_est_aae8_int.item() if not arg_est_aae8_int.empty else 0
    arg_est_aae8_quant = locale.format_string("%.0f",arg_est_aae8_val,grouping=True) if arg_est_aae8_val > 0 else 0

    arg_est_aae_esp_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24024].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae_esp_val = arg_est_aae_esp_int.item() if not arg_est_aae_esp_int.empty else 0
    arg_est_aae_esp_quant = locale.format_string("%.0f",arg_est_aae_esp_val,grouping=True) if arg_est_aae_esp_val > 0 else 0

    arg_grossa_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2715].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_grossa_val = arg_grossa_int.item() if not arg_grossa_int.empty else 0
    arg_grossa_quant = locale.format_string("%.0f",arg_grossa_val,grouping=True) if arg_grossa_val > 0 else 0  

    arg_grossa_fibra_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2716].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_grossa_fibra_val = arg_grossa_fibra_int.item() if not arg_grossa_fibra_int.empty else 0
    arg_grossa_fibra_quant = locale.format_string("%.0f",arg_grossa_fibra_val,grouping=True) if arg_grossa_fibra_val > 0 else 0 

    arg_media_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2711].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_media_val = arg_media_int.item() if not arg_media_int.empty else 0
    arg_media_quant = locale.format_string("%.0f",arg_media_val,grouping=True) if arg_media_val > 0 else 0 

    arg_media_fibra_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2714].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_media_fibra_val = arg_media_fibra_int.item() if not arg_media_fibra_int.empty else 0
    arg_media_fibra_quant = locale.format_string("%.0f",arg_media_fibra_val,grouping=True) if arg_media_fibra_val > 0 else 0 

    arg_mult_uso_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24222].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_mult_uso_val = arg_mult_uso_int.item() if not arg_mult_uso_int.empty else 0
    arg_mult_uso_quant = locale.format_string("%.0f",arg_mult_uso_val,grouping=True) if arg_mult_uso_val > 0 else 0

    arg_piso_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2717].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_piso_val = arg_piso_int.item() if not arg_piso_int.empty else 0
    arg_piso_quant = locale.format_string("%.0f",arg_piso_val,grouping=True) if arg_piso_val > 0 else 0   

    arg_piso_eva_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2718].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_piso_eva_val = arg_piso_eva_int.item() if not arg_piso_eva_int.empty else 0
    arg_piso_eva_quant = locale.format_string("%.0f",arg_piso_eva_val,grouping=True) if arg_piso_eva_val > 0 else 0

    arg_contrapiso_10mpa_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 25878].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_contrapiso_10mpa_val = arg_contrapiso_10mpa_int.item() if not arg_contrapiso_10mpa_int.empty else 0
    arg_contrapiso_10mpa_quant = locale.format_string("%.0f",arg_contrapiso_10mpa_val,grouping=True) if arg_contrapiso_10mpa_val > 0 else 0  

    arg_contrapiso_5mpa_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 25877].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_contrapiso_5mpa_val = arg_contrapiso_5mpa_int.item() if not arg_contrapiso_5mpa_int.empty else 0
    arg_contrapiso_5mpa_quant = locale.format_string("%.0f",arg_contrapiso_5mpa_val,grouping=True) if arg_contrapiso_5mpa_val > 0 else 0

    massa_fina_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2719].groupby('ESTQCOD')['IBPROQUANT'].sum()
    massa_fina_val = massa_fina_int.item() if not massa_fina_int.empty else 0
    massa_fina_quant = locale.format_string("%.0f",massa_fina_val,grouping=True) if massa_fina_val > 0 else 0  

    multichapisco_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2729].groupby('ESTQCOD')['IBPROQUANT'].sum()
    multichapisco_val = multichapisco_int.item() if not multichapisco_int.empty else 0
    multichapisco_quant = locale.format_string("%.0f",multichapisco_val,grouping=True) if multichapisco_val > 0 else 0 

    response_data = {
        'concrecal_cimento':concrecal_cimento_quant,
        'argamassa_assentamento':arg_assent_quant,
        'arg_colante_ac1':arg_colante_ac1_quant,
        'arg_colante_ac2':arg_colante_ac2_quant,
        'arg_colante_ac3':arg_colante_ac3_quant,
        'arg_projecao':arg_projecao_quant,
        'arg_rev_arv1':arg_rev_arv1_quant,
        'arg_rev_arv2':arg_rev_arv2_quant,
        'arg_rev_arv3':arg_rev_arv3_quant,
        'arg_est_aae12':arg_est_aae12_quant,
        'arg_est_aae16':arg_est_aae16_quant,
        'arg_est_aae20':arg_est_aae20_quant,
        'arg_est_aae5':arg_est_aae5_quant,
        'arg_est_aae8':arg_est_aae8_quant,
        'arg_est_aae_esp':arg_est_aae_esp_quant,
        'arg_grossa':arg_grossa_quant,
        'arg_grossa_fibra':arg_grossa_fibra_quant,
        'arg_media':arg_media_quant,
        'arg_media_fibra':arg_media_fibra_quant,
        'arg_mult_uso': arg_mult_uso_quant,
        'arg_piso':arg_piso_quant,
        'arg_piso_eva':arg_piso_eva_quant,
        'arg_contrapiso_10mpa': arg_contrapiso_10mpa_quant,
        'arg_contrapiso_5mpa':arg_contrapiso_5mpa_quant,
        'massa_fina':massa_fina_quant,
        'multichapisco':multichapisco_quant,
        #-----------TOTAIS--------------------------------####
        'producao_total':producao_total,
        'ensacado_total': ensacado_total,
    }
    return JsonResponse(response_data, safe=False)

#---------------------------------CONSULTA ARGAMASSA PRODUTOINDIVIDUAL ---------------------------#########
@csrf_exempt
@api_view(['POST'])
def calculos_argamassa_produto_individual(request):
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
    produto = request.data.get('produto')
    consulta_argamassa_produto = pd.read_sql(f"""
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
                AND BPROEP = 1
                AND ESTQCOD = '{produto}'

                ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD
            """,engine)
    #KPIs

    produto_int = consulta_argamassa_produto['IBPROQUANT'].sum()
    #produto_val = produto_int.item() if not produto_int.empty else 0
    produto_quant = locale.format_string("%.0f",produto_int,grouping=True) if produto_int > 0 else 0


    response_data = {
        'produto':produto_quant,
    }
    return JsonResponse(response_data, safe=False)


    ###---------------------------------CONSULTA EQUIPAMENTOS --------------------##########
@csrf_exempt
@api_view(['POST'])
def calculos_argamassa_equipamentos(request):
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
        AND BPROEP = 1
        AND BPROEQP IN (264,265)
        ORDER BY BPRO.BPROCOD

        """,engine)
    #ARG MH-01
    mh01_hora_producao_int =  consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 264 ].groupby('EQUIPAMENTO_CODIGO')['HRPRO'].sum()
    mh01_hora_producao_val = mh01_hora_producao_int.item() if not mh01_hora_producao_int.empty else 0
    mh01_hora_producao_quant = locale.format_string("%.0f",mh01_hora_producao_val,grouping=True) if mh01_hora_producao_val > 0 else 0

    mh01_hora_parado_int =  consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 264 ].groupby('EQUIPAMENTO_CODIGO')['HREVENTO'].sum()
    mh01_hora_parado_val = mh01_hora_parado_int.item() if not mh01_hora_parado_int.empty else 0
    mh01_hora_parado_quant = locale.format_string("%.0f",mh01_hora_parado_val,grouping=True) if mh01_hora_parado_val > 0 else 0

    mh01_producao_int =  consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 264 ].groupby('EQUIPAMENTO_CODIGO')['QUANT'].sum()
    mh01_producao_val = mh01_producao_int.item() if not mh01_producao_int.empty else 0
    mh01_producao_quant = locale.format_string("%.0f",mh01_producao_val,grouping=True) if mh01_producao_val > 0 else 0

    mh01_produtividade_val = 0 
    if mh01_hora_producao_val > 0:
        mh01_produtividade_val = mh01_producao_val / mh01_hora_producao_val
        mh01_produtividade = locale.format_string("%.0f",mh01_produtividade_val, grouping=True)
    else:
        mh01_produtividade = 0 

    #ARG - MH02
    mh02_hora_producao_int =  consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 265 ].groupby('EQUIPAMENTO_CODIGO')['HRPRO'].sum()
    mh02_hora_producao_val = mh02_hora_producao_int.item() if not mh02_hora_producao_int.empty else 0
    mh02_hora_producao_quant = locale.format_string("%.0f",mh02_hora_producao_val,grouping=True) if mh02_hora_producao_val > 0 else 0

    mh02_hora_parado_int =  consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 265 ].groupby('EQUIPAMENTO_CODIGO')['HREVENTO'].sum()
    mh02_hora_parado_val = mh01_hora_parado_int.item() if not mh02_hora_parado_int.empty else 0
    mh02_hora_parado_quant = locale.format_string("%.0f",mh02_hora_parado_val,grouping=True) if mh02_hora_parado_val > 0 else 0

    mh02_producao_int =  consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 265 ].groupby('EQUIPAMENTO_CODIGO')['QUANT'].sum()
    mh02_producao_val = mh02_producao_int.item() if not mh02_producao_int.empty else 0
    mh02_producao_quant = locale.format_string("%.0f",mh02_producao_val,grouping=True) if mh02_producao_val > 0 else 0

    mh02_produtividade_val = 0 
    if mh01_hora_producao_val > 0:
        mh02_produtividade_val = mh02_producao_val / mh02_hora_producao_val
        mh02_produtividade = locale.format_string("%.0f",mh02_produtividade_val, grouping=True)
    else:
        mh02_produtividade = 0

    response_data = {
            'mh01_hora_producao':mh01_hora_producao_quant,
            'mh01_hora_parado':mh01_hora_parado_quant,
            'mh01_producao':mh01_producao_quant,
            'mh01_produtividade':mh01_produtividade,
            'mh02_hora_producao':mh02_hora_producao_quant,
            'mh02_hora_parado':mh02_hora_parado_quant,
            'mh02_producao':mh02_producao_quant,
            'mh02_produtividade':mh02_produtividade,
        }

    return JsonResponse (response_data, safe=False)            
##############-----------------------------------CALCULAR GRÀFICOS ARGAMASSA------------------------------------####
@csrf_exempt
@api_view(['POST'])
def calculos_argamassa_graficos(request):

    # Recuperando o tipo de cálculo do corpo da requisição
    tipo_calculo = request.data.get('tipo_calculo')
    etapa = request.data.get('etapa')
    produto = request.data.get('produto')
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
    
    
    consulta_argamassa = pd.read_sql(f"""
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
                AND BPROEP = 1
                AND ESTQCOD = '{produto}'
                ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD
            """,engine)
    # Inicializar variáveis
    volume_diario = None
    volume_mensal = None

    if 'BPRODATA' in consulta_argamassa.columns:
        consulta_argamassa['BPRODATA'] = pd.to_datetime(consulta_argamassa['BPRODATA'],errors='coerce')
        consulta_argamassa = consulta_argamassa.dropna(subset=['BPRODATA']) # remove as linhas onde a data é nula

     # Quebrando o cálculo mensal em dias
    if tipo_calculo == 'mensal':
        consulta_argamassa['DIA'] = consulta_argamassa['BPRODATA'].dt.day
        #Função para preencher em caso de dias faltantes
        def preencher_dias_faltantes(volume_df):
            dias_completos = pd.DataFrame({'DIA': range(1, 32)})
            return dias_completos.merge(volume_df, on='DIA', how='left').fillna(0)
        
        #calculo do volume acumulado dos ensacados
        volume_diario_df = consulta_argamassa[consulta_argamassa['ESTQCOD'] == produto].groupby('DIA')['PESO'].sum().reset_index()
        
        #Preencher dias Faltantes
        volume_diario_df = preencher_dias_faltantes(volume_diario_df)

        #MediasDiarias
        media_diaria = volume_diario_df['PESO'].mean()
        media_diaria = locale.format_string("%.0f",media_diaria,grouping=True)

        #volume Total
        volume_diario_total = int(volume_diario_df['PESO'].sum())
        #data Atual 
        hoje = datetime.now().day -1

        # Calculo média agregada todos os produtos
        if hoje > 0 :
            media_diaria_agregada = volume_diario_total / hoje
            media_diaria_agregada = locale.format_string("%.0f",media_diaria_agregada,grouping=True)
        else:
            media_diaria_agregada = 0

        #CAlculo de projeção
        dias_corridos = consulta_argamassa['DIA'].max()  #último dia no mes que teve produção
        dias_no_mes = (consulta_argamassa['BPRODATA'].max().replace(day=1) + pd.DateOffset(months=1) - pd.DateOffset(days=1)).day        

        if dias_corridos > 0 :
            volume_ultimo_dia = consulta_argamassa[consulta_argamassa['ESTQCOD'] == produto & (consulta_argamassa['DIA'] == dias_corridos )]

            #Volume total
            volume_ultimo_dia_total = int(volume_ultimo_dia['PESO'].sum())
            volume_ultimo_dia_total = locale.format_string("%.0f",volume_ultimo_dia_total,grouping=True)

            #PROJEÇÂO
            producao_acumulada = volume_diario_df['PESO'].sum()
            projecao = (producao_acumulada / dias_corridos) * dias_no_mes
            
            projecao = locale.format_string("%.0f",projecao,grouping=True)

        else :
            projecao = 0
            volume_ultimo_dia_total = 0
        

        volume_diario = {
            #----------VOLUMES ULTIMO DIA-----------------------#
           # 'volume_ultimo_dia_total': volume_ultimo_dia_total,
            #------------------PROJEÇÕES--------------------------------#
          #  'projecao': projecao,
            #----------------MEDIAS----------------------------------#
            'media_diaria': media_diaria,
            'media_diaria_agregada': media_diaria_agregada,
            #---------------VOLUME TOTAL---------------#
            
            'volume_diario_total': volume_diario_total,
            #-----------------INDIVIDUAIS-----------------------#
            'produto': volume_diario_df.to_dict(orient='records'),

        }
       
    elif tipo_calculo == 'anual':
        consulta_argamassa['MES'] = consulta_argamassa['BPRODATA'].dt.month

        # Função para preencher os meses faltantes com 0
        def preencher_meses_faltantes(volume_df):
            meses_completos = pd.DataFrame({'MES': range(1, 13)})
            return meses_completos.merge(volume_df, on='MES', how='left').fillna(0)
        
        #calculo do volume acumulado dos ensacados
        volume_mensal_df = consulta_argamassa[consulta_argamassa['ESTQCOD'] == produto].groupby('MES')['PESO'].sum().reset_index()
       
        #Preencher dias Faltantes
        volume_mensal_df = preencher_meses_faltantes(volume_mensal_df)

        # Pegando o mês atual (corridos)
        mes_corrente = datetime.now().month

        # Somar o volume mensal sem incluir os meses futuros
        volume_mensal_df_filtrado = volume_mensal_df[volume_mensal_df['MES'] <= mes_corrente]
        
        # Médias mensais baseadas nos meses já passados
        media_mensal = volume_mensal_df_filtrado['PESO'].sum() / mes_corrente
        media_mensal = locale.format_string("%.0f", media_mensal, grouping=True)

        # Calculando o número total de entradas (dias de produção)
        mes = datetime.now().month


        # Calculando projeção
        #meses_corridos = consulta_fcm['MES'].max()  # Último dia do mês em que houve produção
        meses_corridos = datetime.now().month
        meses_no_ano = 12

        if meses_corridos > 0 :
            volume_ultimo_mes = consulta_argamassa[consulta_argamassa['ESTQCOD'] == produto & (consulta_argamassa['MES'] == meses_corridos )]
            
            #Volume total
            volume_ultimo_mes_total = volume_ultimo_mes['PESO'].sum()
            volume_ultimo_mes_total = locale.format_string("%.0f",volume_ultimo_mes_total, grouping=True)

            #PROJEÇÂO
            producao_mensal_acumulada = volume_mensal_df['PESO'].sum()
            projecao_anual = (producao_mensal_acumulada / meses_corridos) * meses_no_ano
            projecao_anual = locale.format_string("%.0f", projecao_anual, grouping=True)

        else:
            projecao_anual = 0

        # Projeção anual agregada
        if meses_corridos > 0:
            projecao_anual_total = (producao_mensal_acumulada / meses_corridos) * meses_no_ano
            projecao_anual_total = locale.format_string("%.0f", projecao_anual_total, grouping=True)
        else:
            projecao_anual_total = 0

        volume_mensal = {
            #---------PROJECOES-----------------#
            'projecao_anual_total': projecao_anual_total,
            #------------MEDIAS--------------#####
            'media_mensal_cvc': media_mensal,
            #-----------VOLUMES-----------------####
            'volume_ultimo_mes_total': volume_ultimo_mes_total,
            #-----------INDIVIDUAIS------------#
            'produto': volume_mensal_df.to_dict(orient='records'),
            
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

###----------------------------------GRAFICOS CARREGAMENTO---------------------------"#########
@csrf_exempt
@api_view(['POST'])
def calculos_argamassa_graficos_carregamento(request):

    # Recuperando o tipo de cálculo do corpo da requisição
    tipo_calculo = request.data.get('tipo_calculo')
    produto = request.data.get('produto')
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
    SELECT CLINOME, CLICOD, TRANNOME, TRANCOD, NFPLACA, ESTUF, NFPED, NFNUM, SDSSERIE, NFDATA,INFQUANT,

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
        AND ESTQCOD = '{produto}'

    ORDER BY NFDATA, NFNUM
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
            return dias_completos.merge(volume_df, on='DIA', how='left').fillna(0)    

        #calculo do volume acumulado dos ensacados
        volume_diario_df = consulta_carregamento[consulta_carregamento['ESTQCOD'] == produto].groupby('DIA')['INFQUANT'].sum().reset_index()
        
        #Preencher dias Faltantes
        volume_diario = preencher_dias_faltantes(volume_diario_df)
        
        #MediasDiarias
        media_diaria = volume_diario_df['INFQUANT'].mean()
        media_diaria = locale.format_string("%.0f",media_diaria,grouping=True)

        #volume Total
        volume_diario_total = volume_diario_df['INFQUANT'].sum()
        #data Atual 
        hoje = datetime.now().day -1

        # Calculo média agregada todos os produtos
        if hoje > 0 :
            media_diaria_agregada = volume_diario_total / hoje
            media_diaria_agregada = locale.format_string("%.0f",media_diaria_agregada,grouping=True)
        else:
            media_diaria_agregada = 0

        #CAlculo de projeção
        dias_corridos = consulta_carregamento['DIA'].max()  #último dia no mes que teve produção
        dias_no_mes = (consulta_carregamento['NFDATA'].max().replace(day=1) + pd.DateOffset(months=1) - pd.DateOffset(days=1)).day   

        if dias_corridos > 0 :
            volume_ultimo_dia = consulta_carregamento[consulta_carregamento['ESTQCOD'] == produto & (consulta_carregamento['DIA'] == dias_corridos )]
            
            #Volume total
            volume_ultimo_dia_total = int(volume_ultimo_dia['INFQUANT'].sum())
            volume_ultimo_dia_total = locale.format_string("%.0f",volume_ultimo_dia_total,grouping=True)

            #PROJEÇÂO
            producao_acumulada =int (volume_diario_df['INFQUANT'].sum())
            projecao = (producao_acumulada / dias_corridos) * dias_no_mes
            projecao = locale.format_string("%.0f",projecao,grouping=True)

        else :
            projecao = 0
            volume_ultimo_dia_total = 0
            volume_ultimo_dia = 0
            
        volume_diario = {
            #----------VOLUMES ULTIMO DIA-----------------------#
            'volume_ultimo_dia_total': volume_ultimo_dia_total,
            #------------------PROJEÇÕES--------------------------------#
            'projecao': projecao,
            #----------------MEDIAS----------------------------------#
            'media_diaria': media_diaria,
            'media_diaria_agregada': media_diaria_agregada,
            #---------------VOLUME TOTAL---------------#
            'volume_ultimo_dia_total': volume_ultimo_dia_total,
            'volume_diario_total': volume_diario_total,
            #-----------------INDIVIDUAIS-----------------------#
            'produto': volume_diario_df.to_dict(orient='records'),
        }

    elif tipo_calculo == 'anual':
        consulta_carregamento['MES'] = consulta_carregamento['NFDATA'].dt.month

        # Função para preencher os meses faltantes com 0
        def preencher_meses_faltantes(volume_df):
            meses_completos = pd.DataFrame({'MES': range(1, 13)})
            return meses_completos.merge(volume_df, on='MES', how='left').fillna(0)
        
        #calculo do volume acumulado dos ensacados
        volume_mensal_df = consulta_carregamento[consulta_carregamento['ESTQCOD'] == produto].groupby('MES')['INFQUANT'].sum().reset_index()
       
        #Preencher dias Faltantes
        volume_mensal_df = preencher_meses_faltantes(volume_mensal_df)
    
        # Pegando o mês atual (corridos)
        mes_corrente = datetime.now().month

        # Somar o volume mensal sem incluir os meses futuros
        volume_mensal_df_filtrado = volume_mensal_df[volume_mensal_df['MES'] <= mes_corrente]
        
        # Médias mensais baseadas nos meses já passados
        media_mensal = volume_mensal_df_filtrado['INFQUANT'].sum() / mes_corrente
        media_mensal = locale.format_string("%.0f", media_mensal, grouping=True)

        #SOma valores mensais 
        volume_mensal_total = volume_mensal_df['INFQUANT'].sum()
        
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
            volume_ultimo_mes = consulta_carregamento[consulta_carregamento['ESTQCOD'] == produto & (consulta_carregamento['MES'] == meses_corridos )]
            
            #Volume total
            volume_ultimo_mes_total = int(volume_ultimo_mes['INFQUANT'].sum())
            volume_ultimo_mes_total = locale.format_string("%.0f",volume_ultimo_mes_total, grouping=True)

            #PROJEÇÂO
            producao_mensal_acumulada = volume_mensal_df['INFQUANT'].sum()
            projecao_anual = (producao_mensal_acumulada / meses_corridos) * meses_no_ano
            projecao_anual = locale.format_string("%.0f", projecao_anual, grouping=True)

        else:
            projecao_anual = 0
            volume_ultimo_mes_total = 0
            volume_ultimo_mes = 0

        volume_mensal = {
            #---------PROJECOES-----------------#
            'projecao_anual': projecao_anual,
            #------------MEDIAS--------------#####
            'media_mensal': media_mensal,
            'media_mensal_agregada': media_mensal_agregada,
            #-----------VOLUMES-----------------####
            'volume_ultimo_mes_total': volume_ultimo_mes_total,
            #-----------INDIVIDUAIS------------#
            'produto': volume_mensal_df.to_dict(orient='records'),
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