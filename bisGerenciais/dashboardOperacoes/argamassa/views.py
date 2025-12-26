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

pd.set_option('future.no_silent_downcasting', True)

connection_string = 'mssql+pyodbc://DBCONSULTA:%21%40%23123qweQWE@172.10.27.51:1433/DB?driver=ODBC+Driver+17+for+SQL+Server'
engine = create_engine(connection_string)

#-------------------------------------INDICADORES-----------------------------------------""

@csrf_exempt
@api_view(['POST'])
def calculos_indicadores_realizado(request):
    ano = request.data.get('ano', None)
    meses = request.data.get('periodo', [])
    
    # Validação dos meses
    if not isinstance(meses, list) or not all(isinstance(mes, int) and 1 <= mes <= 12 for mes in meses):
        raise ValueError("O parâmetro 'meses' deve ser uma lista de inteiros entre 1 e 12.")
    # Converte listas para strings no formato esperado pelo SQL
    meses_string = ", ".join(map(str, meses))

     # Gera o intervalo de datas com base no ano
    if ano:
        data_inicio = f"{ano}-01-01"
        #data_fim = f"{ano}-12-31"
        data_fim = datetime.today().strftime("%Y-%m-%d")
    else:
        raise ValueError("O parâmetro 'ano' é obrigatório.")    


    meses_condition = f"MONTH(BPRODATA1) IN ({meses_string})" if meses else "1=1"

    consulta_argamassa = pd.read_sql(f"""
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
                AND BPROEP = 1
                AND ({meses_condition})
                AND ESTQCOD != (5594)
                ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD
            """,engine)
    
    total = consulta_argamassa['PESO'].sum()
    return JsonResponse({'total': total}, status=200)




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
            INFQUANT, INFPESO,
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
    #Movimentação em Sacos   
    total_movimentacao = consulta_movimentacao['QUANT'].sum()
    total_movimentacao = locale.format_string("%.0f",total_movimentacao, grouping=True)

    total_movimentacao_sc = consulta_movimentacao['INFQUANT'].sum()
    total_movimentacao_sc = locale.format_string("%.0f",total_movimentacao_sc, grouping=True)

    response_data = {
            'total_movimentacao': total_movimentacao,
            'total_movimentacao_sc': total_movimentacao_sc,
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
                IBPROQUANT, ((ESTQPESO*IBPROQUANT) /1000) PESO,ESTQPESO

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
                AND ESTQCOD IN (
                    2708,2709,2710,2711,2714,2715,2716,2717,2719,2728,
                    2729,2730,22089,23987,23988,23989,24019,24020,24021,
                    24022,24023,24024,24222,25877,25878
                )
                ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD
            """,engine)
    #KPIs
    producao_total = consulta_argamassa['PESO'].sum()
    producao_total = int(producao_total)
    producao_total = locale.format_string("%.0f",producao_total,grouping=True)

    ensacado_total = consulta_argamassa['IBPROQUANT'].sum()
    ensacado_total = int(ensacado_total)
    ensacado_total = locale.format_string("%.0f",ensacado_total, grouping=True)

    ####################################################################################
    #Ensacado
    concrecal_cimento_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2728].groupby('ESTQCOD')['IBPROQUANT'].sum()
    concrecal_cimento_val = concrecal_cimento_int.item() if not concrecal_cimento_int.empty else 0
    concrecal_cimento_quant = locale.format_string("%.0f",concrecal_cimento_val,grouping=True) if concrecal_cimento_val > 0 else 0

    #Tonelada
    tn_concrecal_cimento_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2728].groupby('ESTQCOD')['PESO'].sum()
    tn_concrecal_cimento_val = tn_concrecal_cimento_int.item() if not tn_concrecal_cimento_int.empty else 0
    tn_concrecal_cimento_quant = locale.format_string("%.0f",tn_concrecal_cimento_val,grouping=True) if tn_concrecal_cimento_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_assent_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 22089].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_assent_val = arg_assent_int.item() if not arg_assent_int.empty else 0
    arg_assent_quant = locale.format_string("%.0f",arg_assent_val,grouping=True) if arg_assent_val > 0 else 0

    #Tonelada
    tn_arg_assent_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 22089].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_assent_val = tn_arg_assent_int.item() if not tn_arg_assent_int.empty else 0
    tn_arg_assent_quant = locale.format_string("%.0f",tn_arg_assent_val,grouping=True) if tn_arg_assent_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_colante_ac1_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2708].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_colante_ac1_val = arg_colante_ac1_int.item() if not arg_colante_ac1_int.empty else 0
    arg_colante_ac1_quant = locale.format_string("%.0f",arg_colante_ac1_val,grouping=True) if arg_colante_ac1_val > 0 else 0

    #Tonelada
    tn_arg_colante_ac1_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2708].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_colante_ac1_val = tn_arg_colante_ac1_int.item() if not tn_arg_colante_ac1_int.empty else 0
    tn_arg_colante_ac1_quant = locale.format_string("%.0f",tn_arg_colante_ac1_val,grouping=True) if tn_arg_colante_ac1_val > 0 else 0

    ####################################################################################


    #Ensacado
    arg_colante_ac2_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2709].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_colante_ac2_val = arg_colante_ac2_int.item() if not arg_colante_ac2_int.empty else 0
    arg_colante_ac2_quant = locale.format_string("%.0f",arg_colante_ac2_val,grouping=True) if arg_colante_ac2_val > 0 else 0

    #Tonelada
    tn_arg_colante_ac2_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2709].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_colante_ac2_val = tn_arg_colante_ac2_int.item() if not tn_arg_colante_ac2_int.empty else 0
    tn_arg_colante_ac2_quant = locale.format_string("%.0f",tn_arg_colante_ac2_val,grouping=True) if tn_arg_colante_ac2_val > 0 else 0

    ####################################################################################       

    #Ensacado
    arg_colante_ac3_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2710].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_colante_ac3_val = arg_colante_ac3_int.item() if not arg_colante_ac3_int.empty else 0
    arg_colante_ac3_quant = locale.format_string("%.0f",arg_colante_ac3_val,grouping=True) if arg_colante_ac3_val > 0 else 0

    #Tonelada
    tn_arg_colante_ac3_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2710].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_colante_ac3_val = tn_arg_colante_ac3_int.item() if not tn_arg_colante_ac3_int.empty else 0
    tn_arg_colante_ac3_quant = locale.format_string("%.0f",tn_arg_colante_ac3_val,grouping=True) if tn_arg_colante_ac3_val > 0 else 0


    ####################################################################################

    #Ensacado
    arg_projecao_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2730].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_projecao_val = arg_projecao_int.item() if not arg_projecao_int.empty else 0
    arg_projecao_quant = locale.format_string("%.0f",arg_projecao_val,grouping=True) if arg_projecao_val > 0 else 0

    #Tonelada
    tn_arg_projecao_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2730].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_projecao_val = tn_arg_projecao_int.item() if not tn_arg_projecao_int.empty else 0
    tn_arg_projecao_quant = locale.format_string("%.0f",tn_arg_projecao_val,grouping=True) if tn_arg_projecao_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_rev_arv1_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 23987].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_rev_arv1_val = arg_rev_arv1_int.item() if not arg_rev_arv1_int.empty else 0
    arg_rev_arv1_quant = locale.format_string("%.0f",arg_rev_arv1_val,grouping=True) if arg_rev_arv1_val > 0 else 0

    #Tonelada
    tn_arg_rev_arv1_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 23987].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_rev_arv1_val = tn_arg_rev_arv1_int.item() if not tn_arg_rev_arv1_int.empty else 0    
    tn_arg_rev_arv1_quant = locale.format_string("%.0f",tn_arg_rev_arv1_val,grouping=True) if tn_arg_rev_arv1_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_rev_arv2_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 23988].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_rev_arv2_val = arg_rev_arv2_int.item() if not arg_rev_arv2_int.empty else 0
    arg_rev_arv2_quant = locale.format_string("%.0f",arg_rev_arv2_val,grouping=True) if arg_rev_arv2_val > 0 else 0

    #Tonelada
    tn_arg_rev_arv2_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 23988].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_rev_arv2_val = tn_arg_rev_arv2_int.item() if not tn_arg_rev_arv2_int.empty else 0
    tn_arg_rev_arv2_quant = locale.format_string("%.0f",tn_arg_rev_arv2_val,grouping=True) if tn_arg_rev_arv2_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_rev_arv3_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 23989].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_rev_arv3_val = arg_rev_arv3_int.item() if not arg_rev_arv3_int.empty else 0
    arg_rev_arv3_quant = locale.format_string("%.0f",arg_rev_arv3_val,grouping=True) if arg_rev_arv3_val > 0 else 0

    #Tonelada
    tn_arg_rev_arv3_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 23989].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_rev_arv3_val = tn_arg_rev_arv3_int.item() if not tn_arg_rev_arv3_int.empty else 0
    tn_arg_rev_arv3_quant = locale.format_string("%.0f",tn_arg_rev_arv3_val,grouping=True) if tn_arg_rev_arv3_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_est_aae12_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24021].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae12_val = arg_est_aae12_int.item() if not arg_est_aae12_int.empty else 0
    arg_est_aae12_quant = locale.format_string("%.0f",arg_est_aae12_val,grouping=True) if arg_est_aae12_val > 0 else 0

    #Tonelada
    tn_arg_est_aae12_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24021].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_est_aae12_val = tn_arg_est_aae12_int.item() if not tn_arg_est_aae12_int.empty else 0    
    tn_arg_est_aae12_quant = locale.format_string("%.0f",tn_arg_est_aae12_val,grouping=True) if tn_arg_est_aae12_val > 0 else 0

    #################################################################################### 

    #Ensacado
    arg_est_aae16_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24022].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae16_val = arg_est_aae16_int.item() if not arg_est_aae16_int.empty else 0
    arg_est_aae16_quant = locale.format_string("%.0f",arg_est_aae16_val,grouping=True) if arg_est_aae16_val > 0 else 0

    #Tonelada
    tn_arg_est_aae16_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24022].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_est_aae16_val = tn_arg_est_aae16_int.item() if not tn_arg_est_aae16_int.empty else 0
    tn_arg_est_aae16_quant = locale.format_string("%.0f",tn_arg_est_aae16_val,grouping=True) if tn_arg_est_aae16_val > 0 else 0

    ####################################################################################    

    #Ensacado
    arg_est_aae20_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24023].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae20_val = arg_est_aae20_int.item() if not arg_est_aae20_int.empty else 0
    arg_est_aae20_quant = locale.format_string("%.0f",arg_est_aae20_val,grouping=True) if arg_est_aae20_val > 0 else 0

    #Tonelada
    tn_arg_est_aae20_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24023].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_est_aae20_val = tn_arg_est_aae20_int.item() if not tn_arg_est_aae20_int.empty else 0
    tn_arg_est_aae20_quant = locale.format_string("%.0f",tn_arg_est_aae20_val,grouping=True) if tn_arg_est_aae20_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_est_aae5_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24019].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae5_val = arg_est_aae5_int.item() if not arg_est_aae5_int.empty else 0
    arg_est_aae5_quant = locale.format_string("%.0f",arg_est_aae5_val,grouping=True) if arg_est_aae5_val > 0 else 0

    #Tonelada
    tn_arg_est_aae5_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24019].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_est_aae5_val = tn_arg_est_aae5_int.item() if not tn_arg_est_aae5_int.empty else 0
    tn_arg_est_aae5_quant = locale.format_string("%.0f",tn_arg_est_aae5_val,grouping=True) if tn_arg_est_aae5_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_est_aae8_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24020].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae8_val = arg_est_aae8_int.item() if not arg_est_aae8_int.empty else 0
    arg_est_aae8_quant = locale.format_string("%.0f",arg_est_aae8_val,grouping=True) if arg_est_aae8_val > 0 else 0

    #Tonelada
    tn_arg_est_aae8_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24020].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_est_aae8_val = tn_arg_est_aae8_int.item() if not tn_arg_est_aae8_int.empty else 0
    tn_arg_est_aae8_quant = locale.format_string("%.0f",tn_arg_est_aae8_val,grouping=True) if tn_arg_est_aae8_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_est_aae_esp_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24024].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_est_aae_esp_val = arg_est_aae_esp_int.item() if not arg_est_aae_esp_int.empty else 0
    arg_est_aae_esp_quant = locale.format_string("%.0f",arg_est_aae_esp_val,grouping=True) if arg_est_aae_esp_val > 0 else 0

    #Tonelada
    tn_arg_est_aae_esp_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24024].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_est_aae_esp_val = tn_arg_est_aae_esp_int.item() if not tn_arg_est_aae_esp_int.empty else 0
    tn_arg_est_aae_esp_quant = locale.format_string("%.0f",tn_arg_est_aae_esp_val,grouping=True) if tn_arg_est_aae_esp_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_grossa_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2715].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_grossa_val = arg_grossa_int.item() if not arg_grossa_int.empty else 0
    arg_grossa_quant = locale.format_string("%.0f",arg_grossa_val,grouping=True) if arg_grossa_val > 0 else 0  

    #Tonelada
    tn_arg_grossa_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2715].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_grossa_val = tn_arg_grossa_int.item() if not tn_arg_grossa_int.empty else 0
    tn_arg_grossa_quant = locale.format_string("%.0f",tn_arg_grossa_val,grouping=True) if tn_arg_grossa_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_grossa_fibra_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2716].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_grossa_fibra_val = arg_grossa_fibra_int.item() if not arg_grossa_fibra_int.empty else 0
    arg_grossa_fibra_quant = locale.format_string("%.0f",arg_grossa_fibra_val,grouping=True) if arg_grossa_fibra_val > 0 else 0 

    #Tonelada
    tn_arg_grossa_fibra_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2716].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_grossa_fibra_val = tn_arg_grossa_fibra_int.item() if not tn_arg_grossa_fibra_int.empty else 0
    tn_arg_grossa_fibra_quant = locale.format_string("%.0f",tn_arg_grossa_fibra_val,grouping=True) if tn_arg_grossa_fibra_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_media_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2711].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_media_val = arg_media_int.item() if not arg_media_int.empty else 0
    arg_media_quant = locale.format_string("%.0f",arg_media_val,grouping=True) if arg_media_val > 0 else 0 

    #Tonelada
    tn_arg_media_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2711].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_media_val = tn_arg_media_int.item() if not tn_arg_media_int.empty else 0
    tn_arg_media_quant = locale.format_string("%.0f",tn_arg_media_val,grouping=True) if tn_arg_media_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_media_fibra_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2714].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_media_fibra_val = arg_media_fibra_int.item() if not arg_media_fibra_int.empty else 0
    arg_media_fibra_quant = locale.format_string("%.0f",arg_media_fibra_val,grouping=True) if arg_media_fibra_val > 0 else 0 

    #Tonelada
    tn_arg_media_fibra_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2714].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_media_fibra_val = tn_arg_media_fibra_int.item() if not tn_arg_media_fibra_int.empty else 0
    tn_arg_media_fibra_quant = locale.format_string("%.0f",tn_arg_media_fibra_val,grouping=True) if tn_arg_media_fibra_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_mult_uso_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24222].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_mult_uso_val = arg_mult_uso_int.item() if not arg_mult_uso_int.empty else 0
    arg_mult_uso_quant = locale.format_string("%.0f",arg_mult_uso_val,grouping=True) if arg_mult_uso_val > 0 else 0

    #Tonelada
    tn_arg_mult_uso_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 24222].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_mult_uso_val = tn_arg_mult_uso_int.item() if not tn_arg_mult_uso_int.empty else 0
    tn_arg_mult_uso_quant = locale.format_string("%.0f",tn_arg_mult_uso_val,grouping=True) if tn_arg_mult_uso_val > 0 else 0

    ####################################################################################    

    #Ensacado
    arg_piso_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2717].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_piso_val = arg_piso_int.item() if not arg_piso_int.empty else 0
    arg_piso_quant = locale.format_string("%.0f",arg_piso_val,grouping=True) if arg_piso_val > 0 else 0   

    #Tonelada
    tn_arg_piso_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2717].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_piso_val = tn_arg_piso_int.item() if not tn_arg_piso_int.empty else 0
    tn_arg_piso_quant = locale.format_string("%.0f",tn_arg_piso_val,grouping=True) if tn_arg_piso_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_contrapiso_10mpa_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 25878].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_contrapiso_10mpa_val = arg_contrapiso_10mpa_int.item() if not arg_contrapiso_10mpa_int.empty else 0
    arg_contrapiso_10mpa_quant = locale.format_string("%.0f",arg_contrapiso_10mpa_val,grouping=True) if arg_contrapiso_10mpa_val > 0 else 0  

    #Tonelada
    tn_arg_contrapiso_10mpa_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 25878].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_contrapiso_10mpa_val = tn_arg_contrapiso_10mpa_int.item() if not tn_arg_contrapiso_10mpa_int.empty else 0
    tn_arg_contrapiso_10mpa_quant = locale.format_string("%.0f",tn_arg_contrapiso_10mpa_val,grouping=True) if tn_arg_contrapiso_10mpa_val > 0 else 0

    ####################################################################################

    #Ensacado
    arg_contrapiso_5mpa_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 25877].groupby('ESTQCOD')['IBPROQUANT'].sum()
    arg_contrapiso_5mpa_val = arg_contrapiso_5mpa_int.item() if not arg_contrapiso_5mpa_int.empty else 0
    arg_contrapiso_5mpa_quant = locale.format_string("%.0f",arg_contrapiso_5mpa_val,grouping=True) if arg_contrapiso_5mpa_val > 0 else 0

    #Tonelada
    tn_arg_contrapiso_5mpa_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 25877].groupby('ESTQCOD')['PESO'].sum()
    tn_arg_contrapiso_5mpa_val = tn_arg_contrapiso_5mpa_int.item() if not tn_arg_contrapiso_5mpa_int.empty else 0
    tn_arg_contrapiso_5mpa_quant = locale.format_string("%.0f",tn_arg_contrapiso_5mpa_val,grouping=True) if tn_arg_contrapiso_5mpa_val > 0 else 0

    ####################################################################################

    #Ensacado
    massa_fina_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2719].groupby('ESTQCOD')['IBPROQUANT'].sum()
    massa_fina_val = massa_fina_int.item() if not massa_fina_int.empty else 0
    massa_fina_quant = locale.format_string("%.0f",massa_fina_val,grouping=True) if massa_fina_val > 0 else 0  

    #Tonelada
    tn_massa_fina_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2719].groupby('ESTQCOD')['PESO'].sum()
    tn_massa_fina_val = tn_massa_fina_int.item() if not tn_massa_fina_int.empty else 0
    tn_massa_fina_quant = locale.format_string("%.0f",tn_massa_fina_val,grouping=True) if tn_massa_fina_val > 0 else 0

    ####################################################################################

    #Ensacado
    multichapisco_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2729].groupby('ESTQCOD')['IBPROQUANT'].sum()
    multichapisco_val = multichapisco_int.item() if not multichapisco_int.empty else 0
    multichapisco_quant = locale.format_string("%.0f",multichapisco_val,grouping=True) if multichapisco_val > 0 else 0 

    #Tonelada
    tn_multichapisco_int = consulta_argamassa[consulta_argamassa['ESTQCOD'] == 2729].groupby('ESTQCOD')['PESO'].sum()
    tn_multichapisco_val = tn_multichapisco_int.item() if not tn_multichapisco_int.empty else 0
    tn_multichapisco_quant = locale.format_string("%.0f",tn_multichapisco_val,grouping=True) if tn_multichapisco_val > 0 else 0

    ####################################################################################

    response_data = {
        'CONCRECAL CAL + CIMENTO - SC 20 KG':concrecal_cimento_quant,
        'CONCRECAL CAL + CIMENTO - TN':tn_concrecal_cimento_quant,
        ###-----------------------CONCRECAL 20KG---------------------------#########
        'PRIMEX ARGAMASSA ASSENTAMENTO DE ALVENARIA - AAV - SC 20 KG':arg_assent_quant,
        'PRIMEX ARGAMASSA ASSENTAMENTO DE ALVENARIA - AAV - TN':tn_arg_assent_quant,
        ###-----------------------Primex20KG---------------------------#########
        'PRIMEX ARGAMASSA COLANTE AC-I - SC 20 KG':arg_colante_ac1_quant,
        'PRIMEX ARGAMASSA COLANTE AC-I - TN':tn_arg_colante_ac1_quant,
        ###-----------------------Primex ACI 20KG---------------------------#########
        'PRIMEX ARGAMASSA COLANTE AC-II - SC 20 KG':arg_colante_ac2_quant,
        'PRIMEX ARGAMASSA COLANTE AC-II - TN':tn_arg_colante_ac2_quant,
        ###-----------------------Primex ACII 20KG---------------------------#########
        'PRIMEX ARGAMASSA COLANTE AC-III - SC 20 KG':arg_colante_ac3_quant,
        'PRIMEX ARGAMASSA COLANTE AC-III - TN':tn_arg_colante_ac3_quant,
        ###-----------------------Primex ACIII 20KG---------------------------#########
        'PRIMEX ARGAMASSA DE PROJECAO - SC 25 KG':arg_projecao_quant,
        'PRIMEX ARGAMASSA DE PROJECAO - TN':tn_arg_projecao_quant,
        ###-----------------------Primex PROJECAO 25KG---------------------------#########
        'PRIMEX ARGAMASSA DE REVESTIMENTO ARV-I SC 20 KG':arg_rev_arv1_quant,
        'PRIMEX ARGAMASSA DE REVESTIMENTO ARV-I - TN':tn_arg_rev_arv1_quant,
        ###-----------------------Primex ARV1 20KG---------------------------#########
        'PRIMEX ARGAMASSA DE REVESTIMENTO ARV-II SC 20 KG':arg_rev_arv2_quant,
        'PRIMEX ARGAMASSA DE REVESTIMENTO ARV-II - TN':tn_arg_rev_arv2_quant,
        ###-----------------------Primex ARV2 20KG---------------------------#########
        'PRIMEX ARGAMASSA DE REVESTIMENTO ARV-III SC 20 KG':arg_rev_arv3_quant,
        'PRIMEX ARGAMASSA DE REVESTIMENTO ARV-III - TN':tn_arg_rev_arv3_quant,
        ###-----------------------Primex ARV3 20KG---------------------------#########
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-12 - SC 20 KG':arg_est_aae12_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-12 - TN':tn_arg_est_aae12_quant,
        ###-----------------------Primex AAE12 20KG---------------------------#########
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-16 - SC 20 KG':arg_est_aae16_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-16 - TN':tn_arg_est_aae16_quant,
        ###-----------------------Primex AAE16 20KG---------------------------#########
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-20 - SC 20 KG':arg_est_aae20_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-20 - TN':tn_arg_est_aae20_quant,
        ###-----------------------Primex AAE20 20KG---------------------------#########
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-5 - SC 20 KG':arg_est_aae5_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-5 - TN':tn_arg_est_aae5_quant,
        ###-----------------------Primex AAE5 20KG---------------------------#########
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-8 - SC 20 KG':arg_est_aae8_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-8 - TN':tn_arg_est_aae8_quant,
        ###-----------------------Primex AAE8 20KG---------------------------#########
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-ESPECIAL - SC 20 KG':arg_est_aae_esp_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-ESPECIAL - TN':tn_arg_est_aae_esp_quant,
        ###-----------------------Primex AAE-ESP 20KG---------------------------#########
        'PRIMEX ARGAMASSA GROSSA - SC- 25 KG':arg_grossa_quant,
        'PRIMEX ARGAMASSA GROSSA - TN':tn_arg_grossa_quant,
        ###-----------------------Primex GROSSA 25KG---------------------------#########
        'PRIMEX ARGAMASSA GROSSA C/ FIBRA - SC 25 KG':arg_grossa_fibra_quant,
        'PRIMEX ARGAMASSA GROSSA C/ FIBRA - TN':tn_arg_grossa_fibra_quant,
        ###-----------------------Primex GROSSA FIBRA 25KG---------------------------#########
        'PRIMEX ARGAMASSA MEDIA - SC 25 KG':arg_media_quant,
        'PRIMEX ARGAMASSA MEDIA - TN':tn_arg_media_quant,
        ###-----------------------Primex MEDIA 25KG---------------------------#########
        'PRIMEX ARGAMASSA MEDIA C/ FIBRA - SC 25 KG':arg_media_fibra_quant,
        'PRIMEX ARGAMASSA MEDIA C/ FIBRA - TN':tn_arg_media_fibra_quant,
        ###-----------------------Primex MEDIA FIBRA 25KG---------------------------#########
        'PRIMEX ARGAMASSA MULTIPLO USO - SC 20 KG': arg_mult_uso_quant,
        'PRIMEX ARGAMASSA MULTIPLO USO - TN':tn_arg_mult_uso_quant,
        ###-----------------------Primex MULT USO 20KG---------------------------#########
        'PRIMEX ARGAMASSA P/ PISO - SC 25 KG':arg_piso_quant,
        'PRIMEX ARGAMASSA P/ PISO - TN':tn_arg_piso_quant,
        ###-----------------------Primex PISO 25KG---------------------------#########
        'PRIMEX ARGAMASSA PARA CONTRAPISO 10 MPA - SC 20 KG': arg_contrapiso_10mpa_quant,
        'PRIMEX ARGAMASSA PARA CONTRAPISO 10 MPA - TN':tn_arg_contrapiso_10mpa_quant,
        ###-----------------------Primex CONTRAPISO 10MPA 20KG---------------------------#########
        'PRIMEX ARGAMASSA PARA CONTRAPISO 5  MPA - SC 20 KG':arg_contrapiso_5mpa_quant,
        'PRIMEX ARGAMASSA PARA CONTRAPISO 5  MPA - TN':tn_arg_contrapiso_5mpa_quant,
        ###-----------------------Primex CONTRAPISO 5MPA 20KG---------------------------#########
        'PRIMEX MASSA FINA - SC 20 KG':massa_fina_quant,
        'PRIMEX MASSA FINA - TN':tn_massa_fina_quant,
        ###-----------------------Primex MASSA FINA 20KG---------------------------#########
        'PRIMEX MULTICHAPISCO - SC 20 KG':multichapisco_quant,
        'PRIMEX MULTICHAPISCO - TN':tn_multichapisco_quant,
        ###-----------------------Primex MULTICHAPISCO 20KG---------------------------#########
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
    data = request.data.get('data')
    dataFim = request.data.get('data_fim')
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
        IBPROQUANT UNIDADES, ESTQPESO,((ESTQPESO*IBPROQUANT) /1000) QUANT, 
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
        AND CAST(BPRODATA1 as date) BETWEEN '{data}' AND '{dataFim}'
        AND BPROEP = 1
        AND ESPSIGLA = 'SC'
        AND BPROEQP IN (264,265)
        ORDER BY BPRO.BPROCOD

        """,engine)
    
    # Calcular o total de horas do período consultado
    total_horas_periodo = (pd.to_datetime(dataFim) - pd.to_datetime(data)).total_seconds() / 3600

    #ARG MH-01
    mh01_hora_producao_int =  consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 264 ].groupby('EQUIPAMENTO_CODIGO')['HRPRO'].sum()
    mh01_hora_producao_val = mh01_hora_producao_int.item() if not mh01_hora_producao_int.empty else 0
    mh01_hora_producao_quant = locale.format_string("%.0f",mh01_hora_producao_val,grouping=True) if mh01_hora_producao_val > 0 else 0

    # Calcular a hora parada
    mh01_hora_parado_val = total_horas_periodo - mh01_hora_producao_val
    mh01_hora_parado_quant = locale.format_string("%.1f", mh01_hora_parado_val, grouping=True) if mh01_hora_parado_val > 0 else 0

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

     # Calcular a hora parada
    mh02_hora_parado_val = total_horas_periodo - mh02_hora_producao_val
    mh02_hora_parado_quant = locale.format_string("%.1f", mh02_hora_parado_val, grouping=True) if mh02_hora_parado_val > 0 else 0

    mh02_producao_int =  consulta_equipamentos[consulta_equipamentos['EQUIPAMENTO_CODIGO'] == 265 ].groupby('EQUIPAMENTO_CODIGO')['QUANT'].sum()
    mh02_producao_val = mh02_producao_int.item() if not mh02_producao_int.empty else 0
    mh02_producao_quant = locale.format_string("%.0f",mh02_producao_val,grouping=True) if mh02_producao_val > 0 else 0

    mh02_produtividade_val = 0 
    if mh01_hora_producao_val > 0:
        mh02_produtividade_val = mh02_producao_val / mh02_hora_producao_val
        mh02_produtividade = locale.format_string("%.0f",mh02_produtividade_val, grouping=True)
    else:
        mh02_produtividade = 0

    argamassa_produtividade =  (mh01_produtividade_val + mh02_produtividade_val) / 2
    argamassa_produtividade = locale.format_string("%.0f",argamassa_produtividade,grouping=True) if argamassa_produtividade > 0 else 0   

    argamassa_producao = mh01_producao_val + mh02_producao_val
    argamassa_producao = locale.format_string("%.0f",argamassa_producao, grouping=True) if argamassa_producao > 0 else 0

