from datetime import datetime, timedelta  # Importa as classes necessárias
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
import pandas as pd
import locale
import numpy as np
from sqlalchemy import create_engine

locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')  # Exemplo de locale brasileiro

 # String de conexão
connection_string = 'mssql+pyodbc://DBCONSULTA:DB%40%402023**@172.50.10.5/DB?driver=ODBC+Driver+17+for+SQL+Server'
# Cria a engine
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['POST'])
def calculos_britagem(request):
    connection_name = 'sga'
    
    # Recuperando o tipo de cálculo do corpo da requisição
    tipo_calculo = request.data.get('tipo_calculo')

    # Definindo as datas com base no tipo de cálculo
    if tipo_calculo == 'atual':
        data_inicio = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d 07:10:00')
        data_fim = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d 07:09:00')
    elif tipo_calculo == 'mensal':
        data_inicio = datetime.now().strftime('%Y-%m-01 07:10:00')  # Início do mês
        data_fim = datetime.now().strftime('%Y-%m-%d 07:09:00')  # Data atual
    elif tipo_calculo == 'anual':
        data_inicio = datetime.now().strftime('%Y-01-01 07:10:00')  # Início do ano
        data_fim = datetime.now().strftime('%Y-%m-%d 07:09:00')  # Data atual
    else:
        return JsonResponse({'error': 'Tipo de cálculo inválido'}, status=400)

    
    consulta_evento_parada = pd.read_sql(f"""

    SELECT 
    CASE
    WHEN EDPROPERSN = 'N' THEN 'Parado'
    WHEN EDPROPERSN = 'S' THEN 'Operando'
    ELSE '????'
    END EDPROPERSN,
    EDPREVD,EVDNOME, SUM(EDPRHRTOT*3600) TEMPO,

    (SUM(EDPRHRTOT*3600) / (SELECT SUM(EDPRHRTOT*3600)
                            FROM DIARIAPROD
                            JOIN EVENTODIARIAPROD ON EDPRDPR = DPRCOD
                            WHERE
                              CAST(DPRDATA1 as datetime2) BETWEEN '{data_inicio}' AND '{data_fim}'
                            AND DPRSIT = 1
                            AND DPREMP = 1
                            AND DPRFIL = 0
                            AND DPREQP = DPR.DPREQP)) * 100 PERC_TOTAL

    FROM DIARIAPROD DPR
    JOIN EQUIPAMENTO ON EQPCOD = DPREQP
    JOIN EVENTODIARIAPROD ON EDPRDPR = DPRCOD
    JOIN EVENTODIARIA ON EVDCOD = EDPREVD

    WHERE 
      CAST(DPRDATA1 as datetime2) BETWEEN '{data_inicio}' AND '{data_fim}'
    AND DPRSIT = 1
    AND DPREMP =1
    AND DPRFIL = 0
    AND EQPAPLIC = 'P'
    AND EQPCOD = 66


GROUP BY EDPREVD, EVDNOME, EDPROPERSN, DPREQP

    """,engine)

    ##KPI´S PARADAS

 ###########--ALMOÇO E JANTA ######################
    des = consulta_evento_parada.loc[consulta_evento_parada['EDPREVD']==6,['TEMPO','PERC_TOTAL']]
    almoco_janta_percentual = des['PERC_TOTAL'].values
    if almoco_janta_percentual != 0:
        almoco_janta_percentual = ', '.join(map(str, almoco_janta_percentual))
        almoco_janta_percentual = round(float(almoco_janta_percentual),1)
    else:
        almoco_janta_percentual = 0
    almoco_janta_tempo = des['TEMPO'].values
    if almoco_janta_tempo != 0:
        almoco_janta_tempo = ', '.join(map(str, almoco_janta_tempo))
        almoco_janta_tempo_hours = float(almoco_janta_tempo) / 3600
        total_minutes = round(almoco_janta_tempo_hours * 60)

         # Calcula horas e minutos restantes
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            almoco_janta_tempo = f'{int(hours)}h {int(minutes)}m'  # Converte para int para evitar decimais
        else:
            almoco_janta_tempo = f'{int(minutes)}m'
    else:    
        almoco_janta_tempo = '0m'

###########--EMBUCHAMENTO(ROMPEDOR) ######################
    des = consulta_evento_parada.loc[consulta_evento_parada['EDPREVD']==72,['TEMPO','PERC_TOTAL']]
    embuchamento_rompedor_percentual = des['PERC_TOTAL'].values
    if embuchamento_rompedor_percentual != 0:
        embuchamento_rompedor_percentual = ', '.join(map(str, embuchamento_rompedor_percentual))
        embuchamento_rompedor_percentual = round(float(embuchamento_rompedor_percentual),1)
    else:
        embuchamento_rompedor_percentual = 0
    embuchamento_rompedor_tempo = des['TEMPO'].values
    if embuchamento_rompedor_tempo != 0:
        embuchamento_rompedor_tempo = ', '.join(map(str, embuchamento_rompedor_tempo))
        embuchamento_rompedor_tempo_hours = float(embuchamento_rompedor_tempo) / 3600
        total_minutes = round(embuchamento_rompedor_tempo_hours * 60)

         # Calcula horas e minutos restantes
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            embuchamento_rompedor_tempo = f'{int(hours)}h {int(minutes)}m'  # Converte para int para evitar decimais
        else:
            embuchamento_rompedor_tempo = f'{int(minutes)}m'
    else:    
        embuchamento_rompedor_tempo = '0m'

