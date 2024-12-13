from django.shortcuts import render
from datetime import datetime, timedelta
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
from sqlalchemy import create_engine
import pandas as pd
import locale

locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')  # br

# String de conexão
connection_string = 'mssql+pyodbc://DBCONSULTA:DB%40%402023**@172.50.10.5/DB?driver=ODBC+Driver+17+for+SQL+Server'
# Cria a engine
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['POST'])
def calculos_realizado(request):
    cc = request.data.get('cc')
    #data_inicio = datetime.now().strftime('%Y-01-01 07:10:00')
    #data_fim = datetime.now().strftime('%Y-%m-%d 23:59:00')
    data_inicio = "2024-01-01"
    data_fim = "2024-11-30"
    conta = '4%'
    conta1 = '3401%'
    conta2 = '3402%'

    consulta_realizado = pd.read_sql(f"""

        
            WITH LANCAMENTOS_BASE AS (
                SELECT 
                    LC.LANCCOD, 
                    LC.LANCDATA, 
                    '''' + LC.LANCDEB AS CONTA_DEB, 
                    (SELECT PCNOME FROM PLANO WHERE PCCONTA = LC.LANCDEB) AS CONTA_NOME_DEB,
                    '''' + LC.LANCCRED AS CONTA_CRED, 
                    (SELECT PCNOME FROM PLANO WHERE PCCONTA = LC.LANCCRED) AS CONTA_NOME_CRED,
                    CCNOMECOMP,
                    CCSTCOD,
                    LC.LANCVALOR,
                    LC.LANCHIST,
                    LC.LANCCOMP,
                    LC.LANCTIPOREF,
                    LC.LANCREF,
                    LC.LANCSIT,
                    LC.LANCFIL,
                    LC.LANCEMP
                FROM LANCAMENTO LC
                LEFT OUTER JOIN CENTROCUSTO ON CCCOD = LC.LANCCC
                WHERE 
                    CAST(LC.LANCDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
                    AND LC.LANCEMP = 1
                    AND LANCSIT = 0
                    AND CCSTCOD LIKE '%' + '{cc}' + '%'
                    AND (
                        LC.LANCCRED LIKE '{conta}'
                        OR LC.LANCCRED LIKE '{conta1}'
                        OR LC.LANCCRED LIKE '{conta2}'
                        OR LC.LANCDEB LIKE '{conta}'
                        OR LC.LANCDEB LIKE '{conta1}'
                        OR LC.LANCDEB LIKE '{conta2}'
                    )
            )
            
            SELECT 
                LANCCOD, 
                LANCDATA, 
                CONTA_DEB, 
                CONTA_NOME_DEB, 
                CONTA_CRED, 
                CONTA_NOME_CRED,
                CCNOMECOMP,
                CCSTCOD, 
                LANCVALOR AS DEB_VALOR, 
                0.00 AS CRED_VALOR, 
                'AUT' AS TIPO,
                CASE 
                    WHEN LANCTIPOREF = 14 THEN 
                        (SELECT TREGNOME 
                        FROM TIPOREGISTRO
                        JOIN REGISTRO ON REGTREG = TREGCOD
                        WHERE REGCOD = LANCREF)
                    ELSE 
                        (SELECT REFNOME FROM REFERENCIA WHERE REFCOD = LANCTIPOREF)
                END AS REFERENCIA, 
                LANCREF,
                (SELECT HISTMASCARA FROM HISTORICO WHERE HISTCOD = LANCHIST) + ' ' + LANCCOMP AS HISTORICO,
                CASE 
                    WHEN LANCSIT = 0 THEN 'ATIVO' 
                    WHEN LANCSIT = 1 THEN 'CANCELADO' 
                    ELSE '?????' 
                END AS SITUACAO,
                CASE 
                    WHEN LANCFIL = 0 THEN (SELECT EMPSIGLA FROM EMPRESA WHERE EMPCOD = LANCEMP) 
                    ELSE (SELECT FILSIGLA FROM FILIAL WHERE FILCOD = LANCFIL) 
                END AS UNIDADE
            FROM LANCAMENTOS_BASE

            UNION

            SELECT 
                LANCCOD, 
                LANCDATA, 
                CONTA_DEB, 
                CONTA_NOME_DEB, 
                CONTA_CRED, 
                CONTA_NOME_CRED,
                CCNOMECOMP,
                CCSTCOD, 
                0.00 AS DEB_VALOR, 
                -LANCVALOR AS CRED_VALOR, 
                'AUT' AS TIPO,
                CASE 
                    WHEN LANCTIPOREF = 14 THEN 
                        (SELECT TREGNOME 
                        FROM TIPOREGISTRO
                        JOIN REGISTRO ON REGTREG = TREGCOD
                        WHERE REGCOD = LANCREF)
                    ELSE 
                        (SELECT REFNOME FROM REFERENCIA WHERE REFCOD = LANCTIPOREF)
                END AS REFERENCIA, 
                LANCREF,
                (SELECT HISTMASCARA FROM HISTORICO WHERE HISTCOD = LANCHIST) + ' ' + LANCCOMP AS HISTORICO,
                CASE 
                    WHEN LANCSIT = 0 THEN 'ATIVO' 
                    WHEN LANCSIT = 1 THEN 'CANCELADO' 
                    ELSE '?????' 
                END AS SITUACAO,
                CASE 
                    WHEN LANCFIL = 0 THEN (SELECT EMPSIGLA FROM EMPRESA WHERE EMPCOD = LANCEMP) 
                    ELSE (SELECT FILSIGLA FROM FILIAL WHERE FILCOD = LANCFIL) 
                END AS UNIDADE
            FROM LANCAMENTOS_BASE
                
                
""",engine)
    
    consulta_realizado['SALDO'] = consulta_realizado.apply(
    lambda row: row["DEB_VALOR"] if row["CONTA_DEB"][1] in ['3', '4'] else row["CRED_VALOR"],
    axis=1
)
    #total = int(consulta_realizado['SALDO'])
    total = consulta_realizado['SALDO'].sum()
    total = locale.format_string("%.0f",total, grouping=True)

    

    #Converte o DataFrame em um formato JSON serializável
    data_json = {
        'total': total,
        'respostas':consulta_realizado.to_dict(orient='records')
        }
    
    # Retorna o JSON como resposta
    return JsonResponse(data_json, safe=False)
