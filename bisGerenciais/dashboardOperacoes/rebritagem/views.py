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
def calculos_rebritagem(request):
    connection_name = 'sga'
    
    # Recuperando o tipo de cálculo do corpo da requisição
    tipo_calculo = request.data.get('tipo_calculo')

    # Definindo as datas com base no tipo de cálculo
    if tipo_calculo == 'atual':
        data_inicio = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
        data_fim = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    elif tipo_calculo == 'mensal':
        data_inicio = datetime.now().strftime('%Y-%m-01 00:00:00')  # Início do mês
        data_fim = datetime.now().strftime('%Y-%m-%d 23:59:59')  # Data atual
    elif tipo_calculo == 'anual':
        data_inicio = datetime.now().strftime('%Y-01-01 00:00:00')  # Início do ano
        data_fim = datetime.now().strftime('%Y-%m-%d 23:59:59')  # Data atual
    else:
        return JsonResponse({'error': 'Tipo de cálculo inválido'}, status=400)

    consulta_volume_rebritado = pd.read_sql(f"""
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
    volume_rebritado_por_loc = consulta_volume_rebritado.groupby('LOCCOD')['TOTAL'].sum()
    volume_rebritado_por_loc = volume_rebritado_por_loc.reindex([93], fill_value=0)
    # Em seguida, aplique a formatação local a cada valor da Series
    volume_rebritado_por_loc_formatado = volume_rebritado_por_loc.apply(lambda x: locale.format_string("%.0f", x, grouping=True))

    volume_rebritado_por_loc_formatado = volume_rebritado_por_loc_formatado.to_dict()
    
    # Somando os valores dos códigos 44, 62 e 66
    volume_rebritado_total = round(volume_rebritado_por_loc.loc[[93]].sum(),2)
    volume_rebritado_total = locale.format_string("%.0f",volume_rebritado_total,grouping=True)

    response_data = {
        'volume_rebritado_total': volume_rebritado_total,
        'tipo_calculo': tipo_calculo,
        'volume_rebritado':volume_rebritado_por_loc_formatado,
    }
    return JsonResponse(response_data,safe=False)

@csrf_exempt
@api_view(['POST'])
def calculos_rebritagem_paradas(request):
    connection_name = 'sga'
    
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
        CAST(DPRDATA1 as date) BETWEEN '{data_inicio} ' AND '{data_fim}'
        AND DPRSIT = 1
        AND DPREMP =1
        AND DPRFIL = 0
        AND EQPAPLIC = 'P'
        AND EQPCOD =92


    GROUP BY EDPREVD, EVDNOME, EDPROPERSN, DPREQP

    """,engine)

    ##KPI´S PARADAS

 ###########--ALMOÇO E JANTA ######################
    des = consulta_evento_parada.loc[consulta_evento_parada['EDPREVD']==6,['TEMPO','PERC_TOTAL']]
    almoco_janta_percentual = des['PERC_TOTAL'].values
    if (almoco_janta_percentual != 0).any():
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
    if (esperando_demanda_percentual != 0).any():
        esperando_demanda_percentual = ', '.join(map(str, esperando_demanda_percentual))
        esperando_demanda_percentual = round(float(esperando_demanda_percentual),1)
        
    else:
        esperando_demanda_percentual = 0
    esperando_demanda_tempo = des['TEMPO'].values
    if (esperando_demanda_tempo != 0).any():
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

    response_data = {
        #######################---------EVENTOS-PARADA-----------##############################
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
    }

    return JsonResponse(response_data, safe=False)