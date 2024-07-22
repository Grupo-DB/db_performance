import json
from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from django.http import JsonResponse
import pandas as pd
from datacalc.serializers import PeriodoSerializer
from management.models import Colaborador,Avaliacao,Ambiente,Avaliado,Avaliador
from datacalc.models import Periodo
from datetime import datetime
from django.utils import timezone
from rest_framework import generics
from rest_framework.parsers import JSONParser
from django.db.models import Q
from management.utils import send_custom_email
# Create your views here.


# def calc_colaboradores(request):
#     queryset = Colaborador.objects.all().values()
#     df = pd.DataFrame(queryset)

#     total_colaboradores = len(df)

#     querysetidade = Colaborador.objects.all().values('data_nascimento')
#     dfidade = pd.DataFrame(querysetidade)

#     hoje = datetime.today()
#     dfidade['idade'] = (hoje - dfidade['data_nascimento']).astype('<m8[Y]')

#     media_idade = df['idade'].mean()

#     return JsonResponse({
#         'total_colaboradores': total_colaboradores,
#         'media_idade':media_idade
#     })






#@method_decorator(csrf_exempt, name='dispatch')
@csrf_exempt
def filtrar_colaboradores(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        selected_filiais = data.get('selectedFiliais', [])
        selected_areas = data.get('selectedAreas', [])
        selected_cargos = data.get('selectedCargos', [])
        selected_ambientes = data.get('selectedAmbientes', [])
        selected_setores = data.get('selectedSetores', [])
        data_inicio = data.get('data_inicio', None)
        data_fim = data.get('data_fim', None)
        
        queryset = Colaborador.objects.all()

        if selected_filiais:
            queryset = queryset.filter(filial_id__in=selected_filiais)
        if selected_areas:
            queryset = queryset.filter(area_id__in=selected_areas)    
        if selected_cargos:
            queryset = queryset.filter(cargo_id__in=selected_cargos)
        if selected_ambientes:
            queryset = queryset.filter(ambiente_id__in=selected_ambientes)    
        if selected_setores:
            queryset = queryset.filter(setor_id__in=selected_setores)
        

        df = pd.DataFrame(queryset.values())

        # Log the DataFrame columns and head
        
        # querysetidade = Colaborador.objects.all().values('data_nascimento')
        # dfidade = pd.DataFrame(querysetidade)

        hoje = timezone.now().date()
        # Converte a data de nascimento para a data local
        hoje = timezone.now().date()
    
        if 'data_nascimento' in df.columns:
            df['data_nascimento'] = pd.to_datetime(df['data_nascimento'], errors='coerce').dt.date
            df['data_nascimento'].fillna(pd.to_datetime('1900-01-01').date(), inplace=True)  # Preenche NaNs com uma data padrão
            df['idade'] = (hoje - df['data_nascimento']).apply(lambda x: x.days // 365)
            media_idade = round(df['idade'].mean())
        else:
            media_idade = 0

        if 'data_admissao' in df.columns:
            df['data_admissao'] = pd.to_datetime(df['data_admissao'], errors='coerce').dt.date
            df['data_admissao'].fillna(pd.to_datetime('1900-01-01').date(), inplace=True)  # Preenche NaNs com uma data padrão
            df['tempo'] = (hoje - df['data_admissao']).apply(lambda x: x.days // 365)
            media_tempo = round(df['tempo'].mean())
        else:
            media_tempo = 0

        if df.empty:
            return JsonResponse({
                'total_colaboradores': 0,
                'total_avaliacoes': len(avaliacoes),
                'media_salarios': 0,
                'media_idade':0,
                'media_tempo':0,
                'total_feedbacks':0,
                'filtered_data': [],
                'grafico_dados': {},
                'grafico_dados_racas': {},
                'grafico_dados_instrucao':{},
                'grafico_dados_estado_civil':{},
                'media_salario_por_raca': {},
                'media_salario_por_genero': {},
                'instrucao_por_raca':{},
                'instrucao_por_genero':{},
                'media_geral': 0,
                'media_respostas': {}
            })

        if 'salario' not in df.columns:
            return JsonResponse({
                'total_colaboradores': len(df),
                'media_salarios': 0,
                'total_feedbacks':0,
                'media_idade':0,
                'media_tempo':0,
                'filtered_data': df.to_dict(orient='records'),
                'instrucao_por_raca':{},
                'grafico_dados': {},
                'grafico_dados_racas': {},
                'grafico_dados_instrucao':{},
                'grafico_dados_estado_civil,':{},
                'media_salario_por_raca': {},
                'instrucao_por_genero':{},
                'media_salario_por_genero': {},
                'media_geral': 0,
                'total_avaliacoes': len(avaliacoes),
                'media_respostas': {}
            })

        total_colaboradores = len(df)
        media_salarios = df['salario'].mean()
        
        campos_necessarios = ['id', 'nome','filial_id','area_id','cargo_id', 'setor_id', 'ambiente_id','salario','data_nascimento','data_admissao','estado_civil','instrucao','genero']
        filtered_data = df[campos_necessarios].to_dict(orient='records')

        grafico_dados = df['tipocontrato'].value_counts().to_dict()
        grafico_dados_racas = df['raca'].value_counts().to_dict()
        grafico_dados_instrucao = df['instrucao'].value_counts().to_dict()
        grafico_dados_estado_civil = df['estado_civil'].value_counts().to_dict()
        media_salario_por_raca = df.groupby('raca')['salario'].mean().to_dict()
        media_salario_por_genero = df.groupby('genero')['salario'].mean().to_dict()
        media_salario_por_instrucao = df.groupby('instrucao')['salario'].mean().to_dict()
        grouped = df.groupby('genero')['instrucao'].value_counts()
        instrucao_por_genero = {f'{k[0]}_{k[1]}': v for k, v in grouped.items()}
        grouped2 = df.groupby('raca')['instrucao'].value_counts()
        instrucao_por_raca = {f'{k[0]}_{k[1]}': v for k, v in grouped2.items()}

        ambientes = Ambiente.objects.all()
        ambiente_dict = {amb.id: amb.nome for amb in ambientes}

        # Verificar e garantir que a substituição está correta
        if 'ambiente_id' in df.columns:
            df['ambiente_nome'] = df['ambiente_id'].map(ambiente_dict)

        colaboradores_por_ambiente = df['ambiente_nome'].value_counts().to_dict()
        media_salario_por_ambiente = df.groupby('ambiente_nome')['salario'].mean().to_dict()
       
        # Calcular a média das respostas das avaliações gerais
        avaliacoesGeral = Avaliacao.objects.filter(avaliado_id__in=queryset.values_list('id', flat=True))
        avaliacoesGeral = avaliacoesGeral.filter(tipo='Avaliação Geral')
        # Filtrar avaliações por data
        if data_inicio:
            data_inicio = pd.to_datetime(data_inicio)
            avaliacoesGeral = avaliacoesGeral.filter(create_at__gte=data_inicio)
        if data_fim:
            data_fim = pd.to_datetime(data_fim)
            avaliacoesGeral = avaliacoesGeral.filter(create_at__lte=data_fim)

       # avaliacoes = avaliacoes.filter(tipo='Avaliação Geral')
        perguntas_respostas_geral = []
        for avaliacao in avaliacoesGeral:
            if isinstance(avaliacao.perguntasRespostas, str):
                perguntas_respostas_geral.append(json.loads(avaliacao.perguntasRespostas))
            else:
                perguntas_respostas_geral.append(avaliacao.perguntasRespostas)

        # Inicializar dicionários para média e contagem das respostas
        media_respostas_geral = {}
        count_respostas_geral = {}
        total_respostas_geral = 0
        soma_respostas_geral = 0

        # Processar as perguntas e respostas
        for pr in perguntas_respostas_geral:
            for pergunta, dados in pr.items():
                if pergunta not in media_respostas_geral:
                    media_respostas_geral[pergunta] = 0
                    count_respostas_geral[pergunta] = 0
                resposta = dados.get('resposta', None)
                if resposta == "" or resposta is None or resposta == "nao_se_aplica":
                    # Ignora respostas vazias ou None
                    continue
                try:
                    resposta = int(resposta)

                except ValueError:
                    print(f"Não foi possível converter a resposta '{dados.get('resposta')}' para inteiro.")
                    resposta = 0
                media_respostas_geral[pergunta] += resposta
                count_respostas_geral[pergunta] += 1
                soma_respostas_geral += resposta
                total_respostas_geral += 1

        # Calcular a média das respostas
        for pergunta in media_respostas_geral:
            if count_respostas_geral[pergunta] > 0:
                media_respostas_geral[pergunta] /= count_respostas_geral[pergunta]

        media_geral = round((soma_respostas_geral / total_respostas_geral if total_respostas_geral > 0 else 0  ),1)          
        
        total_avaliacoes_gerais = len(avaliacoesGeral)       
        total_feedbacks_geral = len(avaliacoesGeral.filter(feedback=1))
        percentComplete =(total_feedbacks_geral / total_avaliacoes_gerais) * 100 if total_avaliacoes_gerais else 0;

###############################################################################################################################


        avaliacoesGestor = Avaliacao.objects.filter(avaliado_id__in=queryset.values_list('id', flat=True))
        avaliacoesGestor = avaliacoesGestor.filter(tipo='Avaliação do Gestor')

        # Filtrar avaliações por data
        if data_inicio:
            data_inicio = pd.to_datetime(data_inicio)
            avaliacoesGestor = avaliacoesGestor.filter(create_at__gte=data_inicio)
        if data_fim:
            data_fim = pd.to_datetime(data_fim)
            avaliacoesGestor = avaliacoesGestor.filter(create_at__lte=data_fim)

        perguntas_respostas_gestor = []
        for avaliacao in avaliacoesGestor:
            if isinstance(avaliacao.perguntasRespostas, str):
                perguntas_respostas_gestor.append(json.loads(avaliacao.perguntasRespostas))
            else:
                perguntas_respostas_gestor.append(avaliacao.perguntasRespostas)

        media_respostas_gestor = {}
        count_respostas_gestor = {}
        total_respostas_gestor = 0
        soma_respostas_gestor = 0

        for pr in perguntas_respostas_gestor:
            for pergunta, dados in pr.items():
                if pergunta not in media_respostas_gestor:
                    media_respostas_gestor[pergunta] = 0
                    count_respostas_gestor[pergunta] = 0
                resposta = dados.get('resposta', None)
                if resposta == "" or resposta is None or resposta == "nao_se_aplica":
                    # Ignora respostas vazias ou None
                    continue
                try:
                    resposta = int(resposta)    
                except ValueError:
                    print(f"Não foi possível converter a resposta '{dados.get('resposta')}' para inteiro.")
                    resposta = 0
                media_respostas_gestor[pergunta] += resposta
                count_respostas_gestor[pergunta] += 1
                soma_respostas_gestor += resposta
                total_respostas_gestor += 1


        for pergunta in media_respostas_gestor:
            if count_respostas_gestor[pergunta] > 0:
                media_respostas_gestor[pergunta] /= count_respostas_gestor[pergunta]


        media_geral_gestor = round((soma_respostas_gestor / total_respostas_gestor if total_respostas_gestor > 0 else 0  ),1)
        
        media_total = round(((media_geral_gestor + media_geral) / 2),2)

        total_avaliacoes_gestor = len(avaliacoesGestor)       
        total_feedbacks_gestor = len(avaliacoesGestor.filter(feedback=1))
        percentCompleteGestor = (total_feedbacks_gestor / total_avaliacoes_gestor) if total_avaliacoes_gestor else 0
        
        total_avaliacoes_geral = total_avaliacoes_gerais + total_avaliacoes_gestor
        total_feedbacks_geral = total_feedbacks_geral + total_feedbacks_gestor

        percentCompleteGeral = (total_feedbacks_geral / total_avaliacoes_geral) * 100  if total_avaliacoes_geral else 0;

        response_data = {
            'total_colaboradores': total_colaboradores,
            'total_avaliacoes_gerais': total_avaliacoes_gerais,
            'media_salarios': media_salarios,
            'total_feedbacks':total_feedbacks_geral,
            'media_idade':media_idade,
            'media_tempo':media_tempo,
            'filtered_data': filtered_data,
            'grafico_dados': grafico_dados,
            'grafico_dados_racas': grafico_dados_racas,
            'grafico_dados_instrucao':grafico_dados_instrucao,
            'grafico_dados_estado_civil':grafico_dados_estado_civil,
            'media_salario_por_raca': media_salario_por_raca,
            'media_salario_por_genero': media_salario_por_genero,
            'total_avaliacoes_geral':total_avaliacoes_geral,
            'total_avaliacoes':total_avaliacoes_geral,
            'total_avaliacoes_gestor':total_avaliacoes_gestor,
            'media_respostas_geral': media_respostas_geral,
            'media_geral':media_geral,
            'media_total':media_total,
            'media_geral_gestor': media_geral_gestor,
            'media_respostas_gestor': media_respostas_gestor,
            'percentCompleteGestor': percentCompleteGestor,
            'percentComplete':percentComplete,
            'total_feedbacks_geral':total_feedbacks_geral,
            'total_feedbacks_gestor':total_feedbacks_gestor,
            'instrucao_por_raca':instrucao_por_raca,
            'instrucao_por_genero':instrucao_por_genero,
            'colaboradores_por_ambiente': colaboradores_por_ambiente,
            'percentCompleteGeral':percentCompleteGeral,
            'media_salario_por_instrucao':media_salario_por_instrucao,
            'media_salario_por_ambiente': media_salario_por_ambiente,
        }

        return JsonResponse(response_data, safe=False)


################################DASHBOARD AVALIADOR E AVALIADOS###############################################################

@csrf_exempt
def filtrar_avaliacoes(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        selected_avaliadores = data.get('avaliadorSelecionadoId', [])
        selected_avaliados = data.get('avaliadoSelecionadoId', [])
        selected_areas = data.get('selectedAreas', [])
        selected_cargos = data.get('selectedCargos', [])
        selected_ambientes = data.get('selectedAmbientes', [])
        selected_setores = data.get('selectedSetores', [])
        data_inicio = data.get('data_inicio', None)
        data_fim = data.get('data_fim', None)

        queryset =Avaliacao.objects.all()

        if selected_avaliadores:
            queryset = queryset.filter(avaliador_id__in=selected_avaliadores)
        if selected_avaliados:
            queryset = queryset.filter(avaliado_id__in=selected_avaliados)
        if selected_areas:
            queryset = queryset.filter(area_id__in=selected_areas)    
        if selected_cargos:
            queryset = queryset.filter(cargo_id__in=selected_cargos)
        if selected_ambientes:
            queryset = queryset.filter(ambiente_id__in=selected_ambientes)    
        if selected_setores:
            queryset = queryset.filter(setor_id__in=selected_setores)

        df = pd.DataFrame(queryset.values())
              
        campos_necessarios = ['id', 'tipo','avaliado_id','avaliador_id','periodo']
        filtered_data = df[campos_necessarios].to_dict(orient='records')
        # Calcular a média das respostas das avaliações gerais

        avaliacoes = Avaliacao.objects.filter(avaliador_id__in=selected_avaliadores)

        # Filtrar avaliações por data
        if data_inicio:
            data_inicio = pd.to_datetime(data_inicio)
            avaliacoes = avaliacoes.filter(create_at__gte=data_inicio)
        if data_fim:
            data_fim = pd.to_datetime(data_fim)
            avaliacoes = avaliacoes.filter(create_at__lte=data_fim)


        perguntas_respostas = []

        for avaliacao in avaliacoes:
            if isinstance(avaliacao.perguntasRespostas, str):
                perguntas_respostas.append(json.loads(avaliacao.perguntasRespostas))
            else:
                perguntas_respostas.append(avaliacao.perguntasRespostas)

        media_respostas = {}
        count_respostas = {}
        total_respostas = 0
        soma_respostas = 0

        for pr in perguntas_respostas:
            for pergunta, dados in pr.items():
                if pergunta not in media_respostas:
                    media_respostas[pergunta] = 0
                    count_respostas[pergunta] = 0
                resposta = dados.get('resposta', None)
                if resposta == "" or resposta is None or resposta == "nao_se_aplica":
                     # Ignora respostas vazias ou None
                    continue
                try:
                    resposta = float(resposta)
                except ValueError:
                    resposta = 0  # ou outro valor padrão que você considere apropriado
                media_respostas[pergunta] += resposta
                count_respostas[pergunta] += 1
                soma_respostas += resposta
                total_respostas += 1

        for pergunta in media_respostas:
            if count_respostas[pergunta] > 0:
                media_respostas[pergunta] /= count_respostas[pergunta]

        media_geral = round((soma_respostas / total_respostas if total_respostas > 0 else 0  ),1)          
        total_avaliacoes = len(avaliacoes)       
        
###AVALIADOS

        avaliacoesAv = Avaliacao.objects.filter(avaliado_id__in=selected_avaliados)

        # Filtrar avaliações por data
        if data_inicio:
            data_inicio = pd.to_datetime(data_inicio)
            avaliacoesAv = avaliacoesAv.filter(create_at__gte=data_inicio)
        if data_fim:
            data_fim = pd.to_datetime(data_fim)
            avaliacoesAv = avaliacoesAv.filter(create_at__lte=data_fim)
        

        perguntas_respostas_avaliado = []
        for avaliacao in avaliacoesAv:
            if isinstance(avaliacao.perguntasRespostas, str):
                perguntas_respostas_avaliado.append(json.loads(avaliacao.perguntasRespostas))
            else:
                perguntas_respostas_avaliado.append(avaliacao.perguntasRespostas)

        media_respostas_avaliado = {}
        count_respostas_avaliado = {}
        total_respostas_avaliado = 0
        soma_respostas_avaliado = 0

        for pr in perguntas_respostas_avaliado:
            for pergunta, dados in pr.items():
                if pergunta not in media_respostas_avaliado:
                    media_respostas_avaliado[pergunta] = 0
                    count_respostas_avaliado[pergunta] = 0
                resposta = dados.get('resposta', None)
                if resposta == "" or resposta is None or resposta == "nao_se_aplica":
                # Ignora respostas vazias ou None
                    continue
                try:
                    resposta = float(resposta)
                except ValueError:
                    resposta = 0  # ou outro valor padrão que você considere apropriado

                media_respostas_avaliado[pergunta] += resposta
                count_respostas_avaliado[pergunta] += 1
                soma_respostas_avaliado += resposta
                total_respostas_avaliado += 1


        for pergunta in media_respostas_avaliado:
            if count_respostas_avaliado[pergunta] > 0:
                media_respostas_avaliado[pergunta] /= count_respostas_avaliado[pergunta]

        media_geral_avaliado = round((soma_respostas_avaliado / total_respostas_avaliado) if total_respostas_avaliado > 0 else 0  ,1)          
        total_avaliacoes = len(avaliacoes)
        total_avaliacoes_avaliados = len(avaliacoesAv)
        response_data = {
            'media_respostas_avaliado':media_respostas_avaliado,
            'total_avaliacoes': total_avaliacoes,
            'filtered_data': filtered_data,
            'media_respostas': media_respostas,
            'media_geral':media_geral,
            'media_geral_avaliado':media_geral_avaliado,
            'total_avaliacoes_avaliados':total_avaliacoes_avaliados
        }

        return JsonResponse(response_data, safe=False)
    

########################################################################################################

@csrf_exempt
def periodo(request):
    if request.method == 'GET':
        try:
            # Supondo que você só tenha um período salvo no banco de dados
            periodo = Periodo.objects.latest('id')
            serializer = PeriodoSerializer(periodo)
            return JsonResponse(serializer.data)
        except Periodo.DoesNotExist:
            return JsonResponse({'dataInicio': None, 'dataFim': None})

    if request.method == 'POST':
        data = JSONParser().parse(request)
        serializer = PeriodoSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse({'status': 'success'})
        return JsonResponse(serializer.errors, status=400)
    
################################------------------------AVALIADOR----LOGADO-------------------------------------------------######################################

@csrf_exempt
@api_view(['POST'])
def filtrar_avaliacoes_logado(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        selected_avaliadores = data.get('avaliadorSelecionadoId', [])
        selected_avaliados = data.get('avaliadoSelecionadoId', [])
        selected_areas = data.get('selectedAreas', [])
        selected_cargos = data.get('selectedCargos', [])
        selected_ambientes = data.get('selectedAmbientes', [])
        selected_setores = data.get('selectedSetores', [])
        data_inicio = data.get('data_inicio', None)
        data_fim = data.get('data_fim', None)
        periodo = data.get('periodo', '')

        user = request.user

        try:
            avaliador_logado = Avaliador.objects.get(user=user)
        except Avaliador.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Avaliador logado não encontrado'}, status=status.HTTP_404_NOT_FOUND)

        queryset = Avaliacao.objects.filter(avaliador=avaliador_logado)

        if selected_avaliadores:
            queryset = queryset.filter(avaliador_id__in=selected_avaliadores)
        if selected_avaliados:
            queryset = queryset.filter(avaliado_id__in=selected_avaliados)
        if selected_areas:
            queryset = queryset.filter(area_id__in=selected_areas)
        if selected_cargos:
            queryset = queryset.filter(cargo_id__in=selected_cargos)
        if selected_ambientes:
            queryset = queryset.filter(ambiente_id__in=selected_ambientes)
        if selected_setores:
            queryset = queryset.filter(setor_id__in=selected_setores)
        if periodo:
            queryset = queryset.filter(periodo=periodo)

        df = pd.DataFrame(queryset.values())

        campos_necessarios = ['id', 'tipo', 'avaliado_id', 'avaliador_id', 'periodo']
        filtered_data = df[campos_necessarios].to_dict(orient='records')

        # Calcular a média das respostas das avaliações do avaliador logado
        avaliacoes_logado = Avaliacao.objects.filter(avaliador=avaliador_logado)
        avaliacoes_logado = avaliacoes_logado.filter(tipo='Avaliação Geral')


        # Filtrar avaliações por data
        if data_inicio:
            data_inicio = pd.to_datetime(data_inicio)
            avaliacoes_logado = avaliacoes_logado.filter(create_at__gte=data_inicio)
        if data_fim:
            data_fim = pd.to_datetime(data_fim)
            avaliacoes_logado = avaliacoes_logado.filter(create_at__lte=data_fim)


        perguntas_respostas_logado = []
        for avaliacao in avaliacoes_logado:
            if isinstance(avaliacao.perguntasRespostas, str):
                perguntas_respostas_logado.append(json.loads(avaliacao.perguntasRespostas))
            else:
                perguntas_respostas_logado.append(avaliacao.perguntasRespostas)

        media_respostas_logado = {}
        count_respostas_logado = {}
        total_respostas_logado = 0
        soma_respostas_logado = 0

        for pr in perguntas_respostas_logado:
            for pergunta, dados in pr.items():
                if pergunta not in media_respostas_logado:
                    media_respostas_logado[pergunta] = 0
                    count_respostas_logado[pergunta] = 0
                resposta = dados.get('resposta', None)
                if resposta == "" or resposta is None or resposta == "nao_se_aplica":
                    # Ignora respostas vazias ou None
                    continue
                try:
                    resposta = int(resposta)    
                except ValueError:
                    resposta = 0  # ou outro valor padrão que você considere apropriado

                media_respostas_logado[pergunta] += resposta
                count_respostas_logado[pergunta] += 1
                soma_respostas_logado += resposta
                total_respostas_logado += 1

        for pergunta in media_respostas_logado:
            if count_respostas_logado[pergunta] > 0:
                media_respostas_logado[pergunta] /= count_respostas_logado[pergunta]

        media_geral_logado = round((soma_respostas_logado / total_respostas_logado if total_respostas_logado > 0 else 0), 1)
        total_avaliacoes_logado = len(avaliacoes_logado)


    ########################Gestor

        avaliacoesGestorMe = Avaliacao.objects.filter(avaliador=avaliador_logado)
        avaliacoesGestorMe = avaliacoesGestorMe.filter(tipo='Avaliação do Gestor')


        # Filtrar avaliações por data
        if data_inicio:
            data_inicio = pd.to_datetime(data_inicio)
            avaliacoesGestorMe = avaliacoesGestorMe.filter(create_at__gte=data_inicio)
        if data_fim:
            data_fim = pd.to_datetime(data_fim)
            avaliacoesGestorMe = avaliacoesGestorMe.filter(create_at__lte=data_fim)


        perguntas_respostas_gestorMe = []
        for avaliacao in avaliacoesGestorMe:
            if isinstance(avaliacao.perguntasRespostas, str):
                perguntas_respostas_gestorMe.append(json.loads(avaliacao.perguntasRespostas))
            else:
                perguntas_respostas_gestorMe.append(avaliacao.perguntasRespostas)

        media_respostas_gestorMe = {}
        count_respostas_gestorMe = {}
        total_respostas_gestorMe = 0
        soma_respostas_gestorMe = 0

        for pr in perguntas_respostas_gestorMe:
            for pergunta, dados in pr.items():
                if pergunta not in media_respostas_gestorMe:
                    media_respostas_gestorMe[pergunta] = 0
                    count_respostas_gestorMe[pergunta] = 0
                resposta = dados.get('resposta', None)
                if resposta == "" or resposta is None or resposta == "nao_se_aplica":
                    # Ignora respostas vazias ou None
                    continue
                try:
                    resposta = int(resposta)    
                except ValueError:
                    print(f"Não foi possível converter a resposta '{dados.get('resposta')}' para inteiro.")
                    resposta = 0
                media_respostas_gestorMe[pergunta] += resposta
                count_respostas_gestorMe[pergunta] += 1
                soma_respostas_gestorMe += resposta
                total_respostas_gestorMe += 1


        for pergunta in media_respostas_gestorMe:
            if count_respostas_gestorMe[pergunta] > 0:
                media_respostas_gestorMe[pergunta] /= count_respostas_gestorMe[pergunta]


        media_geral_gestorMe = round((soma_respostas_gestorMe / total_respostas_gestorMe if total_respostas_gestorMe > 0 else 0  ),1)

        media_totalAv = round(((media_geral_gestorMe + media_geral_logado) / 2),2)

        total_avaliacoes_gestorMe = len(avaliacoesGestorMe)


#############################################################################


        # Calcular a média das respostas dos avaliados pelo avaliador logado
        avaliacoes_avaliados_logado = Avaliacao.objects.filter(avaliado_id__in=selected_avaliados, avaliador=avaliador_logado)
        avaliacoes_avaliados_logado = avaliacoes_avaliados_logado.filter(tipo='Avaliação Geral')
        
        # Filtrar avaliações por data
        if data_inicio:
            data_inicio = pd.to_datetime(data_inicio)
            avaliacoes_avaliados_logado = avaliacoes_avaliados_logado.filter(create_at__gte=data_inicio)
        if data_fim:
            data_fim = pd.to_datetime(data_fim)
            avaliacoes_avaliados_logado = avaliacoes_avaliados_logado.filter(create_at__lte=data_fim)

        perguntas_respostas_avaliados_logado = []
        for avaliacao in avaliacoes_avaliados_logado:
            if isinstance(avaliacao.perguntasRespostas, str):
                perguntas_respostas_avaliados_logado.append(json.loads(avaliacao.perguntasRespostas))
            else:
                perguntas_respostas_avaliados_logado.append(avaliacao.perguntasRespostas)

        media_respostas_avaliados_logado = {}
        count_respostas_avaliados_logado = {}
        total_respostas_avaliados_logado = 0
        soma_respostas_avaliados_logado = 0

        for pr in perguntas_respostas_avaliados_logado:
            for pergunta, dados in pr.items():
                if pergunta not in media_respostas_avaliados_logado:
                    media_respostas_avaliados_logado[pergunta] = 0
                    count_respostas_avaliados_logado[pergunta] = 0
                resposta = dados.get('resposta', None)
                if resposta == "" or resposta is None or resposta == "nao_se_aplica":
                    # Ignora respostas vazias ou None
                    continue
                try:
                    resposta = int(resposta)    
                except ValueError:
                    resposta = 0  # ou outro valor padrão que você considere apropriado

                media_respostas_avaliados_logado[pergunta] += resposta
                count_respostas_avaliados_logado[pergunta] += 1
                soma_respostas_avaliados_logado += resposta
                total_respostas_avaliados_logado += 1

        for pergunta in media_respostas_avaliados_logado:
            if count_respostas_avaliados_logado[pergunta] > 0:
                media_respostas_avaliados_logado[pergunta] /= count_respostas_avaliados_logado[pergunta]

        media_geral_avaliados_logado = round((soma_respostas_avaliados_logado / total_respostas_avaliados_logado if total_respostas_avaliados_logado > 0 else 0), 1)
        total_avaliacoes_avaliados_logado = len(avaliacoes_avaliados_logado)

##################Gestor
        avaliacoes_avaliados_logadoMe = Avaliacao.objects.filter(avaliado_id__in=selected_avaliados, avaliador=avaliador_logado)
        avaliacoes_avaliados_logadoMe = avaliacoes_avaliados_logadoMe.filter(tipo='Avaliação do Gestor') 

        # Filtrar avaliações por data
        if data_inicio:
            data_inicio = pd.to_datetime(data_inicio)
            avaliacoes_avaliados_logadoMe = avaliacoes_avaliados_logadoMe.filter(create_at__gte=data_inicio)
        if data_fim:
            data_fim = pd.to_datetime(data_fim)
            avaliacoes_avaliados_logadoMe = avaliacoes_avaliados_logadoMe.filter(create_at__lte=data_fim)

            
        perguntas_respostas_avaliados_logadoMe = []
        for avaliacao in avaliacoes_avaliados_logadoMe:
            if isinstance(avaliacao.perguntasRespostas, str):
                perguntas_respostas_avaliados_logadoMe.append(json.loads(avaliacao.perguntasRespostas))
            else:
                perguntas_respostas_avaliados_logadoMe.append(avaliacao.perguntasRespostas)

        media_respostas_avaliados_logadoMe = {}
        count_respostas_avaliados_logadoMe = {}
        total_respostas_avaliados_logadoMe = 0
        soma_respostas_avaliados_logadoMe = 0

        for pr in perguntas_respostas_avaliados_logadoMe:
            for pergunta, dados in pr.items():
                if pergunta not in media_respostas_avaliados_logadoMe:
                    media_respostas_avaliados_logadoMe[pergunta] = 0
                    count_respostas_avaliados_logadoMe[pergunta] = 0
                resposta = dados.get('resposta', None)
                if resposta == "" or resposta is None or resposta == "nao_se_aplica":
                    # Ignora respostas vazias ou None
                    continue
                try:
                    resposta = int(resposta)    
                except ValueError:
                    resposta = 0  # ou outro valor padrão que você considere apropriado

                media_respostas_avaliados_logadoMe[pergunta] += resposta
                count_respostas_avaliados_logadoMe[pergunta] += 1
                soma_respostas_avaliados_logadoMe += resposta
                total_respostas_avaliados_logadoMe += 1

        for pergunta in media_respostas_avaliados_logadoMe:
            if count_respostas_avaliados_logadoMe[pergunta] > 0:
                media_respostas_avaliados_logadoMe[pergunta] /= count_respostas_avaliados_logadoMe[pergunta]

        media_geral_avaliados_logadoMe = round((soma_respostas_avaliados_logadoMe / total_respostas_avaliados_logadoMe if total_respostas_avaliados_logadoMe > 0 else 0), 1)
        total_avaliacoes_avaliados_logadoMe = len(avaliacoes_avaliados_logadoMe)
        
        media_totalAva = round(((media_geral_avaliados_logado + media_geral_avaliados_logadoMe) / 2),2)


        # Calcular total de avaliados sem avaliação no período para o avaliador logado
        avaliados = avaliador_logado.avaliados.all()
        avaliados_com_avaliacao = Avaliacao.objects.filter(periodo=periodo, avaliado__in=avaliados).values_list('avaliado_id', flat=True)
        avaliados_sem_avaliacao_logado = avaliados.exclude(id__in=avaliados_com_avaliacao)
        total_avaliados_sem_avaliacao_logado = avaliados_sem_avaliacao_logado.count()

        response_data = {
            'media_respostas_logado': media_respostas_logado,
            'total_avaliacoes_logado': total_avaliacoes_logado,
            'filtered_data': filtered_data,
            'media_respostas_avaliados_logado': media_respostas_avaliados_logado,
            'media_geral_logado': media_geral_logado,
            'media_geral_avaliados_logado': media_geral_avaliados_logado,
            'total_avaliacoes_avaliados_logado': total_avaliacoes_avaliados_logado,
            'total_avaliados_sem_avaliacao_logado': total_avaliados_sem_avaliacao_logado,
            'media_geral_gestorMe': media_geral_gestorMe,
            'total_avaliacoes_gestorMe': total_avaliacoes_gestorMe,
            'media_respostas_gestorMe' : media_respostas_gestorMe,
            'media_totalAv': media_totalAv,
            'media_respostas_avaliados_logadoMe': media_respostas_avaliados_logadoMe,
            'media_geral_avaliados_logadoMe' : media_geral_avaliados_logadoMe,
            'total_avaliacoes_avaliados_logadoMe':total_avaliacoes_avaliados_logadoMe,
            'media_totalAva':media_totalAva
        }

        return JsonResponse(response_data, safe=False)