###########--EMBUCHAMENTO(DESARME) ######################
    des = consulta_evento_parada.loc[consulta_evento_parada['EDPREVD']==26,['TEMPO','PERC_TOTAL']]
    embuchamento_desarme_percentual = des['PERC_TOTAL'].values
    if embuchamento_desarme_percentual != 0:
        embuchamento_desarme_percentual = ', '.join(map(str, embuchamento_desarme_percentual))
        embuchamento_desarme_percentual = round(float(embuchamento_desarme_percentual),1)
    else:
        embuchamento_rompedor_percentual = 0
    embuchamento_desarme_tempo = des['TEMPO'].values
    if embuchamento_desarme_tempo != 0:
        embuchamento_desarme_tempo = ', '.join(map(str, embuchamento_desarme_tempo))
        embuchamento_desarme_tempo_hours = float(embuchamento_desarme_tempo) / 3600
        total_minutes = round(embuchamento_desarme_tempo_hours * 60)

         # Calcula horas e minutos restantes
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            embuchamento_desarme_tempo = f'{int(hours)}h {int(minutes)}m'  # Converte para int para evitar decimais
        else:
            embuchamento_desarme_tempo = f'{int(minutes)}m'
    else:    
        embuchamento_desarme_tempo = '0m'  

###########--SETUP------- ######################
    des = consulta_evento_parada.loc[consulta_evento_parada['EDPREVD']==27,['TEMPO','PERC_TOTAL']]
    setup_percentual = des['PERC_TOTAL'].values
    if setup_percentual != 0:
        setup_percentual = ', '.join(map(str, setup_percentual))
        setup_percentual = round(float(setup_percentual),1)
    else:
        setup_percentual = 0
    setup_tempo = des['TEMPO'].values
    if setup_tempo != 0:
        setup_tempo = ', '.join(map(str, setup_tempo))
        setup_tempo_hours = float(setup_tempo) / 3600
        total_minutes = round(setup_tempo_hours * 60)

         # Calcula horas e minutos restantes
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            setup_tempo = f'{int(hours)}h {int(minutes)}m'  # Converte para int para evitar decimais
        else:
            setup_tempo = f'{int(minutes)}m'
    else:    
        setup_tempo = '0m'  


###########--FALTA MATERIA PRIMA------- ######################
    des = consulta_evento_parada.loc[consulta_evento_parada['EDPREVD']==14,['TEMPO','PERC_TOTAL']]
    materiaprima_percentual = des['PERC_TOTAL'].values
    if materiaprima_percentual != 0:
        materiaprima_percentual = ', '.join(map(str, materiaprima_percentual))
        materiaprima_percentual = round(float(materiaprima_percentual),1)
    else:
        materiaprima_percentual = 0
    materiaprima_tempo = des['TEMPO'].values
    if materiaprima_tempo != 0:
        materiaprima_tempo = ', '.join(map(str, materiaprima_tempo))
        materiaprima_tempo_hours = float(materiaprima_tempo) / 3600
        total_minutes = round(materiaprima_tempo_hours * 60)

         # Calcula horas e minutos restantes
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            materiaprima_tempo = f'{int(hours)}h {int(minutes)}m'  # Converte para int para evitar decimais
        else:
            materiaprima_tempo = f'{int(minutes)}m'
    else:    
        materiaprima_tempo = '0m'    

###########--ESPERANDO DEMANDA------- ######################
    des = consulta_evento_parada.loc[consulta_evento_parada['EDPREVD']==12,['TEMPO','PERC_TOTAL']]
    esperando_demanda_percentual = des['PERC_TOTAL'].values
    if esperando_demanda_percentual != 0:
        esperando_demanda_percentual = ', '.join(map(str, esperando_demanda_percentual))
        esperando_demanda_percentual = round(float(esperando_demanda_percentual),1)
    else:
        esperando_demanda_percentual = 0
    esperando_demanda_tempo = des['TEMPO'].values
    if esperando_demanda_tempo != 0:
        esperando_demanda_tempo = ', '.join(map(str, esperando_demanda_tempo))
        esperando_demanda_tempo_hours = float(esperando_demanda_tempo) / 3600
        total_minutes = round(esperando_demanda_tempo_hours * 60)

         # Calcula horas e minutos restantes
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            esperando_demanda_tempo = f'{int(hours)}h {int(minutes)}m'  # Converte para int para evitar decimais
        else:
            esperando_demanda_tempo = f'{int(minutes)}m'
    else:    
        esperando_demanda_tempo = '0m'  