####------------------------------------------------CARREGAMENTO DO DIA---------------####
    data = request.data.get('data')
    dataFim = request.data.get('data_fim')
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
            AND CAST (NFDATA as date) BETWEEN '{data}' AND '{dataFim}'
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
            'mh01_hora_producao':mh01_hora_producao_quant,
            'mh01_hora_parado':mh01_hora_parado_quant,
            'mh01_producao':mh01_producao_quant,
            'mh01_produtividade':mh01_produtividade,
            'mh02_hora_producao':mh02_hora_producao_quant,
            'mh02_hora_parado':mh02_hora_parado_quant,
            'mh02_producao':mh02_producao_quant,
            'mh02_produtividade':mh02_produtividade,
            'argamassa_produtividade':argamassa_produtividade,
            'argamassa_producao': argamassa_producao,
            'total_movimentacao':total_movimentacao
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
        # def preencher_dias_faltantes(volume_df):
        #     dias_completos = pd.DataFrame({'DIA': range(1, 32)})
        #     return dias_completos.merge(volume_df, on='DIA', how='left').fillna(0)
        
        def preencher_dias_faltantes(volume_df):
            dias_completos = pd.DataFrame({'DIA': range(1, 32)})
         # Preenche valores nulos com 0 e converte tipos de dados
            return dias_completos.merge(volume_df, on='DIA', how='left').fillna(0).infer_objects(copy=False)


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
            projecao_val = (producao_acumulada / dias_corridos) * dias_no_mes
            projecao = locale.format_string("%.0f",projecao_val,grouping=True) if projecao_val > 0 else 0

        else :
            projecao = 0
            volume_ultimo_dia_total = 0
        

        volume_diario = {
            #----------VOLUMES ULTIMO DIA-----------------------#
           # 'volume_ultimo_dia_total': volume_ultimo_dia_total,
            #------------------PROJEÇÕES--------------------------------#
            'projecao': projecao,
            #----------------MEDIAS----------------------------------#
            'media': media_diaria,
            'media_diaria_agregada': media_diaria_agregada,
            #---------------VOLUME TOTAL---------------#
            
            'volume_diario_total': volume_diario_total,
            #-----------------INDIVIDUAIS-----------------------#
            'produto': volume_diario_df.to_dict(orient='records'),

        }
       
    elif tipo_calculo == 'anual':
        consulta_argamassa['MES'] = consulta_argamassa['BPRODATA'].dt.month

        # Função para preencher os meses faltantes com 0
        # def preencher_meses_faltantes(volume_df):
        #     meses_completos = pd.DataFrame({'MES': range(1, 13)})
        #     return meses_completos.merge(volume_df, on='MES', how='left').fillna(0)

        def preencher_meses_faltantes(volume_df):
            meses_completos = pd.DataFrame({'MES': range(1, 13)})
         # Preenche valores nulos com 0 e converte tipos de dados
            return meses_completos.merge(volume_df, on='MES', how='left').fillna(0).infer_objects(copy=False)
        
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
            'projecao': projecao_anual_total,
            #------------MEDIAS--------------#####
            'media': media_mensal,
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
            return dias_completos.merge(volume_df, on='DIA', how='left').fillna(0).infer_objects(copy=False)   

        #calculo do volume acumulado dos ensacados
        volume_diario_df = consulta_carregamento[consulta_carregamento['ESTQCOD'] == produto].groupby('DIA')['QUANT'].sum().reset_index()
        
        #Preencher dias Faltantes
        volume_diario = preencher_dias_faltantes(volume_diario_df)
        
        #MediasDiarias
        media_diaria_val = volume_diario_df['QUANT'].mean()
        media_diaria = locale.format_string("%.0f",media_diaria_val,grouping=True) if media_diaria_val > 0 else 0

        #volume Total
        volume_diario_total = volume_diario_df['QUANT'].sum()
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
            volume_ultimo_dia_total = int(volume_ultimo_dia['QUANT'].sum())
            volume_ultimo_dia_total = locale.format_string("%.0f",volume_ultimo_dia_total,grouping=True)

            #PROJEÇÂO
            producao_acumulada =int (volume_diario_df['QUANT'].sum())
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
            return meses_completos.merge(volume_df, on='MES', how='left').fillna(0).infer_objects(copy=False)
        
        #calculo do volume acumulado dos ensacados
        volume_mensal_df = consulta_carregamento[consulta_carregamento['ESTQCOD'] == produto].groupby('MES')['QUANT'].sum().reset_index()
       
        #Preencher dias Faltantes
        volume_mensal_df = preencher_meses_faltantes(volume_mensal_df)
    
        # Pegando o mês atual (corridos)
        mes_corrente = datetime.now().month

        # Somar o volume mensal sem incluir os meses futuros
        volume_mensal_df_filtrado = volume_mensal_df[volume_mensal_df['MES'] <= mes_corrente]
        
        # Médias mensais baseadas nos meses já passados
        media_mensal = volume_mensal_df_filtrado['QUANT'].sum() / mes_corrente
        media_mensal = locale.format_string("%.0f", media_mensal, grouping=True)

        #SOma valores mensais 
        volume_mensal_total = volume_mensal_df['QUANT'].sum()
        
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
            volume_ultimo_mes_total = int(volume_ultimo_mes['QUANT'].sum())
            volume_ultimo_mes_total = locale.format_string("%.0f",volume_ultimo_mes_total, grouping=True)

            #PROJEÇÂO
            producao_mensal_acumulada = volume_mensal_df['QUANT'].sum()
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

