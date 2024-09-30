from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from django.shortcuts import render
from django.db import connections
import pandas as pd
import locale
from sqlalchemy import create_engine

 # String de conexão
connection_string = 'mssql+pyodbc://DBCONSULTA:DB%40%402023**@172.50.10.5/DB?driver=ODBC+Driver+17+for+SQL+Server'
# Cria a engine
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['GET'])
def calculos_cal(request):
    connection_name = 'sga'
    consulta_ultimo_dia_azbe = pd.read_sql(f"""

        SELECT
            BPROCOD, BPRODATA, ESTQCOD, ESTQNOMECOMP,BPROEQP,BPROHRPROD,BPROHROPER,BPROFPROQUANT,BPROFPRO,
            IBPROQUANT, ((ESTQPESO*IBPROQUANT) /1000) PESO

            FROM BAIXAPRODUCAO
            JOIN ITEMBAIXAPRODUCAO ON BPROCOD = IBPROBPRO
            JOIN ESTOQUE ON ESTQCOD = IBPROREF
            LEFT OUTER JOIN EQUIPAMENTO ON EQPCOD = BPROEQP

            WHERE CAST(BPRODATA as date) BETWEEN CAST (DATEADD (DAY,-2,GETDATE())AS DATE)
                                        AND CAST (GETDATE() AS DATE)

            AND BPROEMP = 1
            AND BPROFIL = 0
            AND BPROSIT = 1
            AND IBPROTIPO = 'D'
            AND BPROEP = 2
            AND BPROFPRO = 27

            ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD,BPROFPRO

            """,engine)
    
        #KPI´S
    to_ton_azbe = round(consulta_ultimo_dia_azbe['PESO'].sum(),1)
    to_ton_azbe = locale.format_string("%.2f",to_ton_azbe,grouping=True)

    response_data = {
            'to_ton_azbe': to_ton_azbe,
        }

    return JsonResponse(response_data, safe=False)