###########--PREPARANDO LOCAL------- ######################
    des = consulta_evento_parada.loc[consulta_evento_parada['EDPREVD']==9,['TEMPO','PERC_TOTAL']]
    preparando_local_percentual = des['PERC_TOTAL'].values
    if preparando_local_percentual != 0:
        preparando_local_percentual = ', '.join(map(str, preparando_local_percentual))
        preparando_local_percentual = round(float(preparando_local_percentual),1)
    else:
        preparando_local_percentual = 0
    preparando_local_tempo = des['TEMPO'].values
    if preparando_local_tempo != 0:
        preparando_local_tempo = ', '.join(map(str, preparando_local_tempo))
        preparando_local_tempo_hours = float(preparando_local_tempo) / 3600
        total_minutes = round(preparando_local_tempo_hours * 60)

         # Calcula horas e minutos restantes
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            preparando_local_tempo = f'{int(hours)}h {int(minutes)}m'  # Converte para int para evitar decimais
        else:
            preparando_local_tempo = f'{int(minutes)}m'
    else:    
        preparando_local_tempo = '0m'

###########--ALIMENTADOR DESLIGADO------- ######################
    des = consulta_evento_parada.loc[consulta_evento_parada['EDPREVD']==53,['TEMPO','PERC_TOTAL']]
    alimentador_desligado_percentual = des['PERC_TOTAL'].values
    if alimentador_desligado_percentual != 0:
        alimentador_desligado_percentual = ', '.join(map(str, alimentador_desligado_percentual))
        alimentador_desligado_percentual = round(float(alimentador_desligado_percentual),1)
    else:
        alimentador_desligado_percentual = 0
    alimentador_desligado_tempo = des['TEMPO'].values
    if alimentador_desligado_tempo != 0:
        alimentador_desligado_tempo = ', '.join(map(str, alimentador_desligado_tempo))
        alimentador_desligado_tempo_hours = float(alimentador_desligado_tempo) / 3600
        total_minutes = round(alimentador_desligado_tempo_hours * 60)

         # Calcula horas e minutos restantes
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            alimentador_desligado_tempo = f'{int(hours)}h {int(minutes)}m'  # Converte para int para evitar decimais
        else:
            alimentador_desligado_tempo = f'{int(minutes)}m'
    else:    
        alimentador_desligado_tempo = '0m'

###########--EVENTO NAO INFORMADO------- ######################
    des = consulta_evento_parada.loc[consulta_evento_parada['EDPREVD']==28,['TEMPO','PERC_TOTAL']]
    evento_nao_informado_percentual = des['PERC_TOTAL'].values
    if evento_nao_informado_percentual != 0:
        evento_nao_informado_percentual = ', '.join(map(str, evento_nao_informado_percentual))
        evento_nao_informado_percentual = round(float(evento_nao_informado_percentual),1)
    else:
        evento_nao_informado_percentual = 0
    evento_nao_informado_tempo = des['TEMPO'].values
    if evento_nao_informado_tempo != 0:
        evento_nao_informado_tempo = ', '.join(map(str, evento_nao_informado_tempo))
        evento_nao_informado_tempo_hours = float(evento_nao_informado_tempo) / 3600
        total_minutes = round(evento_nao_informado_tempo_hours * 60)

         # Calcula horas e minutos restantes
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            evento_nao_informado_tempo = f'{int(hours)}h {int(minutes)}m'  # Converte para int para evitar decimais
        else:
            evento_nao_informado_tempo = f'{int(minutes)}m'
    else:    
        evento_nao_informado_tempo = '0m'