#---------------CARREGAMENTO POR PRODUTO----------------------
@csrf_exempt
@api_view(['POST'])
def calculos_argamassa_produtos_carregamento(request):

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
        AND ESTQCOD IN (
                2728, 22089, 2708, 2709, 2710, 2730, 23987, 23988, 23989, 24021, 24022, 24023, 24019, 
                24020, 24024, 2715, 2716, 2711, 2714, 24222, 2717, 2718, 25878, 25877, 2719, 2729
            )

    ORDER BY NFDATA, NFNUM
                 """,engine)
    concrecal_cimento_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2728].groupby('ESTQCOD')['QUANT'].sum()
    concrecal_cimento_val = concrecal_cimento_int.item() if not concrecal_cimento_int.empty else 0
    concrecal_cimento_quant = locale.format_string("%.0f",concrecal_cimento_val,grouping=True) if concrecal_cimento_val > 0 else 0

    arg_assent_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 22089].groupby('ESTQCOD')['QUANT'].sum()
    arg_assent_val = arg_assent_int.item() if not arg_assent_int.empty else 0
    arg_assent_quant = locale.format_string("%.0f",arg_assent_val,grouping=True) if arg_assent_val > 0 else 0

    arg_colante_ac1_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2708].groupby('ESTQCOD')['QUANT'].sum()
    arg_colante_ac1_val = arg_colante_ac1_int.item() if not arg_colante_ac1_int.empty else 0
    arg_colante_ac1_quant = locale.format_string("%.0f",arg_colante_ac1_val,grouping=True) if arg_colante_ac1_val > 0 else 0

    arg_colante_ac2_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2709].groupby('ESTQCOD')['QUANT'].sum()
    arg_colante_ac2_val = arg_colante_ac2_int.item() if not arg_colante_ac2_int.empty else 0
    arg_colante_ac2_quant = locale.format_string("%.0f",arg_colante_ac2_val,grouping=True) if arg_colante_ac2_val > 0 else 0

    arg_colante_ac3_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2710].groupby('ESTQCOD')['QUANT'].sum()
    arg_colante_ac3_val = arg_colante_ac3_int.item() if not arg_colante_ac3_int.empty else 0
    arg_colante_ac3_quant = locale.format_string("%.0f",arg_colante_ac3_val,grouping=True) if arg_colante_ac3_val > 0 else 0

    arg_projecao_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2730].groupby('ESTQCOD')['QUANT'].sum()
    arg_projecao_val = arg_projecao_int.item() if not arg_projecao_int.empty else 0
    arg_projecao_quant = locale.format_string("%.0f",arg_projecao_val,grouping=True) if arg_projecao_val > 0 else 0

    arg_rev_arv1_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 23987].groupby('ESTQCOD')['QUANT'].sum()
    arg_rev_arv1_val = arg_rev_arv1_int.item() if not arg_rev_arv1_int.empty else 0
    arg_rev_arv1_quant = locale.format_string("%.0f",arg_rev_arv1_val,grouping=True) if arg_rev_arv1_val > 0 else 0

    arg_rev_arv2_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 23988].groupby('ESTQCOD')['QUANT'].sum()
    arg_rev_arv2_val = arg_rev_arv2_int.item() if not arg_rev_arv2_int.empty else 0
    arg_rev_arv2_quant = locale.format_string("%.0f",arg_rev_arv2_val,grouping=True) if arg_rev_arv2_val > 0 else 0

    arg_rev_arv3_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 23989].groupby('ESTQCOD')['QUANT'].sum()
    arg_rev_arv3_val = arg_rev_arv3_int.item() if not arg_rev_arv3_int.empty else 0
    arg_rev_arv3_quant = locale.format_string("%.0f",arg_rev_arv3_val,grouping=True) if arg_rev_arv3_val > 0 else 0

    arg_est_aae12_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 24021].groupby('ESTQCOD')['QUANT'].sum()
    arg_est_aae12_val = arg_est_aae12_int.item() if not arg_est_aae12_int.empty else 0
    arg_est_aae12_quant = locale.format_string("%.0f",arg_est_aae12_val,grouping=True) if arg_est_aae12_val > 0 else 0

    arg_est_aae16_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 24022].groupby('ESTQCOD')['QUANT'].sum()
    arg_est_aae16_val = arg_est_aae16_int.item() if not arg_est_aae16_int.empty else 0
    arg_est_aae16_quant = locale.format_string("%.0f",arg_est_aae16_val,grouping=True) if arg_est_aae16_val > 0 else 0

    arg_est_aae20_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 24023].groupby('ESTQCOD')['QUANT'].sum()
    arg_est_aae20_val = arg_est_aae20_int.item() if not arg_est_aae20_int.empty else 0
    arg_est_aae20_quant = locale.format_string("%.0f",arg_est_aae20_val,grouping=True) if arg_est_aae20_val > 0 else 0

    arg_est_aae5_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 24019].groupby('ESTQCOD')['QUANT'].sum()
    arg_est_aae5_val = arg_est_aae5_int.item() if not arg_est_aae5_int.empty else 0
    arg_est_aae5_quant = locale.format_string("%.0f",arg_est_aae5_val,grouping=True) if arg_est_aae5_val > 0 else 0

    arg_est_aae8_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 24020].groupby('ESTQCOD')['QUANT'].sum()
    arg_est_aae8_val = arg_est_aae8_int.item() if not arg_est_aae8_int.empty else 0
    arg_est_aae8_quant = locale.format_string("%.0f",arg_est_aae8_val,grouping=True) if arg_est_aae8_val > 0 else 0

    arg_est_aae_esp_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 24024].groupby('ESTQCOD')['QUANT'].sum()
    arg_est_aae_esp_val = arg_est_aae_esp_int.item() if not arg_est_aae_esp_int.empty else 0
    arg_est_aae_esp_quant = locale.format_string("%.0f",arg_est_aae_esp_val,grouping=True) if arg_est_aae_esp_val > 0 else 0

    arg_grossa_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2715].groupby('ESTQCOD')['QUANT'].sum()
    arg_grossa_val = arg_grossa_int.item() if not arg_grossa_int.empty else 0
    arg_grossa_quant = locale.format_string("%.0f",arg_grossa_val,grouping=True) if arg_grossa_val > 0 else 0  

    arg_grossa_fibra_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2716].groupby('ESTQCOD')['QUANT'].sum()
    arg_grossa_fibra_val = arg_grossa_fibra_int.item() if not arg_grossa_fibra_int.empty else 0
    arg_grossa_fibra_quant = locale.format_string("%.0f",arg_grossa_fibra_val,grouping=True) if arg_grossa_fibra_val > 0 else 0 

    arg_media_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2711].groupby('ESTQCOD')['QUANT'].sum()
    arg_media_val = arg_media_int.item() if not arg_media_int.empty else 0
    arg_media_quant = locale.format_string("%.0f",arg_media_val,grouping=True) if arg_media_val > 0 else 0 

    arg_media_fibra_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2714].groupby('ESTQCOD')['QUANT'].sum()
    arg_media_fibra_val = arg_media_fibra_int.item() if not arg_media_fibra_int.empty else 0
    arg_media_fibra_quant = locale.format_string("%.0f",arg_media_fibra_val,grouping=True) if arg_media_fibra_val > 0 else 0 

    arg_mult_uso_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 24222].groupby('ESTQCOD')['QUANT'].sum()
    arg_mult_uso_val = arg_mult_uso_int.item() if not arg_mult_uso_int.empty else 0
    arg_mult_uso_quant = locale.format_string("%.0f",arg_mult_uso_val,grouping=True) if arg_mult_uso_val > 0 else 0

    arg_piso_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2717].groupby('ESTQCOD')['QUANT'].sum()
    arg_piso_val = arg_piso_int.item() if not arg_piso_int.empty else 0
    arg_piso_quant = locale.format_string("%.0f",arg_piso_val,grouping=True) if arg_piso_val > 0 else 0   

    arg_piso_eva_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2718].groupby('ESTQCOD')['QUANT'].sum()
    arg_piso_eva_val = arg_piso_eva_int.item() if not arg_piso_eva_int.empty else 0
    arg_piso_eva_quant = locale.format_string("%.0f",arg_piso_eva_val,grouping=True) if arg_piso_eva_val > 0 else 0

    arg_contrapiso_10mpa_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 25878].groupby('ESTQCOD')['QUANT'].sum()
    arg_contrapiso_10mpa_val = arg_contrapiso_10mpa_int.item() if not arg_contrapiso_10mpa_int.empty else 0
    arg_contrapiso_10mpa_quant = locale.format_string("%.0f",arg_contrapiso_10mpa_val,grouping=True) if arg_contrapiso_10mpa_val > 0 else 0  

    arg_contrapiso_5mpa_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 25877].groupby('ESTQCOD')['QUANT'].sum()
    arg_contrapiso_5mpa_val = arg_contrapiso_5mpa_int.item() if not arg_contrapiso_5mpa_int.empty else 0
    arg_contrapiso_5mpa_quant = locale.format_string("%.0f",arg_contrapiso_5mpa_val,grouping=True) if arg_contrapiso_5mpa_val > 0 else 0

    massa_fina_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2719].groupby('ESTQCOD')['QUANT'].sum()
    massa_fina_val = massa_fina_int.item() if not massa_fina_int.empty else 0
    massa_fina_quant = locale.format_string("%.0f",massa_fina_val,grouping=True) if massa_fina_val > 0 else 0  

    multichapisco_int = consulta_carregamento[consulta_carregamento['ESTQCOD'] == 2729].groupby('ESTQCOD')['QUANT'].sum()
    multichapisco_val = multichapisco_int.item() if not multichapisco_int.empty else 0
    multichapisco_quant = locale.format_string("%.0f",multichapisco_val,grouping=True) if multichapisco_val > 0 else 0 

    response_data = {
        'CONCRECAL CAL + CIMENTO - SC 20 KG':concrecal_cimento_quant,
        'PRIMEX ARGAMASSA ASSENTAMENTO DE ALVENARIA - AAV - SC 20 KG':arg_assent_quant,
        'PRIMEX ARGAMASSA COLANTE AC-I - SC 20 KG':arg_colante_ac1_quant,
        'PRIMEX ARGAMASSA COLANTE AC-II - SC 20 KG':arg_colante_ac2_quant,
        'PRIMEX ARGAMASSA COLANTE AC-III - SC 20 KG':arg_colante_ac3_quant,
        'PRIMEX ARGAMASSA DE PROJECAO - SC 25 KG':arg_projecao_quant,
        'PRIMEX ARGAMASSA DE REVESTIMENTO ARV-I SC 20 KG':arg_rev_arv1_quant,
        'PRIMEX ARGAMASSA DE REVESTIMENTO ARV-II SC 20 KG':arg_rev_arv2_quant,
        'PRIMEX ARGAMASSA DE REVESTIMENTO ARV-III SC 20 KG':arg_rev_arv3_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-12 - SC 20 KG':arg_est_aae12_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-16 - SC 20 KG':arg_est_aae16_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-20 - SC 20 KG':arg_est_aae20_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-5 - SC 20 KG':arg_est_aae5_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-8 - SC 20 KG':arg_est_aae8_quant,
        'PRIMEX ARGAMASSA ESTRUTURAL AAE-ESPECIAL - SC 20 KG':arg_est_aae_esp_quant,
        'PRIMEX ARGAMASSA GROSSA - SC- 25 KG':arg_grossa_quant,
        'PRIMEX ARGAMASSA GROSSA C/ FIBRA - SC 25 KG':arg_grossa_fibra_quant,
        'PRIMEX ARGAMASSA MEDIA - SC 25 KG':arg_media_quant,
        'PRIMEX ARGAMASSA MEDIA C/ FIBRA - SC 25 KG':arg_media_fibra_quant,
        'PRIMEX ARGAMASSA MULTIPLO USO - SC 20 KG': arg_mult_uso_quant,
        'PRIMEX ARGAMASSA P/ PISO - SC 25 KG':arg_piso_quant,
        'PRIMEX ARGAMASSA P/ PISO C/ E.V.A. - SC 25 KG':arg_piso_eva_quant,
        'PRIMEX ARGAMASSA PARA CONTRAPISO 10 MPA - SC 20 KG': arg_contrapiso_10mpa_quant,
        'PRIMEX ARGAMASSA PARA CONTRAPISO 5  MPA - SC 20 KG':arg_contrapiso_5mpa_quant,
        'PRIMEX MASSA FINA - SC 20 KG':massa_fina_quant,
        'PRIMEX MULTICHAPISCO - SC 20 KG':multichapisco_quant,
        #-----------TOTAIS--------------------------------####
        # 'producao_total':producao_total,
        # 'ensacado_total': ensacado_total,
    }
    return JsonResponse(response_data, safe=False)