from django.shortcuts import render
from datetime import datetime, timedelta
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
import pandas as pd
import locale
from sqlalchemy import create_engine

locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')

connection_string = 'mssql+pyodbc://DBCONSULTA:DB%40%402023**@172.50.10.5/DB?driver=ODBC+Driver+17+for+SQL+Server'
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['POST'])
def calculos_fertilizante(request):
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
    
    consulta_fertilizante = pd.read_sql(f"""
        SELECT BPROCOD, BPRODATA, ESTQCOD, ESTQNOMECOMP,BPROHRPROD, 
        IBPROQUANT,BPROEP,IBPROREF, ((ESTQPESO*IBPROQUANT) /1000) PESO

        FROM BAIXAPRODUCAO
        JOIN ITEMBAIXAPRODUCAO ON BPROCOD = IBPROBPRO
        JOIN ESTOQUE ON ESTQCOD = IBPROREF
        LEFT OUTER JOIN EQUIPAMENTO ON EQPCOD = BPROEQP

        WHERE CAST (BPRODATA1 as datetime2) BETWEEN '{data_inicio}' AND '{data_fim}'
        AND BPROEMP = 1
        AND BPROFIL = 0
        AND BPROSIT = 1
        AND IBPROTIPO = 'D'
        
        AND EQPLOC = 52
        ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD
            """,engine)
    
    #KPI's ensacados
    #S-10 Big Bag
    big_bag_s10_quant_int = consulta_fertilizante[consulta_fertilizante['ESTQCOD'] == 8].groupby('ESTQCOD')['IBPROQUANT'].sum()
    big_bag_s10_quant_val = big_bag_s10_quant_int.item() if not big_bag_s10_quant_int.empty else 0
    big_bag_s10_quant = locale.format_string("%.1f",big_bag_s10_quant_val,grouping=True) if big_bag_s10_quant_val > 0 else 0
    #S-10 50KG
    sc50_s10_quant_int = consulta_fertilizante[consulta_fertilizante['ESTQCOD'] == 2].groupby('ESTQCOD')['IBPROQUANT'].sum()
    sc50_s10_quant_val = sc50_s10_quant_int.item() if not sc50_s10_quant_int.empty else 0
    sc50_s10_quant = locale.format_string("%.1f",sc50_s10_quant_val,grouping=True) if sc50_s10_quant_val > 0 else 0
    #DB CA S
    db_ca_s_granel_int = consulta_fertilizante[consulta_fertilizante['ESTQCOD'] == 3].groupby('ESTQCOD')['IBPROQUANT'].sum()
    db_ca_s_granel_val = db_ca_s_granel_int.item() if not db_ca_s_granel_int.empty else 0
    db_ca_s_granel = locale.format_string("%.1f",db_ca_s_granel_val,grouping=True) if db_ca_s_granel_val > 0 else 0

    #-------------------------------------------------PRODUÇÃO TOTAL DA FÁBRICA----------------------------------------------------
    total_fabrica_fertilizante_int = consulta_fertilizante['PESO'].sum()
    total_fabrica_fertilizante = locale.format_string("%.1f",total_fabrica_fertilizante_int,grouping=True) if total_fabrica_fertilizante_int > 0 else 0

    ####----------------------PRODUTIVIDADE--------------------##################################
    #HS
    tot_hs = consulta_fertilizante['BPROHRPROD'].sum()
    if tot_hs != 0 :
        tn_hora = total_fabrica_fertilizante_int / tot_hs
    else:
        tn_hora = 0
    tn_hora = locale.format_string("%.2f",tn_hora,grouping=True)
    tot_hs = locale.format_string("%.2f",tot_hs,grouping=True)

    #----------------------------------------------ESTOQUE--------------------------
    #consulta da posição do estoque
    data_estoque = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d 07:10:00')
    consulta_estoque = pd.read_sql(f"""

            SELECT DISTINCT ESTQNOME, ESTQCOD, DADOS.DT DATA, EMPCOD EMPRESA, QESTQFIL FILIAL,
            QUANTESTOQUE, QUANTMOV, (QUANTESTOQUE - QUANTMOV) SALDO,
            ((QUANTESTOQUE * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000) QUANTESTOQUETN,
            ((QUANTMOV * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000) QUANTMOVTN,
            ((QUANTESTOQUE * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000) -
            ((QUANTMOV * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000) SALDOTN
        FROM (
            SELECT CAST('{data_estoque}' as date) AS DT
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
            AND CAST(MESTQDATA as date) = '{data_estoque}'
            GROUP BY MESTQESTQ, MESTQEMP, MESTQFIL
        ) MOV ON MOV.MESTQESTQ = EQ.ESTQCOD
            AND MOV.MESTQEMP = EE.EMPCOD 
            AND MOV.MESTQFIL = QESTQ.QESTQFIL

        WHERE EE.EMPCOD = 1
        AND COALESCE(QESTQFIL, 0) = 0 
        AND ESTQGALM = 1828
        AND MOV.MOVCOUNT > 0 -- Usa o resultado do JOIN ao invés da subquery
        AND (SELECT COUNT(*) FROM GRUPOALMOXARIFADO WHERE GALMCOD = EQ.ESTQGALM AND GALMPRODVENDA = 'S') > 0  /*&PRODVENDA*/
        ORDER BY ESTQNOME, DATA;

            """,engine)

    #KPI'S
    #S-10 BIG BAG
    estoque_s10_big_bag_int = consulta_estoque[consulta_estoque['ESTQCOD'] == 8].groupby('ESTQCOD')['SALDO'].sum()
    estoque_s10_big_bag_val = estoque_s10_big_bag_int.item() if not estoque_s10_big_bag_int.empty else 0
    estoque_s10_big_bag = locale.format_string("%.1f",estoque_s10_big_bag_val,grouping=True)if estoque_s10_big_bag_val > 0 else 0
    #S-10 50KG
    #S-10 BIG BAG
    estoque_s10_sc50_int = consulta_estoque[consulta_estoque['ESTQCOD'] == 2].groupby('ESTQCOD')['SALDO'].sum()
    estoque_s10_sc50_val = estoque_s10_sc50_int.item() if not estoque_s10_sc50_int.empty else 0
    estoque_s10_sc50 = locale.format_string("%.1f",estoque_s10_sc50_val,grouping=True)if estoque_s10_sc50_val > 0 else 0
    #DB CA S GRANEL
    estoque_db_ca_s_granel_int = consulta_estoque[consulta_estoque['ESTQCOD'] == 3].groupby('ESTQCOD')['SALDO'].sum()
    estoque_db_ca_s_granel_val = estoque_db_ca_s_granel_int.item() if not estoque_db_ca_s_granel_int.empty else 0
    estoque_db_ca_s_granel = locale.format_string("%.1f",estoque_db_ca_s_granel_val,grouping=True)if estoque_db_ca_s_granel_val > 0 else 0

    #######-------------Carregamento Geral (movimentação)--------------------------------------
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
        AND ESTQCOD IN (2,3,8,128,7985)

    ORDER BY NFDATA, NFNUM
                 """,engine)

    #KPI'S
    total_movimentacao = consulta_movimentacao['QUANT'].sum()
    total_movimentacao = locale.format_string("%.1f",total_movimentacao, grouping=True)

    

    response_data = {
        'big_bag_s10_quant': big_bag_s10_quant,
        'sc50_s10_quant': sc50_s10_quant,
        'db_ca_s_granel': db_ca_s_granel,
        'total_fabrica_fertilizante': total_fabrica_fertilizante,
        'estoque_s10': estoque_s10_big_bag,
        'estoque_s10_sc50': estoque_s10_sc50,
        'estoque_db_ca_s_granel': estoque_db_ca_s_granel,
        'total_movimentacao':total_movimentacao,
        'tn_hora':tn_hora,
        'tot_hs':tot_hs
    }

    return JsonResponse(response_data,safe=False)

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

    consulta_ferilizante = pd.read_sql(f"""
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
                AND EQPLOC = 52
                AND ({meses_condition})
                ORDER BY BPRODATA, BPROCOD, ESTQNOMECOMP, ESTQCOD
            """,engine)
    
    total = consulta_ferilizante['PESO'].sum()
    return JsonResponse({'total': total}, status=200)