################################################################################################

    consulta_mov = pd.read_sql(f"""
        SELECT 
            DTRREF AS DIARIA, 
            DTRDATA1 AS INICIO, 
            DTRDATA2 AS FIM, 
            EQPCOD,
            CASE 
                WHEN EQPAUTOMTAG LIKE '' OR EQPAUTOMTAG IS NULL 
                THEN EQPNOME 
                ELSE EQPAUTOMTAG 
            END AS EQUIPAMENTO,

            ISNULL(L3.LOCNOME + '>>', '') + ISNULL(L2.LOCNOME + '>>', '') + ISNULL(L1.LOCNOME, '') AS ORIGEM,
			  
			  -- Colunas separadas para os códigos dos locais
			L3.LOCCOD AS LOCCOD_L3,
			L2.LOCCOD AS LOCCOD_L2,
			L1.LOCCOD AS LOCCOD_L1,

           -- DESTINO com LOCNOME concatenado e LOCCOD em colunas separadas
    CASE
        WHEN IDTRTIPODEST = 1 
        THEN (SELECT 
                CASE 
                    WHEN EQPAUTOMTAG LIKE '' OR EQPAUTOMTAG IS NULL 
                    THEN EQPNOME 
                    ELSE EQPAUTOMTAG 
                END 
              FROM EQUIPAMENTO
              WHERE EQPCOD = IDTR.IDTRDESTINO)
        ELSE (SELECT 
                ISNULL(LOCNOME_L3 + '>>', '') + ISNULL(LOCNOME_L2 + '>>', '') + ISNULL(LOCNOME_L1, '')
              FROM (
                  SELECT 
                      L1_SUB.LOCNOME AS LOCNOME_L1, 
                      L2_SUB.LOCNOME AS LOCNOME_L2, 
                      L3_SUB.LOCNOME AS LOCNOME_L3, 
                      L1_SUB.LOCCOD AS LOCCOD_L1, 
                      L2_SUB.LOCCOD AS LOCCOD_L2, 
                      L3_SUB.LOCCOD AS LOCCOD_L3
                  FROM 
                      LOCAL L1_SUB
                  LEFT OUTER JOIN 
                      LOCAL L2_SUB ON L2_SUB.LOCCOD = L1_SUB.LOCLOCPAI
                  LEFT OUTER JOIN 
                      LOCAL L3_SUB ON L3_SUB.LOCCOD = L2_SUB.LOCLOCPAI
                  WHERE 
                      L1_SUB.LOCCOD = IDTR.IDTRDESTINO
              ) AS SUBQUERY_DESTINO)
    END AS DESTINO,
    (SELECT LOCCOD_L3 FROM (
        SELECT 
            L3_SUB.LOCCOD AS LOCCOD_L3
        FROM 
            LOCAL L1_SUB
        LEFT OUTER JOIN 
            LOCAL L2_SUB ON L2_SUB.LOCCOD = L1_SUB.LOCLOCPAI
        LEFT OUTER JOIN 
            LOCAL L3_SUB ON L3_SUB.LOCCOD = L2_SUB.LOCLOCPAI
        WHERE 
            L1_SUB.LOCCOD = IDTR.IDTRDESTINO
    ) AS SUBQUERY_DESTINO_L3) AS LOCCOD_DESTINO_L3,
    (SELECT LOCCOD_L2 FROM (
        SELECT 
            L2_SUB.LOCCOD AS LOCCOD_L2
        FROM 
            LOCAL L1_SUB
        LEFT OUTER JOIN 
            LOCAL L2_SUB ON L2_SUB.LOCCOD = L1_SUB.LOCLOCPAI
        LEFT OUTER JOIN 
            LOCAL L3_SUB ON L3_SUB.LOCCOD = L2_SUB.LOCLOCPAI
        WHERE 
            L1_SUB.LOCCOD = IDTR.IDTRDESTINO
    ) AS SUBQUERY_DESTINO_L2) AS LOCCOD_DESTINO_L2,
    (SELECT LOCCOD_L1 FROM (
        SELECT 
            L1_SUB.LOCCOD AS LOCCOD_L1
        FROM 
            LOCAL L1_SUB
        LEFT OUTER JOIN 
            LOCAL L2_SUB ON L2_SUB.LOCCOD = L1_SUB.LOCLOCPAI
        LEFT OUTER JOIN 
            LOCAL L3_SUB ON L3_SUB.LOCCOD = L2_SUB.LOCLOCPAI
        WHERE 
            L1_SUB.LOCCOD = IDTR.IDTRDESTINO
    ) AS SUBQUERY_DESTINO_L1) AS LOCCOD_DESTINO_L1,

    (SELECT 
        CASE 
            WHEN EQPAUTOMTAG LIKE '' OR EQPAUTOMTAG IS NULL 
            THEN EQPNOME 
            ELSE EQPAUTOMTAG 
        END 
     FROM EQUIPAMENTO
     WHERE EQPCOD = IDTR.IDTREQP) AS EQUIPAMENTO_CARGA,

    PPROCOD, 
    PPRONOME, 
    IDTRNUMVIA AS VIAGEM, 
    IDTRPESOTOT AS PESO, 
    IDTRHRTOT AS HR

    FROM 
        ITEMDIARIATRANSP IDTR
    JOIN 
        DIARIATRANSP ON DTRCOD = IDTRDTR
    JOIN 
        EQUIPAMENTO ON EQPCOD = DTREQP
    JOIN 
        PRODUCAOPRODUTO ON PPROCOD = IDTRPPRO
    JOIN 
        LOCAL L1 ON L1.LOCCOD = IDTRLOCORIG
    LEFT OUTER JOIN 
        LOCAL L2 ON L2.LOCCOD = L1.LOCLOCPAI
    LEFT OUTER JOIN 
        LOCAL L3 ON L3.LOCCOD = L2.LOCLOCPAI

    WHERE 
        DTRSIT = 1
        AND DTREMP = 1
        AND DTRFIL = 0
        
        AND CAST(DTRDATA1 AS datetime2) BETWEEN '{data_inicio}' AND '{data_fim}'
        
    ORDER BY 
    INICIO, FIM, DIARIA;
            """,engine)
    
    ###KPI´S
    ##############################-----------------MINA---BRITADOR---------------------###########################
    mina_britador = consulta_mov.loc[
    (
        (consulta_mov['LOCCOD_L3'] == 1) |
        (consulta_mov['LOCCOD_L2'] == 1) |
        (consulta_mov['LOCCOD_L1'] == 1) 
    )  &
    (
        (consulta_mov['LOCCOD_DESTINO_L3'] == 10) |
        (consulta_mov['LOCCOD_DESTINO_L2'] == 10) |
        (consulta_mov['LOCCOD_DESTINO_L1'] == 10)
    ) &
    (
        (consulta_mov['PPROCOD'].isin([1,2,21]))
    )
]
    mina_britador = round(mina_britador['PESO'].sum(),1) or 0
    mina_britador = locale.format_string("%.0f",mina_britador,grouping=True)
    ####################----MINA ESTOQUE---------------------####################################
    mina_estoque = consulta_mov.loc[
    (
        (consulta_mov['LOCCOD_L3'] == 1) |
        (consulta_mov['LOCCOD_L2'] == 1) |
        (consulta_mov['LOCCOD_L1'] == 1)
    )    &
        (
            (consulta_mov['LOCCOD_DESTINO_L3'].isin([10,21])) |
            (consulta_mov['LOCCOD_DESTINO_L2'].isin([10,21])) |
            (consulta_mov['LOCCOD_DESTINO_L1'].isin([10,21])) 
        ) &
    (
        (consulta_mov['PPROCOD'].isin([1,2,21]))
    )
]
    mina_estoque = round(mina_estoque['PESO'].sum(),1) or 0
    mina_estoque = locale.format_string("%.0f",mina_estoque,grouping=True)

        ####################----ESTOQUE--BRITADOR---------------------####################################
    estoque_britador = consulta_mov.loc[
    (
        (consulta_mov['LOCCOD_L2'].isin([10, 21])) | 
        (consulta_mov['LOCCOD_L1'].isin([10, 21])) | 
        (consulta_mov['LOCCOD_L3'].isin([10, 21]))
    ) &
    (
        (consulta_mov['LOCCOD_DESTINO_L3'] == 10) |
        (consulta_mov['LOCCOD_DESTINO_L2'] == 10) |
        (consulta_mov['LOCCOD_DESTINO_L1'] == 10)
    ) &
    (
        (consulta_mov['PPROCOD'].isin([1,2,21]))
    )
]
    estoque_britador = round(estoque_britador['PESO'].sum(),1) or 0
    estoque_britador = locale.format_string("%.0f",estoque_britador,grouping=True)

