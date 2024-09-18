from datetime import datetime, timedelta  # Importa as classes necessárias
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
import pandas as pd
import locale


locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')  # Exemplo de locale brasileiro

@csrf_exempt
@api_view(['POST'])
def calculos_calcario(request):
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

    consulta_fcm1 = pd.read_sql(f"""

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
            """,connections[connection_name])

    #KPI´S
    total_fcm1 = consulta_fcm1['PESO'].sum()
    total_fcm1_formatado = locale.format_string("%.0f",total_fcm1,grouping=True)

    #HS
    tot_hs_dia = consulta_fcm1['BPROHRPROD'].sum()
    if tot_hs_dia != 0 :
        tn_hora_dia_fcm1 = total_fcm1 / tot_hs_dia
    else:
        tn_hora_dia_fcm1 = 0
    tn_hora_dia_fcm1 = locale.format_string("%.2f",tn_hora_dia_fcm1,grouping=True)

    response_data = {
        'total_fcm1':total_fcm1_formatado,
        'tn_hora_dia_fcm1':tn_hora_dia_fcm1
    }

    return JsonResponse(response_data)