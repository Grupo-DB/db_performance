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
def calculos_britagem(request):
    connection_name = 'sga'
    
    # Recuperando o tipo de cálculo do corpo da requisição
    tipo_calculo = request.data.get('tipo_calculo')

    # Definindo as datas com base no tipo de cálculo
    if tipo_calculo == 'atual':
        data_inicio = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
        data_fim = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
    elif tipo_calculo == 'mensal':
        data_inicio = datetime.now().strftime('%Y-%m-01 00:00:00')  # Início do mês
        data_fim = datetime.now().strftime('%Y-%m-%d 23:59:59')  # Data atual
    elif tipo_calculo == 'anual':
        data_inicio = datetime.now().strftime('%Y-01-01 00:00:00')  # Início do ano
        data_fim = datetime.now().strftime('%Y-%m-%d 23:59:59')  # Data atual
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
                            CAST(DPRDATA1 as date) BETWEEN '{data_inicio}' AND '{data_fim}'
                            AND DPRSIT = 1
                            AND DPREMP = 1
                            AND DPRFIL = 0
                            AND DPREQP = DPR.DPREQP)) * 100 PERC_TOTAL

    FROM DIARIAPROD DPR
    JOIN EQUIPAMENTO ON EQPCOD = DPREQP
    JOIN EVENTODIARIAPROD ON EDPRDPR = DPRCOD
    JOIN EVENTODIARIA ON EVDCOD = EDPREVD

    WHERE 
    CAST(DPRDATA1 as date) BETWEEN '2024-09-01 ' AND '2024-09-03'
    AND DPRSIT = 1
    AND DPREMP =1
    AND DPRFIL = 0
    AND EQPAPLIC = 'P'
    AND EQPCOD = 66


GROUP BY EDPREVD, EVDNOME, EDPROPERSN, DPREQP

    """,connections[connection_name])

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

################################################################################################

    consulta_mov = pd.read_sql(f"""
        DECLARE @LOCAL_ORIGEM VARCHAR(MAX) = '';  -- Substitua pelo valor apropriado

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
        AND CAST(DTRDATA1 AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
        
    ORDER BY 
    INICIO, FIM, DIARIA;
            """,connections[connection_name])
    
    ###KPI´S
    #mb_me = consulta_mov.loc[(consulta_mov['LOCCOD_L3']==1) & (consulta_mov['LOCCOD_DESTINO_L3']==10)]
    mb_me = consulta_mov.loc[
    (consulta_mov['LOCCOD_L3'] == 1) & 
    (
        (consulta_mov['LOCCOD_DESTINO_L3'] == 10) |
        (consulta_mov['LOCCOD_DESTINO_L2'] == 10) |
        (consulta_mov['LOCCOD_DESTINO_L1'] == 10)
    )
]
#     mb_me = consulta_mov.loc[
#     (consulta_mov['LOCCOD_L3'].astype(str).str.contains('1', case=False, na=False) & 
#      consulta_mov['LOCCOD_DESTINO_L3'].astype(str)=='10') 
#    # consulta_mov['LOCCOD_DESTINO_L2'].astype(str)=='10' 
#     #consulta_mov['LOCCOD_DESTINO_L1'].astype(str).str.contains('10', case=False, na=False)
# ]

    
    tot_tn_mn_brit_me = round(mb_me['PESO'].sum(),1)
    tot_tn_mn_brit_me = locale.format_string("%.2f",tot_tn_mn_brit_me,grouping=True)

################---------CONTEXT--------------###########################

    response_data = {
        'setup_percentual':setup_percentual,
        'setup_tempo':setup_tempo,
        'embuchamento_desarme_percentual':embuchamento_desarme_percentual,
        'embuchamento_desarme_tempo':embuchamento_desarme_tempo,
        'embuchamento_rompedor_percentual':embuchamento_rompedor_percentual,
        'embuchamento_rompedor_tempo':embuchamento_rompedor_tempo,
        'almoco_janta_percentual':almoco_janta_percentual,
        'almoco_janta_tempo': almoco_janta_tempo,
        'tot_tn_mn_brit_me':tot_tn_mn_brit_me
    }

    return JsonResponse(response_data, safe=False)        