###########--------MINA---REJEITO---------------###############################################################

    mina_rejeito = consulta_mov.loc[
        (
            (consulta_mov['LOCCOD_L1'].isin([1,10,15,16,17,19,20,21,22,63,92])) |
            (consulta_mov['LOCCOD_L2'].isin([1,10,15,16,17,19,20,21,22,63,92])) |
            (consulta_mov['LOCCOD_L3'].isin([1,10,15,16,17,19,20,21,22,63,92])) 
        ) &
        (
            (consulta_mov['LOCCOD_DESTINO_L1'].isin([1,10,15,16,17,19,20,21,22,63,92])) |
            (consulta_mov['LOCCOD_DESTINO_L2'].isin([1,10,15,16,17,19,20,21,22,63,92])) |
            (consulta_mov['LOCCOD_DESTINO_L3'].isin([1,10,15,16,17,19,20,21,22,63,92]))
        ) &
        (
            (consulta_mov['PPROCOD'] == 3)
        )
    ]
    mina_rejeito = round(mina_rejeito['PESO'].sum(),1) or 0
    mina_rejeito = locale.format_string("%.0f",mina_rejeito,grouping=True)

    
################---------CONTEXT--------------###########################

    response_data = {
        'alimentador_desligado_percentual': alimentador_desligado_percentual.tolist() if isinstance(alimentador_desligado_percentual, np.ndarray) else alimentador_desligado_percentual,
        'alimentador_desligado_tempo':alimentador_desligado_tempo,
        'evento_nao_informado_percentual':evento_nao_informado_percentual.tolist() if isinstance(evento_nao_informado_percentual, np.ndarray) else evento_nao_informado_percentual,
        'evento_nao_informado_tempo':evento_nao_informado_tempo,
        'preparando_local_percentual':preparando_local_percentual.tolist() if isinstance(preparando_local_percentual, np.ndarray) else preparando_local_percentual,
        'preparando_local_tempo':preparando_local_tempo,
        'esperando_demanda_percentual':esperando_demanda_percentual.tolist() if isinstance(esperando_demanda_percentual, np.ndarray) else esperando_demanda_percentual,
        'esperando_demanda_tempo':esperando_demanda_tempo,
        'materiaprima_percentual':materiaprima_percentual.tolist() if isinstance(materiaprima_percentual, np.ndarray) else materiaprima_percentual,
        'materiaprima_tempo':materiaprima_tempo,
        'setup_percentual':setup_percentual.tolist() if isinstance(setup_percentual, np.ndarray) else setup_percentual,
        'setup_tempo':setup_tempo,
        'embuchamento_desarme_percentual':embuchamento_desarme_percentual.tolist() if isinstance(embuchamento_desarme_percentual, np.ndarray) else embuchamento_desarme_percentual,
        'embuchamento_desarme_tempo':embuchamento_desarme_tempo,
        'embuchamento_rompedor_percentual':embuchamento_rompedor_percentual.tolist() if isinstance(embuchamento_rompedor_percentual, np.ndarray) else embuchamento_rompedor_percentual,
        'embuchamento_rompedor_tempo':embuchamento_rompedor_tempo,
        'almoco_janta_percentual':almoco_janta_percentual.tolist() if isinstance(almoco_janta_percentual,np.ndarray) else almoco_janta_percentual,
        'almoco_janta_tempo': almoco_janta_tempo,
        'mina_britador':mina_britador,
        'mina_estoque':mina_estoque,
        'estoque_britador':estoque_britador,
        'mina_rejeito':mina_rejeito
    }

    return JsonResponse(response_data, safe=False)        

