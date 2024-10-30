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
    connection_name = 'sga'
    
    # Recuperando o tipo de cálculo do corpo da requisição
    tipo_calculo = request.data.get('tipo_calculo')

    # Definindo as datas com base no tipo de cálculo
    if tipo_calculo == 'atual':
        data_inicio = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d 07:10:00')
        data_fim = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d 07:10:00')
    elif tipo_calculo == 'mensal':
        data_inicio = datetime.now().strftime('%Y-%m-01 07:10:00')  # Início do mês
        data_fim = datetime.now().strftime('%Y-%m-%d 07:10:10')  # Data atual
    elif tipo_calculo == 'anual':
        data_inicio = datetime.now().strftime('%Y-01-01 07:10:00')  # Início do ano
        data_fim = datetime.now().strftime('%Y-%m-%d 07:10:00')  # Data atual
    else:
        return JsonResponse({'error': 'Tipo de cálculo inválido'}, status=400)

    # Função para realizar a consulta com base no BPROEP
    def consulta_produto(bproep):
        return pd.read_sql(f"""
            SELECT SUM(IBPROQUANT * ISNULL(ESTQPESO, 0) / 1000.0) AS PESO
            FROM BAIXAPRODUCAO
            JOIN ITEMBAIXAPRODUCAO ON BPROCOD = IBPROBPRO
            JOIN ESTOQUE ON ESTQCOD = IBPROREF
            WHERE CAST (BPRODATA AS datetime2) BETWEEN '{data_inicio}' AND '{data_fim}'
            AND BPROEMP = 1 AND BPROFIL = 0 AND BPROSIT = 1
            AND IBPROTIPO = 'D' AND BPROEP = {bproep};
        """, engine)

    # Consultas para diferentes produtos com BPROEP fixos
    produtos = {
        'cal': consulta_produto(3),
        'calcario': consulta_produto(6),
        'fertilizante': consulta_produto(8),
        'argamassa': consulta_produto(1),
        # 'produto4': consulta_produto(4),
        # 'produto9': consulta_produto(9),
    }

    # Formatando os resultados
    for key in produtos:
        produtos[key] = locale.format_string("%.0f", produtos[key]['PESO'].sum(), grouping=True)

    # Adicionando a nova consulta
    consulta_rom = pd.read_sql(f"""
        SELECT 
            C.PPDADOCHAR CLIMA, 
            M.PPDADOCHAR MATERIAL, 
            SUM(CAL.P) CAL, 
            SUM(CALCARIO.P) CALCARIO, 
            SUM(DPRHRPROD) HR, 
            (ISNULL(SUM(CAL.P), 0) + ISNULL(SUM(CALCARIO.P), 0)) / CASE WHEN SUM(DPRHRPROD) = 0 THEN 1 ELSE SUM(DPRHRPROD) END TN_HR
        FROM DIARIAPROD DPR
        LEFT OUTER JOIN PESPARAMETRO C ON C.PPTPP = 4 AND C.PPREF = DPR.DPRCOD 
        LEFT OUTER JOIN PESPARAMETRO M ON M.PPTPP = 5 AND M.PPREF = DPR.DPRCOD 
        OUTER APPLY(
            SELECT SUM(ADTRPESOTOT) P 
            FROM ALIMDIARIATRANSP
            JOIN ITEMDIARIATRANSP ON IDTRCOD = ADTRIDTR
            JOIN DIARIATRANSP ON DTRCOD = IDTRDTR
            JOIN LOCAL LD ON LD.LOCCOD = ADTRLOC
            JOIN PRODUCAOPRODUTO ON PPROCOD = LOCPPRO
            WHERE DTRSIT = 1
            AND IDTRTIPODEST = 1
            AND DTREMP = DPR.DPREMP
            AND DTRFIL = DPR.DPRFIL
            AND IDTRDPR = DPR.DPRCOD
            AND CAST(DTRDATA1 as date) BETWEEN '{data_inicio}' AND '{data_fim}'
            AND PPROCOD = 4) CAL
        OUTER APPLY(
            SELECT SUM(ADTRPESOTOT) P 
            FROM ALIMDIARIATRANSP
            JOIN ITEMDIARIATRANSP ON IDTRCOD = ADTRIDTR
            JOIN DIARIATRANSP ON DTRCOD = IDTRDTR
            JOIN LOCAL LD ON LD.LOCCOD = ADTRLOC
            JOIN PRODUCAOPRODUTO ON PPROCOD = LOCPPRO
            WHERE DTRSIT = 1
            AND IDTRTIPODEST = 1
            AND DTREMP = DPR.DPREMP
            AND DTRFIL = DPR.DPRFIL
            AND IDTRDPR = DPR.DPRCOD
            AND CAST(DTRDATA1 as date) BETWEEN '{data_inicio}' AND '{data_fim}'
            AND PPROCOD = 5) CALCARIO
        WHERE DPRSIT = 1
        AND DPREMP = 1
        AND DPRFIL = 0
        AND CAST(DPRDATA1 as date) BETWEEN '{data_inicio}' AND '{data_fim}'
        AND DPREQP = 66
        GROUP BY C.PPDADOCHAR, M.PPDADOCHAR
    """, engine)

    #REBRITAGEM

    consulta_volume_britado = pd.read_sql(f"""
        SELECT 0 TIPO, DPRCOD, DPRREF, EQPCOD, EQPNOME, LOCCOD, LOCNOME, SUM(ADPRPESOTOT) TOTAL, (DPRHROPER) TOTAL_HORAS FROM ALIMDIARIAPROD
            JOIN DIARIAPROD ON DPRCOD = ADPRDPR
            JOIN LOCAL LD ON LD.LOCCOD = ADPRLOC
            JOIN EQUIPAMENTO ON EQPCOD = DPREQP
            WHERE DPRSIT = 1
            AND DPREMP = 1
            AND DPRFIL = 0
            AND CAST(DPRDATA1 as date) BETWEEN '{data_inicio}' AND '{data_fim}'
            AND ADPRLOC <> 0

            GROUP BY EQPNOME, EQPCOD, LOCCOD, LOCNOME, DPRCOD, DPRREF, DPRHROPER

            UNION

            SELECT 0 TIPO, DPRCOD, DPRREF, EQPCOD, EQPNOME, LOCCOD, LOCNOME, SUM(ADTRPESOTOT) TOTAL, (DPRHRPROD) TOTAL_HORAS FROM ALIMDIARIATRANSP
            JOIN ITEMDIARIATRANSP ON IDTRCOD = ADTRIDTR
            JOIN DIARIATRANSP ON DTRCOD = IDTRDTR
            JOIN LOCAL LD ON LD.LOCCOD = ADTRLOC
            JOIN DIARIAPROD ON DPRCOD = IDTRDPR
            JOIN EQUIPAMENTO ON EQPCOD = DPREQP
            WHERE DTRSIT = 1
            AND CAST(DTRDATA1 as date) BETWEEN '{data_inicio}' AND '{data_fim}'
            AND IDTRTIPODEST = 1
            AND DTREMP = 1
            AND DTRFIL = 0

            GROUP BY EQPNOME, EQPCOD, LOCCOD, LOCNOME, DPRCOD, DPRREF, DPRHRPROD

            ORDER BY 5,7
                             """,engine)

    
    #volume_britado_por_loc = locale.format_string("%.2f",consulta_volume_britado.groupby('LOCCOD')['TOTAL'].sum(),grouping=True)
  
    # Primeiro, arredonde os valores da Series para 2 casas decimais
    volume_britado_por_loc = consulta_volume_britado.groupby('LOCCOD')['TOTAL'].sum()
    volume_britado_por_loc = volume_britado_por_loc.reindex([44, 62, 66], fill_value=0)
    # Em seguida, aplique a formatação local a cada valor da Series
    volume_britado_por_loc_formatado = volume_britado_por_loc.apply(lambda x: locale.format_string("%.0f", x, grouping=True))

    volume_britado_por_loc_formatado = volume_britado_por_loc_formatado.to_dict()
    



    # Somando os valores dos códigos 44, 62 e 66
    volume_britado_total = round(volume_britado_por_loc.loc[[44, 62, 66]].sum(),2)
    
    volume_britado_total = locale.format_string("%.0f",volume_britado_total,grouping=True)
    # Convertendo para dicionário para serialização
    volume_britado_dict = volume_britado_por_loc.to_dict()
    
    producao_britador = round(volume_britado_por_loc.loc[[44, 62]].sum(),2)
    producao_britador = locale.format_string("%.0f",producao_britador,grouping=True)
    

    rom_calcario_dia = round(consulta_rom['CALCARIO'].sum(),2)
    rom_cal_dia = round(consulta_rom['CAL'].sum(),2)
    vol_brit = rom_cal_dia + rom_calcario_dia
    vol_brit = locale.format_string("%.0f",vol_brit,grouping=True)    

    response_data = {
        'producao_britador': producao_britador,
        'volume_britado_total': volume_britado_total,
        
        'vol_brit':vol_brit,
        'resultados': produtos,
        'tipo_calculo': tipo_calculo,
        'volume_britado':volume_britado_por_loc_formatado
    }

    return JsonResponse(response_data, safe=False)