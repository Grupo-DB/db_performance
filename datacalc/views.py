import json
from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from django.http import JsonResponse
import pandas as pd
from management.models import Colaborador,Avaliacao,Ambiente
from datetime import datetime
from django.utils import timezone
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
        if 'data_nascimento' in df.columns:
            df['data_nascimento'] = pd.to_datetime(df['data_nascimento']).dt.date
            df['idade'] = (hoje - df['data_nascimento']).apply(lambda x: x.days // 365)
            media_idade = round(df['idade'].mean())
        else:
            media_idade = 0

        if 'data_admissao' in df.columns:
            df['data_admissao'] = pd.to_datetime(df['data_admissao']).dt.date
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
        media_salario_por_ambiente = df.groupby('ambiente_id')['salario'].mean().to_dict()
        # colaboradores_por_ambiente = {f'{k[0]}_{k[1]}': v for k, v in grouped3.items()}
        # grouped4 = df.groupby('raca')['instrucao'].value_counts()
        # instrucao_por_raca = {f'{k[0]}_{k[1]}': v for k, v in grouped2.items()}
        #instrucao_por_raca = df.groupby('genero')['instrucao'].value_counts().to_dict()
        # Filtrando a tabela Avaliacao com base nos IDs dos colaboradores filtrados
        # avaliado_ids = df['id'].tolist()
        # avaliacao_queryset = Avaliacao.objects.filter(avaliado_id__in=avaliado_ids)
        # avaliacao_df = pd.DataFrame(avaliacao_queryset.values())


        # Calcular a média das respostas das avaliações gerais
        avaliacoes = Avaliacao.objects.filter(avaliado_id__in=queryset.values_list('id', flat=True))
        avaliacoes = avaliacoes.filter(tipo='Avaliação Geral')
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
                resposta = dados.get('resposta', 0)
                media_respostas[pergunta] += resposta
                count_respostas[pergunta] += 1
                soma_respostas += resposta
                total_respostas += 1


        for pergunta in media_respostas:
            if count_respostas[pergunta] > 0:
                media_respostas[pergunta] /= count_respostas[pergunta]

        media_geral = round((soma_respostas / total_respostas if total_respostas > 0 else 0  ),1)          
        
        total_avaliacoes = len(avaliacoes)       
        total_feedbacks = len(avaliacoes.filter(feedback=1))
        percentComplete =(total_feedbacks / total_avaliacoes) * 100 if total_avaliacoes else 0;

###############################################################################################################################


        avaliacoesGestor = Avaliacao.objects.filter(avaliado_id__in=queryset.values_list('id', flat=True))
        avaliacoesGestor = avaliacoesGestor.filter(tipo='Avaliação do Gestor')
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
                resposta = dados.get('resposta', 0)
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
        
        total_avaliacoes_geral = total_avaliacoes + total_avaliacoes_gestor
        total_feedbacks_geral = total_feedbacks + total_feedbacks_gestor

        percentCompleteGeral = (total_feedbacks_geral / total_avaliacoes_geral) * 100  if total_avaliacoes_geral else 0;

        response_data = {
            'total_colaboradores': total_colaboradores,
            'total_avaliacoes': total_avaliacoes,
            'media_salarios': media_salarios,
            'total_feedbacks':total_feedbacks,
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
            'total_avaliacoes':total_avaliacoes,
            'total_avaliacoes_gestor':total_avaliacoes_gestor,
            'media_respostas': media_respostas,
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

        # if df.empty:
        #     return JsonResponse({
        #         'total_avaliacoes': len(avaliacoes),
        #         'filtered_data': [],
        #         'media_geral': 0,
        #         'media_respostas': {}
        #     })

        # if 'salario' not in df.columns:
        #     return JsonResponse({
        #         'total_colaboradores': len(df),
        #         'filtered_data': df.to_dict(orient='records'),
        #         'media_geral': 0,
        #         #'total_avaliacoes': len(avaliacoes),
        #         'media_respostas': {}
        #     })

      
        
        campos_necessarios = ['id', 'tipo','avaliado_id','avaliador_id','periodo']
        filtered_data = df[campos_necessarios].to_dict(orient='records')
        # Calcular a média das respostas das avaliações gerais

        avaliacoes = Avaliacao.objects.filter(avaliador_id__in=selected_avaliadores)
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
                resposta = dados.get('resposta', 0)
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
                resposta = dados.get('resposta', 0)
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