######################################################################------------GRÁFICOS-------------------------------######################################################################
@csrf_exempt
@api_view(['POST'])
def calculos_graficos(request):
    connection_name = 'sga'
    
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

    # Consulta SQL
    consulta_volume_britado = pd.read_sql(f""" 
        SELECT 0 TIPO, DPRCOD, DPRREF, EQPCOD, EQPNOME, LOCCOD, LOCNOME, SUM(ADPRPESOTOT) TOTAL, DPRHROPER, DPRDATA1
        FROM ALIMDIARIAPROD
        JOIN DIARIAPROD ON DPRCOD = ADPRDPR
        JOIN LOCAL LD ON LD.LOCCOD = ADPRLOC
        JOIN EQUIPAMENTO ON EQPCOD = DPREQP
        WHERE DPRSIT = 1
        AND DPREMP = 1
        AND DPRFIL = 0
        AND CAST(DPRDATA1 AS datetime2) BETWEEN '{data_inicio}' AND '{data_fim}'
        AND ADPRLOC <> 0
        GROUP BY EQPNOME, EQPCOD, LOCCOD, LOCNOME, DPRCOD, DPRREF, DPRHROPER, DPRDATA1

        UNION

        SELECT 0 TIPO, DPRCOD, DPRREF, EQPCOD, EQPNOME, LOCCOD, LOCNOME, SUM(ADTRPESOTOT) TOTAL, DPRHRPROD, DTRDATA1
        FROM ALIMDIARIATRANSP
        JOIN ITEMDIARIATRANSP ON IDTRCOD = ADTRIDTR
        JOIN DIARIATRANSP ON DTRCOD = IDTRDTR
        JOIN LOCAL LD ON LD.LOCCOD = ADTRLOC
        JOIN DIARIAPROD ON DPRCOD = IDTRDPR
        JOIN EQUIPAMENTO ON EQPCOD = DPREQP
        WHERE DTRSIT = 1
        AND CAST(DTRDATA1 AS datetime2) BETWEEN '{data_inicio}' AND '{data_fim}'
        AND IDTRTIPODEST = 1
        AND DTREMP = 1
        AND DTRFIL = 0
        GROUP BY EQPNOME, EQPCOD, LOCCOD, LOCNOME, DPRCOD, DPRREF, DPRHRPROD, DTRDATA1

        ORDER BY 5,7
    """, engine)

    # Inicializar variáveis
    volume_diario = None
    volume_mensal = None

    # Verificar se 'DPRDATA1' está presente e não é nulo
    if 'DPRDATA1' in consulta_volume_britado.columns:
        consulta_volume_britado['DPRDATA1'] = pd.to_datetime(consulta_volume_britado['DPRDATA1'], errors='coerce')
        consulta_volume_britado = consulta_volume_britado.dropna(subset=['DPRDATA1'])  # Remover linhas onde 'DPRDATA1' é nulo

        # Quebrando o cálculo mensal em dias
        if tipo_calculo == 'mensal':
            consulta_volume_britado['DIA'] = consulta_volume_britado['DPRDATA1'].dt.day
            #volume_diario = consulta_volume_britado.groupby('DIA')['TOTAL'].sum().reset_index()

            #Função para preencher em caso de dias faltantes
            def preencher_dias_faltantes(volume_df):
                dias_completos = pd.DataFrame({'DIA': range(1, 32)})
                return dias_completos.merge(volume_df, on='DIA', how='left').fillna(0).infer_objects(copy=False)


            # Calculando volume diário para LOCCOD 44 e 62
            volume_diario_loc_44 = consulta_volume_britado[consulta_volume_britado['LOCCOD'] == 44].groupby('DIA')['TOTAL'].sum().reset_index()
            volume_diario_loc_62 = consulta_volume_britado[consulta_volume_britado['LOCCOD'] == 62].groupby('DIA')['TOTAL'].sum().reset_index()
            
            # Preencher meses faltantes com 0 para cada fábrica    
            volume_diario_loc_44 = preencher_dias_faltantes(volume_diario_loc_44)
            volume_diario_loc_62 = preencher_dias_faltantes(volume_diario_loc_62)

            # Calculando a média mensal para Pedra Calcario
            media_diaria_calcario = volume_diario_loc_44['TOTAL'].mean()
            media_diaria_calcario = locale.format_string("%.0f", media_diaria_calcario, grouping=True)

            # Calculando a média mensal para Pedra Cal
            media_diaria_cal = volume_diario_loc_62['TOTAL'].mean()
            media_diaria_cal = locale.format_string("%.0f", media_diaria_cal, grouping=True)

            # Calculando projeção
            dias_corridos = consulta_volume_britado['DIA'].max()  # Último dia do mês em que houve produção
            dias_no_mes = (consulta_volume_britado['DPRDATA1'].max().replace(day=1) + pd.DateOffset(months=1) - pd.DateOffset(days=1)).day

            if dias_corridos > 0:
                volume_ultimo_dia_loc_44 = consulta_volume_britado[(consulta_volume_britado['LOCCOD'] == 44) & (consulta_volume_britado['DIA'] == dias_corridos)]
                volume_ultimo_dia_loc_62 = consulta_volume_britado[(consulta_volume_britado['LOCCOD'] == 62) & (consulta_volume_britado['DIA'] == dias_corridos)]

                 # Total do último dia
                total_ultimo_dia_calcario = volume_ultimo_dia_loc_44['TOTAL'].sum()
                total_ultimo_dia_calcario = locale.format_string("%.0f", total_ultimo_dia_calcario, grouping=True)

                total_ultimo_dia_cal = volume_ultimo_dia_loc_62['TOTAL'].sum()
                total_ultimo_dia_cal = locale.format_string("%.0f", total_ultimo_dia_cal, grouping=True)

                # Projeção Calcário (LOCCOD 44)
                producao_acumulada_calcario = volume_diario_loc_44['TOTAL'].sum()
                projecao_calcario = (producao_acumulada_calcario / dias_corridos) * dias_no_mes
                projecao_calcario = locale.format_string("%.0f", projecao_calcario, grouping=True)

                # Projeção Cal (LOCCOD 62)
                producao_acumulada_cal = volume_diario_loc_62['TOTAL'].sum()
                projecao_cal = (producao_acumulada_cal / dias_corridos) * dias_no_mes
                projecao_cal = locale.format_string("%.0f", projecao_cal, grouping=True)
            else:
                projecao_calcario = 0
                projecao_cal = 0
                total_ultimo_dia_calcario = 0
                total_ultimo_dia_cal = 0

            volume_diario = {
                'LOCCOD_44': volume_diario_loc_44.to_dict(orient='records'),
                'LOCCOD_62': volume_diario_loc_62.to_dict(orient='records'),
                'media_diaria_calcario': media_diaria_calcario,
                'media_diaria_cal': media_diaria_cal,
                'projecao_calcario': projecao_calcario,
                'projecao_cal': projecao_cal,
                'total_ultimo_dia_calcario': total_ultimo_dia_calcario,
                'total_ultimo_dia_cal': total_ultimo_dia_cal
            }

        # Quebrando o cálculo anual em meses
        elif tipo_calculo == 'anual':
            consulta_volume_britado['MES'] = consulta_volume_britado['DPRDATA1'].dt.month
            #volume_mensal = consulta_volume_britado.groupby('MES')['TOTAL'].sum().reset_index()

            # Função para preencher os meses faltantes com 0
            def preencher_meses_faltantes(volume_df):
                meses_completos = pd.DataFrame({'MES': range(1, 13)})
                return meses_completos.merge(volume_df, on='MES', how='left').fillna(0).infer_objects(copy=False)    


            # Calculando volume diário para LOCCOD 44 e 62
            volume_mensal_loc_44 = consulta_volume_britado[consulta_volume_britado['LOCCOD'] == 44].groupby('MES')['TOTAL'].sum().reset_index()
            volume_mensal_loc_62 = consulta_volume_britado[consulta_volume_britado['LOCCOD'] == 62].groupby('MES')['TOTAL'].sum().reset_index()
            
                # Preencher meses faltantes com 0 para cada fábrica
            volume_mensal_loc_44 = preencher_meses_faltantes(volume_mensal_loc_44)
            volume_mensal_loc_62 = preencher_meses_faltantes(volume_mensal_loc_62)
           
            # # Calculando a média mensal para Pedra Calcario
            # media_mensal_calcario = volume_mensal_loc_44['TOTAL'].mean()
            # media_mensal_calcario = locale.format_string("%.0f", media_mensal_calcario, grouping=True)

            # # Calculando a média mensal para Pedra Cal
            # media_mensal_cal = volume_mensal_loc_62['TOTAL'].mean()
            # media_mensal_cal = locale.format_string("%.0f", media_mensal_cal, grouping=True)

            # Pegando o mês atual (corridos)
            mes_corrente = datetime.now().month

            # Somar o volume mensal sem incluir os meses futuros
            volume_mensal_loc_44_filtrado = volume_mensal_loc_44[volume_mensal_loc_44['MES'] <= mes_corrente]
            volume_mensal_loc_62_filtrado = volume_mensal_loc_62[volume_mensal_loc_62['MES'] <= mes_corrente]

            # Médias mensais baseadas nos meses já passados
            media_mensal_calcario = volume_mensal_loc_44_filtrado['TOTAL'].sum() / mes_corrente
            media_mensal_calcario = locale.format_string("%.0f", media_mensal_calcario, grouping=True)

            media_mensal_cal = volume_mensal_loc_62_filtrado['TOTAL'].sum() / mes_corrente
            media_mensal_cal = locale.format_string("%.0f", media_mensal_cal, grouping=True)

            # Projeção anual
            meses_corridos = datetime.now().month
            meses_no_ano = 12  # Número total de meses no ano

            if meses_corridos > 0:
                volume_ultimo_mes_loc_44 = consulta_volume_britado[(consulta_volume_britado['LOCCOD'] == 44) & (consulta_volume_britado['MES'] == meses_corridos)]
                volume_ultimo_mes_loc_62 = consulta_volume_britado[(consulta_volume_britado['LOCCOD'] == 62) & (consulta_volume_britado['MES'] == meses_corridos)]

                # Total do último mes
                total_ultimo_mes_calcario = volume_ultimo_mes_loc_44['TOTAL'].sum()
                total_ultimo_mes_calcario = locale.format_string("%.0f", total_ultimo_mes_calcario, grouping=True)

                total_ultimo_mes_cal = volume_ultimo_mes_loc_62['TOTAL'].sum()
                total_ultimo_mes_cal = locale.format_string("%.0f", total_ultimo_mes_cal, grouping=True)

                # Projeção Calcário (LOCCOD 44)
                producao_acumulada_calcario = volume_mensal_loc_44['TOTAL'].sum()
                projecao_anual_calcario = (producao_acumulada_calcario / meses_corridos) * meses_no_ano
                projecao_anual_calcario = locale.format_string("%.0f", projecao_anual_calcario, grouping=True)

                # Projeção Cal (LOCCOD 62)
                producao_acumulada_cal = volume_mensal_loc_62['TOTAL'].sum()
                projecao_anual_cal = (producao_acumulada_cal / meses_corridos) * meses_no_ano
                projecao_anual_cal = locale.format_string("%.0f", projecao_anual_cal, grouping=True)
            else:
                projecao_anual_calcario = 0
                projecao_anual_cal = 0

            volume_mensal = {
                'LOCCOD_44': volume_mensal_loc_44.to_dict(orient='records'),
                'LOCCOD_62': volume_mensal_loc_62.to_dict(orient='records'),
                'media_mensal_calcario': media_mensal_calcario,
                'media_mensal_cal': media_mensal_cal,
                'projecao_anual_calcario': projecao_anual_calcario,
                'projecao_anual_cal': projecao_anual_cal,
                #'meses_corridos': meses_corridos,
                'total_ultimo_mes_calcario': total_ultimo_mes_calcario,
                'total_ultimo_mes_cal': total_ultimo_mes_cal
            }

    # Calcular volumes por local
    volume_britado_por_loc = consulta_volume_britado.groupby('LOCCOD')['TOTAL'].sum()
    volume_britado_por_loc = volume_britado_por_loc.reindex([44, 62, 66], fill_value=0)

    # Somando os valores dos códigos 44, 62 e 66
    volume_britado_total = round(volume_britado_por_loc.loc[[44, 62, 66]].sum(), 2)
    volume_britado_total = locale.format_string("%.0f", volume_britado_total, grouping=True)

    # Calculando produção do britador (somando 44 e 62)
    producao_britador = round(volume_britado_por_loc.loc[[44, 62]].sum(), 2)
    producao_britador = locale.format_string("%.0f", producao_britador, grouping=True)

    # Montando os dados de resposta
    response_data = {
        'volume_britado_total': volume_britado_total,
        'producao_britador': producao_britador,
    }

    # Adicionando o volume diário se o tipo de cálculo for 'mensal'
    if volume_diario is not None:
        response_data['volume_diario'] = volume_diario

    # Adicionando o volume mensal se o tipo de cálculo for 'anual'
    if volume_mensal is not None:
        response_data['volume_mensal'] = volume_mensal

         

    return JsonResponse(response_data)







