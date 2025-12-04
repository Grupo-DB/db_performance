from django.shortcuts import render
import requests
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import viewsets, status as http_status
from .models import Analise, AnaliseEnsaio, AnaliseCalculo
from rest_framework.decorators import action
from .serializer import AnaliseSerializer, AnaliseEnsaioSerializer, AnaliseCalculoSerializer
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.conf import settings
from openai import AzureOpenAI
from openai import APIError
import pandas as pd

# URLs e configurações da sua API do Azure OpenAI
AZURE_OPENAI_ENDPOINT = "https://troop-mg863zkh-eastus2.cognitiveservices.azure.com/"
AZURE_OPENAI_DEPLOYMENT = "o4-mini-labDb"
AZURE_OPENAI_API_VERSION = "2024-04-01-preview"

@method_decorator(csrf_exempt, name='dispatch')
class AnaliseViewSet(viewsets.ModelViewSet):
    queryset = Analise.objects.all()
    serializer_class = AnaliseSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='abertas')
    def abertas(self, request):
        analises = Analise.objects.filter(
            finalizada=0,
        )
        serializer = self.get_serializer(analises, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='fechadas')
    def fechadas(self, request):
        analises = Analise.objects.filter(
            finalizada=1,
        )
        serializer = self.get_serializer(analises, many=True)
        return Response(serializer.data)
    
 
    @csrf_exempt
    @action(detail=False, methods=['post'], url_path='resultados-anteriores')
    def resultados_anteriores(self, request):
        """
        Busca resultados anteriores de análises com o mesmo cálculo e ensaios,
        retornando apenas uma ocorrência por análise (últimas 5 análises).
        """
        if request.method == 'POST':
            data = request.data
            calculo_descricao = data.get('calculo')
            ensaio_ids = data.get('ensaioIds', [])
            ensaio_nome = data.get('ensaio_nome', None)
            limit = int(data.get('limit', 5))

            print(f"✅ POST - Parâmetros recebidos: calculo={calculo_descricao}, ensaio_ids={ensaio_ids}, ensaio_nome={ensaio_nome}, limit={limit}")

            if not calculo_descricao and not ensaio_ids and not ensaio_nome:
                return Response({
                    "error": "Parâmetros 'calculo', 'ensaioIds' ou 'ensaio_nome' são obrigatórios"
                }, status=400)

            try:
                from django.db.models import Q
                from .models import AnaliseCalculo, AnaliseEnsaio
                import json

                # Converter IDs para inteiros se existirem
                if ensaio_ids:
                    ensaio_ids = [int(id) for id in ensaio_ids]
                    print(f"✅ Buscando análises com ensaios IDs: {ensaio_ids}")

                # Inicializar queryset
                analises_filtradas = Analise.objects.all()

                # Filtrar por cálculo se fornecido
                if calculo_descricao:
                    analise_ids_com_calculo = AnaliseCalculo.objects.filter(
                        calculos=calculo_descricao
                    ).values_list('analise_id', flat=True)
                    analises_filtradas = analises_filtradas.filter(id__in=analise_ids_com_calculo)
                    print(f"✅ Análises com cálculo encontradas: {analises_filtradas.count()}")

                # Filtrar por ensaios se fornecido
                if ensaio_ids or ensaio_nome:
                    filtros_ensaio = Q()
                    
                    if ensaio_ids:
                        for ensaio_id in ensaio_ids:
                            filtros_ensaio |= Q(ensaios_utilizados__icontains=f'"id": {ensaio_id}')
                    
                    if ensaio_nome:
                        filtros_ensaio |= Q(ensaios_utilizados__icontains=f'"descricao": "{ensaio_nome}"')
                    
                    analises_com_ensaios = AnaliseEnsaio.objects.filter(filtros_ensaio).values_list('analise_id', flat=True)
                    analises_filtradas = analises_filtradas.filter(id__in=analises_com_ensaios)
                    print(f"✅ Análises com ensaios encontradas: {analises_filtradas.count()}")

                # Aplicar distinct, ordenação e limite
                analises_filtradas = analises_filtradas.distinct().order_by('-id')[:limit]
                print(f"✅ Análises filtradas final: {analises_filtradas.count()}")

                resultados = []
                analises_processadas = set()  # Para evitar duplicatas

                for analise in analises_filtradas:
                    if analise.id in analises_processadas:
                        continue
                    
                    analises_processadas.add(analise.id)
                    print(f"✅ Processando análise ID: {analise.id}")
                    
                    # Dados básicos da análise
                    analise_data = {
                        'analise_id': analise.id,
                        'amostra_numero': analise.amostra.numero if analise.amostra else None,
                        'data_analise': analise.data if hasattr(analise, 'data') else None,
                        'responsavel': None,
                        'digitador': None,
                    }

                    # Flag para saber se já encontrou um resultado para esta análise
                    resultado_encontrado = False

                    # Buscar resultado do cálculo se fornecido (MAIS RECENTE)
                    if calculo_descricao and not resultado_encontrado:
                        calculo_analise = AnaliseCalculo.objects.filter(
                            analise_id=analise.id,
                            calculos=calculo_descricao
                        ).order_by('-id').first()  # ← MAIS RECENTE
                        
                        if calculo_analise:
                            print(f"🔍 Cálculo encontrado para análise {analise.id}")
                            resultados.append({
                                **analise_data,
                                'tipo': 'CALCULO',
                                'resultado_calculo': calculo_analise.resultados,
                                'ensaio_id': None,
                                'ensaio_descricao': None,
                                'valor_ensaio': None,
                                'ensaio_responsavel': None,
                                'ensaio_digitador': None
                            })
                            resultado_encontrado = True

                    # Buscar ensaios se não encontrou cálculo ou se não tem cálculo (MAIS RECENTE)
                    if (ensaio_ids or ensaio_nome) and not resultado_encontrado:
                        filtros_ensaio = Q()
                        
                        if ensaio_ids:
                            for ensaio_id in ensaio_ids:
                                filtros_ensaio |= Q(ensaios_utilizados__icontains=f'"id": {ensaio_id}')
                        
                        if ensaio_nome:
                            filtros_ensaio |= Q(ensaios_utilizados__icontains=f'"descricao": "{ensaio_nome}"')
                        
                        # Buscar o MAIS RECENTE ensaio que corresponde
                        ensaio_encontrado = AnaliseEnsaio.objects.filter(
                            analise_id=analise.id
                        ).filter(filtros_ensaio).order_by('-id').first()  # ← MAIS RECENTE
                        
                        if ensaio_encontrado:
                            try:
                                # Processar JSON dos ensaios
                                if isinstance(ensaio_encontrado.ensaios_utilizados, list):
                                    ensaios_json = ensaio_encontrado.ensaios_utilizados
                                elif isinstance(ensaio_encontrado.ensaios_utilizados, str):
                                    ensaios_json = json.loads(ensaio_encontrado.ensaios_utilizados)
                                else:
                                    continue
                                
                                # Encontrar o ÚLTIMO ensaio que corresponde aos critérios (mais recente na lista)
                                ensaio_match = None
                                for ensaio in reversed(ensaios_json):  # ← REVERSO PARA PEGAR O MAIS RECENTE
                                    match_found = False
                                    
                                    # Verificar se corresponde aos critérios (usar OR, não AND)
                                    if ensaio_ids and ensaio.get('id') in ensaio_ids:
                                        match_found = True
                                    elif ensaio_nome and ensaio_nome.lower() in ensaio.get('descricao', '').lower():
                                        match_found = True
                                    
                                    if match_found:
                                        ensaio_match = ensaio
                                        break  # Pega o primeiro (que é o mais recente devido ao reversed)
                                
                                if ensaio_match:
                                    print(f"🔍 Ensaio encontrado: ID {ensaio_match.get('id')} - {ensaio_match.get('descricao')}")
                                    resultados.append({
                                        **analise_data,
                                        'tipo': 'ENSAIO',
                                        'resultado_calculo': None,
                                        'ensaio_id': ensaio_match.get('id'),
                                        'ensaio_descricao': ensaio_match.get('descricao'),
                                        'valor_ensaio': ensaio_match.get('valor'),
                                        'ensaio_responsavel': ensaio_match.get('responsavel'),
                                        'ensaio_digitador': ensaio_match.get('digitador'),
                                        'ensaio_tecnica': ensaio_match.get('tecnica'),
                                        'ensaio_funcao': ensaio_match.get('funcao'),
                                    })
                                    resultado_encontrado = True
                                            
                            except (json.JSONDecodeError, TypeError) as e:
                                print(f"❌ Erro ao processar JSON: {e}")
                                continue

                    # Se não encontrou nenhum resultado, mas a análise passou pelos filtros, adicionar um registro básico
                    if not resultado_encontrado:
                        print(f"🔍 Nenhum resultado específico encontrado para análise {analise.id}")
                        resultados.append({
                            **analise_data,
                            'tipo': 'ANALISE',
                            'resultado_calculo': None,
                            'ensaio_id': None,
                            'ensaio_descricao': None,
                            'valor_ensaio': None,
                            'ensaio_responsavel': None,
                            'ensaio_digitador': None
                        })

                print(f"✅ Total de resultados retornados: {len(resultados)}")
                return Response(resultados, status=200)

            except ValueError as e:
                print(f"❌ Erro de valor: {e}")
                return Response({
                    "error": "IDs dos ensaios devem ser números inteiros"
                }, status=400)
            except Exception as e:
                print(f"❌ Erro geral: {e}")
                import traceback
                traceback.print_exc()
                return Response({
                    "error": f"Erro interno do servidor: {str(e)}"
                }, status=500)

        return Response({
            "error": "Método não permitido. Use POST."
        }, status=405)

    @action(detail=True, methods=['post'])
    def update_finalizada(self, request, pk=None):
        try:
            analise = self.get_object()
            analise.finalizada = True
            analise.finalizada_at = timezone.now()
            analise.save()
            return Response({"status": "Análise finalizada com sucesso."}, status=200)
        except Analise.DoesNotExist:
            return Response({"error": "Análise não encontrada."}, status=404)
        
    @action(detail=True, methods=['post'])
    def update_aberta(self, request, pk=None):
        try:
            analise = self.get_object()
            analise.finalizada = False
            analise.finalizada_at = None
            analise.save()
            return Response({"status": "Análise reaberta com sucesso."}, status=200)
        except Analise.DoesNotExist:
            return Response({"error": "Análise não encontrada."}, status=404)

    @action(detail=True, methods=['post'])
    def update_laudo(self, request, pk=None):
        try:
            analise = self.get_object()
            analise.laudo = True
            analise.save()
            return Response({"status": "Análise marcada para laudo com sucesso."}, status=200)
        except Analise.DoesNotExist:
            return Response({"error": "Análise não encontrada."}, status=404)

    @action(detail=True, methods=['post'])
    def update_aprovada(self, request, pk=None):
        try:
            analise = self.get_object()
            analise.aprovada = True
            analise.aprovada_at = timezone.now()
            analise.save()
            return Response({"status": "Análise aprovada com sucesso."}, status=200)
        except Analise.DoesNotExist:
            return Response({"error": "Análise não encontrada."}, status=404)
        
    @action(detail=False, methods=['get'], url_path='calcs')
    def calcs(self, request):
        analises = Analise.objects.all()
        serializer = self.get_serializer(analises, many=True)
        serializer.analises = serializer.data
        df = pd.DataFrame(serializer.analises)
        total_aprovadas = Analise.objects.filter(aprovada=True).count()
        total_abertas = Analise.objects.filter(finalizada=False).count()
        total_laudos = Analise.objects.filter(laudo=True).count()

        total_status = {
            'Total Aprovadas': total_aprovadas,
            'Total Abertas': total_abertas,
            'Total Laudos': total_laudos
        }

        response_data = {
            'total_aprovadas': total_aprovadas,
            'total_abertas': total_abertas,
            'total_laudos': total_laudos,
            'total_status': total_status
        }
        return JsonResponse(response_data, safe=False)
                
class AnaliseEnsaioViewSet(viewsets.ModelViewSet):
    queryset = AnaliseEnsaio.objects.all()
    serializer_class = AnaliseEnsaioSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'], url_path='medias-ensaios-por-periodo')
    def medias_ensaios_por_periodo(self, request):
        """
        Retorna as médias dos valores dos ensaios agrupados por tipo de ensaio
        dentro de um período específico.
        
        Parâmetros esperados (POST):
        - ensaio_ids: lista de IDs de ensaios (opcional - se não informado, busca todos)
        - ensaio_descricao: descrição do ensaio para filtrar (opcional)
        - produto_ids: lista de IDs de produtos da amostra (opcional)
        - data_inicial: data inicial no formato YYYY-MM-DD
        - data_final: data final no formato YYYY-MM-DD
        """
        from django.db.models import Q
        from datetime import datetime
        import json
        
        data = request.data
        ensaio_ids = data.get('ensaios_ids', [])
        ensaio_descricao = data.get('ensaio_descricao')
        produto_ids = data.get('produto_ids', [])
        data_inicial = data.get('data_inicio')
        data_final = data.get('data_fim')
        
        # Validações
        if not data_inicial or not data_final:
            return Response({
                "error": "Parâmetros 'data_inicial' e 'data_final' são obrigatórios (formato: YYYY-MM-DD)"
            }, status=400)
        
        try:
            # Validar formato de data sem criar objeto datetime
            datetime.strptime(data_inicial, '%Y-%m-%d')
            datetime.strptime(data_final, '%Y-%m-%d')
            
            # Comparar strings de data diretamente
            if data_inicial > data_final:
                return Response({
                    "error": "A data_inicial deve ser anterior à data_final"
                }, status=400)
        except ValueError:
            return Response({
                "error": "Formato de data inválido. Use YYYY-MM-DD"
            }, status=400)
        
        # Filtrar análises finalizadas no período
        queryset = AnaliseEnsaio.objects.filter(
            analise__data__gte=data_inicial,
            analise__data__lte=data_final,
            #analise__finalizada=True
        )
        
        # Filtrar por ensaios específicos se fornecidos
        if ensaio_ids:
            ensaio_ids = [int(id) for id in ensaio_ids]
            filtros_ensaio = Q()
            for ensaio_id in ensaio_ids:
                filtros_ensaio |= Q(ensaios_utilizados__icontains=f'"id": {ensaio_id}')
            queryset = queryset.filter(filtros_ensaio)
        
        if ensaio_descricao:
            queryset = queryset.filter(
                ensaios_utilizados__icontains=f'"descricao": "{ensaio_descricao}"'
            )
        
        # Filtrar por produto da amostra se fornecido
        if produto_ids:
            if isinstance(produto_ids, list):
                queryset = queryset.filter(analise__amostra__produto_amostra_id__in=produto_ids)
            else:
                queryset = queryset.filter(analise__amostra__produto_amostra_id=produto_ids)
        
        # Processar resultados e calcular médias manualmente
        ensaios_agrupados = {}
        
        # Dicionário para rastrear o último valor de cada ensaio por análise
        # Formato: {analise_id: {key_ensaio: {dados}}}
        ensaios_por_analise = {}
        
        for analise_ensaio in queryset:
            try:
                # Parsear JSON dos ensaios
                if isinstance(analise_ensaio.ensaios_utilizados, list):
                    ensaios_json = analise_ensaio.ensaios_utilizados
                elif isinstance(analise_ensaio.ensaios_utilizados, str):
                    ensaios_json = json.loads(analise_ensaio.ensaios_utilizados)
                else:
                    continue
                
                analise_id = analise_ensaio.analise_id
                
                # Inicializar dicionário para esta análise se não existir
                if analise_id not in ensaios_por_analise:
                    ensaios_por_analise[analise_id] = {}
                
                # Processar cada ensaio (o último sobrescreve os anteriores)
                for ensaio in ensaios_json:
                    ensaio_id = ensaio.get('id')
                    ensaio_desc = ensaio.get('descricao', 'Sem descrição')
                    valor = ensaio.get('valor')
                    
                    # Pular se não tiver valor ou ID
                    if valor is None or ensaio_id is None:
                        continue
                    
                    # Filtrar por ensaio_ids se fornecido
                    if ensaio_ids and ensaio_id not in ensaio_ids:
                        continue
                    
                    # Filtrar por descrição se fornecida
                    if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                        continue
                    
                    # Converter valor para float
                    try:
                        valor_float = float(valor)
                    except (ValueError, TypeError):
                        continue
                    
                    # Armazenar o último valor para este ensaio nesta análise
                    key = f"{ensaio_id}_{ensaio_desc}"
                    ensaios_por_analise[analise_id][key] = {
                        'ensaio_id': ensaio_id,
                        'ensaio_descricao': ensaio_desc,
                        'valor': valor_float,
                        'unidade': ensaio.get('unidade', ''),
                        'analise_id': analise_id,
                        'amostra_numero': analise_ensaio.analise.amostra.numero if analise_ensaio.analise.amostra else None
                    }
            
            except (json.JSONDecodeError, TypeError) as e:
                continue
        
        # Adicionar os valores únicos ao agrupamento global
        for analise_id, ensaios_dict in ensaios_por_analise.items():
            for key, dados in ensaios_dict.items():
                if key not in ensaios_agrupados:
                    ensaios_agrupados[key] = {
                        'ensaio_id': dados['ensaio_id'],
                        'ensaio_descricao': dados['ensaio_descricao'],
                        'valores': [],
                        'unidade': dados['unidade'],
                        'detalhes': []
                    }
                
                # Adiciona apenas uma vez por ensaio por análise
                ensaios_agrupados[key]['valores'].append(dados['valor'])
                ensaios_agrupados[key]['detalhes'].append({
                    'analise_id': dados['analise_id'],
                    'amostra_numero': dados['amostra_numero'],
                    'valor': dados['valor']
                })
        
        # Calcular estatísticas
        resultados = []
        for key, dados in ensaios_agrupados.items():
            valores = dados['valores']
            detalhes = dados['detalhes']
            if valores:
                media = sum(valores) / len(valores)
                minimo = min(valores)
                maximo = max(valores)
                
                resultados.append({
                    'ensaio_id': dados['ensaio_id'],
                    'ensaio_descricao': dados['ensaio_descricao'],
                    'unidade': dados['unidade'],
                    'media': round(media, 4),
                    'valor_minimo': minimo,
                    'valor_maximo': maximo,
                    'quantidade_medicoes': len(valores),
                    'detalhes': detalhes,
                    'periodo': {
                        'data_inicial': data_inicial,
                        'data_final': data_final
                    }
                })
        
        # Ordenar por descrição do ensaio
        resultados.sort(key=lambda x: x['ensaio_descricao'])
        
        return Response({
            'total_ensaios': len(resultados),
            'resultados': resultados
        })
    
    @action(detail=False, methods=['post'], url_path='medias-campos-json-por-periodo')
    def medias_campos_json_por_periodo(self, request):
        """
        Retorna as médias dos campos JSON (substrato, superficial, retracao, etc.)
        agrupados por campo dentro de um período específico.
        
        Cada campo JSON possui estrutura: {"media": valor, "linhas": [...]}
        Este endpoint calcula a média das "medias" de cada campo.
        
        Parâmetros esperados (POST):
        - campos: lista de nomes de campos para filtrar (opcional - se não informado, busca todos)
          Campos disponíveis: substrato, superficial, retracao, elasticidade, flexao, 
          compressao, peneiras, peneiras_umidas, variacao_dimensional, variacao_massa,
          tracao_normal, tracao_submersa, tracao_estufa, tracao_tempo_aberto, 
          modulo_elasticidade, deslizamento
        - local_coleta: filtrar por local de coleta (opcional)
        - laboratorio: filtrar por laboratório (opcional)
        - produto_ids: lista de IDs de produtos da amostra (opcional)
        - data_inicio: data inicial no formato YYYY-MM-DD
        - data_fim: data final no formato YYYY-MM-DD
        - apenas_finalizadas: boolean - se True, filtra apenas finalizadas (default: False)
        """
        from django.db.models import Q
        from datetime import datetime
        from controleQualidade.analise.models import Analise
        import json
        
        data = request.data
        campos = data.get('campos', [])
        local_coleta = data.get('local_coleta')
        laboratorio = data.get('laboratorio', [])
        produto_ids = data.get('produto_ids', [])
        data_inicial = data.get('data_inicio')
        data_final = data.get('data_fim')
        apenas_finalizadas = data.get('apenas_finalizadas', False)
        
        # Validações
        if not data_inicial or not data_final:
            return Response({
                "error": "Parâmetros 'data_inicio' e 'data_fim' são obrigatórios (formato: YYYY-MM-DD)"
            }, status=400)
        
        try:
            datetime.strptime(data_inicial, '%Y-%m-%d')
            datetime.strptime(data_final, '%Y-%m-%d')
            
            if data_inicial > data_final:
                return Response({
                    "error": "A data_inicio deve ser anterior à data_fim"
                }, status=400)
        except ValueError:
            return Response({
                "error": "Formato de data inválido. Use YYYY-MM-DD"
            }, status=400)
        
        # Lista de campos JSON disponíveis na Analise
        campos_disponiveis = [
            'substrato', 'superficial', 'retracao', 'elasticidade', 
            'flexao', 'compressao', 'peneiras', 'peneiras_umidas',
            'variacao_dimensional', 'variacao_massa', 'tracao_normal',
            'tracao_submersa', 'tracao_estufa', 'tracao_tempo_aberto',
            'modulo_elasticidade', 'deslizamento'
        ]
        
        # Se campos foram especificados, validar
        if campos:
            campos_invalidos = [c for c in campos if c not in campos_disponiveis]
            if campos_invalidos:
                return Response({
                    "error": f"Campos inválidos: {', '.join(campos_invalidos)}",
                    "campos_disponiveis": campos_disponiveis
                }, status=400)
            campos_para_processar = campos
        else:
            campos_para_processar = campos_disponiveis
        
        # Filtrar análises no período
        if apenas_finalizadas:
            queryset = Analise.objects.filter(
                finalizada_at__gte=data_inicial,
                finalizada_at__lte=data_final,
                finalizada=True
            ).select_related('amostra')
        else:
            queryset = Analise.objects.filter(
                data__gte=data_inicial,
                data__lte=data_final
            ).select_related('amostra')
        
        # Filtrar por local de coleta
        if local_coleta:
            if isinstance(local_coleta, list):
                filtros_local = Q()
                for local in local_coleta:
                    filtros_local |= Q(amostra__local_coleta__icontains=local)
                queryset = queryset.filter(filtros_local)
            else:
                queryset = queryset.filter(amostra__local_coleta__icontains=local_coleta)
        
        # Filtrar por laboratório
        if laboratorio:
            if isinstance(laboratorio, list):
                filtros_lab = Q()
                for lab in laboratorio:
                    filtros_lab |= Q(amostra__laboratorio__icontains=lab)
                queryset = queryset.filter(filtros_lab)
            else:
                queryset = queryset.filter(amostra__laboratorio__icontains=laboratorio)
        
        # Filtrar por produto
        if produto_ids:
            if isinstance(produto_ids, list):
                queryset = queryset.filter(amostra__produto_amostra_id__in=produto_ids)
            else:
                queryset = queryset.filter(amostra__produto_amostra_id=produto_ids)
        
        # Processar resultados e calcular médias
        campos_agrupados = {}
        
        # Dicionário para rastrear o valor mais recente de cada campo por análise
        campos_por_analise = {}
        
        for analise in queryset:
            analise_id = analise.id
            
            # Inicializar dicionário para esta análise se ainda não existe
            if analise_id not in campos_por_analise:
                campos_por_analise[analise_id] = {}
            
            # Para cada campo JSON solicitado
            for campo_nome in campos_para_processar:
                campo_valor = getattr(analise, campo_nome, None)
                
                if not campo_valor:
                    continue
                
                try:
                    # Se for string, parsear JSON
                    if isinstance(campo_valor, str):
                        campo_json = json.loads(campo_valor)
                    else:
                        campo_json = campo_valor
                    
                    # Verificar se tem a estrutura esperada com "media"
                    if isinstance(campo_json, dict) and 'media' in campo_json:
                        media_valor = campo_json.get('media')
                        
                        # Pular se media for None ou não for numérico
                        if media_valor is None:
                            continue
                        
                        try:
                            media_float = float(media_valor)
                        except (ValueError, TypeError):
                            continue
                        
                        # Armazenar o valor mais recente para este campo nesta análise
                        # (sobrescreve se já existir)
                        campos_por_analise[analise_id][campo_nome] = {
                            'valor': media_float,
                            'amostra_numero': analise.amostra.numero if analise.amostra else None
                        }
                
                except (json.JSONDecodeError, TypeError, AttributeError):
                    continue
        
        # Agrupar valores únicos por campo (apenas um valor por análise)
        for analise_id, campos in campos_por_analise.items():
            for campo_nome, dados in campos.items():
                if campo_nome not in campos_agrupados:
                    campos_agrupados[campo_nome] = {
                        'campo': campo_nome,
                        'valores': [],
                        'analises_ids': [],
                        'detalhes': []
                    }
                
                campos_agrupados[campo_nome]['valores'].append(dados['valor'])
                campos_agrupados[campo_nome]['analises_ids'].append(analise_id)
                campos_agrupados[campo_nome]['detalhes'].append({
                    'analise_id': analise_id,
                    'amostra_numero': dados['amostra_numero'],
                    'valor': round(dados['valor'], 4)
                })
        
        # Calcular estatísticas
        resultados = []
        for campo_nome, dados in campos_agrupados.items():
            valores = dados['valores']
            analises_ids = dados['analises_ids']
            detalhes = dados['detalhes']
            if valores:
                media = sum(valores) / len(valores)
                minimo = min(valores)
                maximo = max(valores)
                
                resultados.append({
                    'campo': campo_nome,
                    'campo_formatado': campo_nome.replace('_', ' ').title(),
                    'media': round(media, 4),
                    'valor_minimo': round(minimo, 4),
                    'valor_maximo': round(maximo, 4),
                    'quantidade_analises': len(valores),
                    'analises_ids': analises_ids,
                    'detalhes': detalhes,
                    'periodo': {
                        'data_inicial': data_inicial,
                        'data_final': data_final
                    }
                })
        
        # Ordenar por nome do campo
        resultados.sort(key=lambda x: x['campo'])
        
        return Response({
            'total_campos': len(resultados),
            'resultados': resultados
        })
    
    @action(detail=False, methods=['post'], url_path='totais-tempo-por-periodo')
    def totais_tempo_por_periodo(self, request):
        """
        Retorna os totais de tempo previsto e tempo trabalhado dos ensaios
        agrupados por período e com opção de filtrar por análise.
        
        Parâmetros esperados (POST):
        - data_inicial: data inicial no formato YYYY-MM-DD (obrigatório)
        - data_final: data final no formato YYYY-MM-DD (obrigatório)
        - analise_id: ID da análise específica (opcional)
        - ensaio_ids: lista de IDs de ensaios (opcional)
        - ensaio_descricao: descrição do ensaio para filtrar (opcional)
        - local_coleta: filtrar por local de coleta da amostra (opcional)
        - apenas_finalizadas: boolean - se True, filtra apenas finalizadas (default: False)
        - agrupar_por_ensaio: boolean - se True, agrupa por ensaio (default: False)
        """
        from django.db.models import Q
        from datetime import datetime
        import json
        
        data = request.data
        data_inicial = data.get('data_inicial')
        data_final = data.get('data_final')
        analise_id = data.get('analise_id')
        ensaio_ids = data.get('ensaio_ids', [])
        ensaio_descricao = data.get('ensaio_descricao')
        local_coleta = data.get('local_coleta',[])
        apenas_finalizadas = data.get('apenas_finalizadas', False)
        agrupar_por_ensaio = data.get('agrupar_por_ensaio', False)
        
        # Validações
        if not data_inicial or not data_final:
            return Response({
                "error": "Parâmetros 'data_inicial' e 'data_final' são obrigatórios (formato: YYYY-MM-DD)"
            }, status=400)
        
        try:
            data_inicial_obj = datetime.strptime(data_inicial, '%Y-%m-%d')
            data_final_obj = datetime.strptime(data_final, '%Y-%m-%d')
            
            if data_inicial_obj > data_final_obj:
                return Response({
                    "error": "A data_inicial deve ser anterior à data_final"
                }, status=400)
        except ValueError:
            return Response({
                "error": "Formato de data inválido. Use YYYY-MM-DD"
            }, status=400)
        
        # Filtrar análises no período
        queryset = AnaliseEnsaio.objects.filter(
            analise__data__gte=data_inicial,
            analise__data__lte=data_final
        )
        
        # Filtrar apenas finalizadas se solicitado
        if apenas_finalizadas:
            queryset = queryset.filter(analise__finalizada=True)
        
        # Filtrar por análise específica se fornecido
        if analise_id:
            queryset = queryset.filter(analise_id=analise_id)
        
        # Filtrar por local de coleta da amostra se fornecido
        if local_coleta:
            queryset = queryset.filter(analise__amostra__local_coleta__icontains=local_coleta)
        
        # Filtrar por ensaios específicos se fornecidos
        if ensaio_ids:
            ensaio_ids = [int(id) for id in ensaio_ids]
            filtros_ensaio = Q()
            for ensaio_id in ensaio_ids:
                filtros_ensaio |= Q(ensaios_utilizados__icontains=f'"id": {ensaio_id}')
            queryset = queryset.filter(filtros_ensaio)
        
        # Função auxiliar para converter tempo em minutos
        def tempo_para_minutos(tempo_str):
            """
            Converte string de tempo para minutos.
            Formatos suportados: 
            - '2h', '30min', '1h30min'
            - '2 Horas', '540 Minutos', '90 minutos'
            - '2 Turnos' (considerando 8h por turno)
            - Números: '120' (assume minutos)
            """
            if not tempo_str:
                return 0
            
            tempo_str = str(tempo_str).lower().strip()
            total_minutos = 0
            
            try:
                # Remover acentos e normalizar
                tempo_str = tempo_str.replace('ç', 'c').replace('õ', 'o').replace('ã', 'a')
                
                # Turnos (8 horas cada)
                if 'turno' in tempo_str:
                    numero = ''.join(filter(str.isdigit, tempo_str.split('turno')[0]))
                    if numero:
                        return float(numero) * 8 * 60
                    return 0
                
                # Horas
                if 'hora' in tempo_str or 'h' in tempo_str:
                    # Separar por 'hora' ou 'h'
                    if 'hora' in tempo_str:
                        partes = tempo_str.split('hora')
                    else:
                        partes = tempo_str.split('h')
                    
                    # Extrair número antes de 'hora' ou 'h'
                    numero_str = partes[0].strip()
                    numero = ''.join(filter(lambda x: x.isdigit() or x == '.', numero_str))
                    if numero:
                        horas = float(numero)
                        total_minutos += horas * 60
                    
                    # Verificar se há minutos depois
                    if len(partes) > 1:
                        resto = partes[1]
                        if 'min' in resto:
                            numero_min = ''.join(filter(lambda x: x.isdigit() or x == '.', resto.split('min')[0]))
                            if numero_min:
                                total_minutos += float(numero_min)
                
                # Minutos
                elif 'min' in tempo_str:
                    numero = ''.join(filter(lambda x: x.isdigit() or x == '.', tempo_str.split('min')[0]))
                    if numero:
                        total_minutos += float(numero)
                
                # Apenas número (assume minutos)
                elif tempo_str.replace('.', '').replace(',', '').isdigit():
                    total_minutos = float(tempo_str.replace(',', '.'))
                
            except Exception as e:
                print(f"Erro ao converter tempo '{tempo_str}': {e}")
                return 0
            
            return total_minutos
        
        def minutos_para_horas_str(minutos):
            """Converte minutos para formato legível (ex: '2h 30min')"""
            if minutos == 0:
                return '0min'
            
            horas = int(minutos // 60)
            mins = int(minutos % 60)
            
            if horas > 0 and mins > 0:
                return f'{horas}h {mins}min'
            elif horas > 0:
                return f'{horas}h'
            else:
                return f'{mins}min'
        
        # Processar resultados
        # Criar cache de ensaios do modelo para buscar tempo_trabalho
        from controleQualidade.ensaio.models import Ensaio
        ensaios_cache = {}
        
        if agrupar_por_ensaio:
            # Agrupar por ensaio
            ensaios_agrupados = {}
            
            for analise_ensaio in queryset:
                try:
                    # Parsear JSON dos ensaios
                    if isinstance(analise_ensaio.ensaios_utilizados, list):
                        ensaios_json = analise_ensaio.ensaios_utilizados
                    elif isinstance(analise_ensaio.ensaios_utilizados, str):
                        ensaios_json = json.loads(analise_ensaio.ensaios_utilizados)
                    else:
                        continue
                    
                    # Processar cada ensaio
                    for ensaio in ensaios_json:
                        ensaio_id = ensaio.get('id')
                        ensaio_desc = ensaio.get('descricao', 'Sem descrição')
                        tempo_previsto = ensaio.get('tempo_previsto')
                        tempo_trabalho = ensaio.get('tempo_trabalho')
                        
                        if ensaio_id is None:
                            continue
                        
                        # Filtrar por descrição se fornecida
                        if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                            continue
                        
                        # Se tempo_trabalho não está no JSON, buscar do modelo Ensaio
                        if not tempo_trabalho:
                            if ensaio_id not in ensaios_cache:
                                try:
                                    ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                    ensaios_cache[ensaio_id] = {
                                        'tempo_previsto': ensaio_modelo.tempo_previsto,
                                        'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                    }
                                except Ensaio.DoesNotExist:
                                    ensaios_cache[ensaio_id] = {
                                        'tempo_previsto': None,
                                        'tempo_trabalho': None
                                    }
                            
                            tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                            # Se tempo_previsto também não está no JSON, usar do modelo
                            if not tempo_previsto:
                                tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                        
                        # Agrupar por ID do ensaio
                        key = f"{ensaio_id}_{ensaio_desc}"
                        if key not in ensaios_agrupados:
                            ensaios_agrupados[key] = {
                                'ensaio_id': ensaio_id,
                                'ensaio_descricao': ensaio_desc,
                                'tempo_previsto_total_minutos': 0,
                                'tempo_trabalho_total_minutos': 0,
                                'quantidade_execucoes': 0
                            }
                        
                        ensaios_agrupados[key]['tempo_previsto_total_minutos'] += tempo_para_minutos(tempo_previsto)
                        ensaios_agrupados[key]['tempo_trabalho_total_minutos'] += tempo_para_minutos(tempo_trabalho)
                        ensaios_agrupados[key]['quantidade_execucoes'] += 1
                
                except (json.JSONDecodeError, TypeError):
                    continue
            
            # Processar campos JSON do modelo Analise que contêm ensaios
            campos_json_analise = [
                'substrato', 'superficial', 'retracao', 'elasticidade', 
                'flexao', 'compressao', 'peneiras', 'peneiras_umidas',
                'variacao_dimensional', 'variacao_massa', 'tracao_normal',
                'tracao_submersa', 'tracao_estufa', 'tracao_tempo_aberto',
                'modulo_elasticidade', 'deslizamento'
            ]
            
            # Buscar análises do período para processar campos JSON
            analises_periodo = Analise.objects.filter(
                data__gte=data_inicial,
                data__lte=data_final
            )
            
            if apenas_finalizadas:
                analises_periodo = analises_periodo.filter(finalizada=True)
            
            if analise_id:
                analises_periodo = analises_periodo.filter(id=analise_id)
            
            if local_coleta:
                analises_periodo = analises_periodo.filter(amostra__local_coleta__icontains=local_coleta)
            
            for analise in analises_periodo:
                for campo_nome in campos_json_analise:
                    campo_valor = getattr(analise, campo_nome, None)
                    
                    if not campo_valor:
                        continue
                    
                    try:
                        # Se for string, parsear JSON
                        if isinstance(campo_valor, str):
                            campo_json = json.loads(campo_valor)
                        else:
                            campo_json = campo_valor
                        
                        # Verificar se é uma lista de ensaios
                        if isinstance(campo_json, list):
                            for item in campo_json:
                                if isinstance(item, dict):
                                    ensaio_id = item.get('id')
                                    ensaio_desc = item.get('descricao', campo_nome.replace('_', ' ').title())
                                    tempo_previsto = item.get('tempo_previsto')
                                    tempo_trabalho = item.get('tempo_trabalho')
                                    
                                    # Filtrar por descrição se fornecida
                                    if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                                        continue
                                    
                                    # Buscar do modelo Ensaio se necessário
                                    if ensaio_id and not tempo_trabalho:
                                        if ensaio_id not in ensaios_cache:
                                            try:
                                                ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                                ensaios_cache[ensaio_id] = {
                                                    'tempo_previsto': ensaio_modelo.tempo_previsto,
                                                    'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                                }
                                            except Ensaio.DoesNotExist:
                                                ensaios_cache[ensaio_id] = {
                                                    'tempo_previsto': None,
                                                    'tempo_trabalho': None
                                                }
                                        
                                        tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                                        if not tempo_previsto:
                                            tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                                    
                                    # Agrupar por ID do ensaio
                                    key = f"{ensaio_id}_{ensaio_desc}"
                                    if key not in ensaios_agrupados:
                                        ensaios_agrupados[key] = {
                                            'ensaio_id': ensaio_id,
                                            'ensaio_descricao': ensaio_desc,
                                            'tempo_previsto_total_minutos': 0,
                                            'tempo_trabalho_total_minutos': 0,
                                            'quantidade_execucoes': 0
                                        }
                                    
                                    ensaios_agrupados[key]['tempo_previsto_total_minutos'] += tempo_para_minutos(tempo_previsto)
                                    ensaios_agrupados[key]['tempo_trabalho_total_minutos'] += tempo_para_minutos(tempo_trabalho)
                                    ensaios_agrupados[key]['quantidade_execucoes'] += 1
                        
                        # Verificar se é um dicionário com campos tempo diretos
                        elif isinstance(campo_json, dict):
                            ensaio_id = campo_json.get('id')
                            ensaio_desc = campo_json.get('descricao', campo_nome.replace('_', ' ').title())
                            tempo_previsto = campo_json.get('tempo_previsto')
                            tempo_trabalho = campo_json.get('tempo_trabalho')
                            
                            # Filtrar por descrição se fornecida
                            if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                                continue
                            
                            if tempo_previsto or tempo_trabalho:
                                # Buscar do modelo Ensaio se necessário
                                if ensaio_id and not tempo_trabalho:
                                    if ensaio_id not in ensaios_cache:
                                        try:
                                            ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                            ensaios_cache[ensaio_id] = {
                                                'tempo_previsto': ensaio_modelo.tempo_previsto,
                                                'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                            }
                                        except Ensaio.DoesNotExist:
                                            ensaios_cache[ensaio_id] = {
                                                'tempo_previsto': None,
                                                'tempo_trabalho': None
                                            }
                                    
                                    tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                                    if not tempo_previsto:
                                        tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                                
                                key = f"{ensaio_id}_{ensaio_desc}"
                                if key not in ensaios_agrupados:
                                    ensaios_agrupados[key] = {
                                        'ensaio_id': ensaio_id,
                                        'ensaio_descricao': ensaio_desc,
                                        'tempo_previsto_total_minutos': 0,
                                        'tempo_trabalho_total_minutos': 0,
                                        'quantidade_execucoes': 0
                                    }
                                
                                ensaios_agrupados[key]['tempo_previsto_total_minutos'] += tempo_para_minutos(tempo_previsto)
                                ensaios_agrupados[key]['tempo_trabalho_total_minutos'] += tempo_para_minutos(tempo_trabalho)
                                ensaios_agrupados[key]['quantidade_execucoes'] += 1
                    
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        continue
            
            # Formatar resultados
            resultados = []
            for key, dados in ensaios_agrupados.items():
                tempo_prev_min = dados['tempo_previsto_total_minutos']
                tempo_trab_min = dados['tempo_trabalho_total_minutos']
                
                # Calcular diferença e eficiência
                diferenca_minutos = tempo_trab_min - tempo_prev_min
                eficiencia = (tempo_prev_min / tempo_trab_min * 100) if tempo_trab_min > 0 else 0
                
                resultados.append({
                    'ensaio_id': dados['ensaio_id'],
                    'ensaio_descricao': dados['ensaio_descricao'],
                    'tempo_previsto_total': minutos_para_horas_str(tempo_prev_min),
                    'tempo_previsto_minutos': round(tempo_prev_min, 2),
                    'tempo_trabalho_total': minutos_para_horas_str(tempo_trab_min),
                    'tempo_trabalho_minutos': round(tempo_trab_min, 2),
                    'diferenca': minutos_para_horas_str(abs(diferenca_minutos)),
                    'diferenca_minutos': round(diferenca_minutos, 2),
                    'status': 'No prazo' if diferenca_minutos <= 0 else 'Atrasado',
                    'eficiencia_percentual': round(eficiencia, 2),
                    'quantidade_execucoes': dados['quantidade_execucoes']
                })
            
            # Ordenar por descrição
            resultados.sort(key=lambda x: x['ensaio_descricao'])
            
            return Response({
                'tipo_agrupamento': 'por_ensaio',
                'total_ensaios': len(resultados),
                'periodo': {
                    'data_inicial': data_inicial,
                    'data_final': data_final
                },
                'resultados': resultados
            })
        
        else:
            # Totais gerais (sem agrupar por ensaio)
            tempo_previsto_total_min = 0
            tempo_trabalho_total_min = 0
            total_ensaios_executados = 0
            analises_processadas = set()
            
            # Criar cache de ensaios do modelo
            from controleQualidade.ensaio.models import Ensaio
            ensaios_cache = {}
            
            for analise_ensaio in queryset:
                analises_processadas.add(analise_ensaio.analise_id)
                
                try:
                    # Parsear JSON dos ensaios
                    if isinstance(analise_ensaio.ensaios_utilizados, list):
                        ensaios_json = analise_ensaio.ensaios_utilizados
                    elif isinstance(analise_ensaio.ensaios_utilizados, str):
                        ensaios_json = json.loads(analise_ensaio.ensaios_utilizados)
                    else:
                        continue
                    
                    # Processar cada ensaio
                    for ensaio in ensaios_json:
                        ensaio_id = ensaio.get('id')
                        ensaio_desc = ensaio.get('descricao', 'Sem descrição')
                        tempo_previsto = ensaio.get('tempo_previsto')
                        tempo_trabalho = ensaio.get('tempo_trabalho')
                        
                        # Filtrar por descrição se fornecida
                        if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                            continue
                        
                        # Se tempo_trabalho não está no JSON, buscar do modelo Ensaio
                        if ensaio_id and not tempo_trabalho:
                            if ensaio_id not in ensaios_cache:
                                try:
                                    ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                    ensaios_cache[ensaio_id] = {
                                        'tempo_previsto': ensaio_modelo.tempo_previsto,
                                        'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                    }
                                except Ensaio.DoesNotExist:
                                    ensaios_cache[ensaio_id] = {
                                        'tempo_previsto': None,
                                        'tempo_trabalho': None
                                    }
                            
                            tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                            # Se tempo_previsto também não está no JSON, usar do modelo
                            if not tempo_previsto:
                                tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                        
                        tempo_previsto_total_min += tempo_para_minutos(tempo_previsto)
                        tempo_trabalho_total_min += tempo_para_minutos(tempo_trabalho)
                        total_ensaios_executados += 1
                
                except (json.JSONDecodeError, TypeError):
                    continue
            
            # Processar campos JSON do modelo Analise que contêm ensaios
            campos_json_analise = [
                'substrato', 'superficial', 'retracao', 'elasticidade', 
                'flexao', 'compressao', 'peneiras', 'peneiras_umidas',
                'variacao_dimensional', 'variacao_massa', 'tracao_normal',
                'tracao_submersa', 'tracao_estufa', 'tracao_tempo_aberto',
                'modulo_elasticidade', 'deslizamento'
            ]
            
            # Buscar análises do período para processar campos JSON
            analises_periodo = Analise.objects.filter(
                data__gte=data_inicial,
                data__lte=data_final
            )
            
            if apenas_finalizadas:
                analises_periodo = analises_periodo.filter(finalizada=True)
            
            if analise_id:
                analises_periodo = analises_periodo.filter(id=analise_id)
            
            if local_coleta:
                analises_periodo = analises_periodo.filter(amostra__local_coleta__icontains=local_coleta)
            
            for analise in analises_periodo:
                analises_processadas.add(analise.id)
                
                for campo_nome in campos_json_analise:
                    campo_valor = getattr(analise, campo_nome, None)
                    
                    if not campo_valor:
                        continue
                    
                    try:
                        # Se for string, parsear JSON
                        if isinstance(campo_valor, str):
                            campo_json = json.loads(campo_valor)
                        else:
                            campo_json = campo_valor
                        
                        # Verificar se é uma lista de ensaios
                        if isinstance(campo_json, list):
                            for item in campo_json:
                                if isinstance(item, dict):
                                    ensaio_id = item.get('id')
                                    ensaio_desc = item.get('descricao', campo_nome.replace('_', ' ').title())
                                    tempo_previsto = item.get('tempo_previsto')
                                    tempo_trabalho = item.get('tempo_trabalho')
                                    
                                    # Filtrar por descrição se fornecida
                                    if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                                        continue
                                    
                                    # Buscar do modelo Ensaio se necessário
                                    if ensaio_id and not tempo_trabalho:
                                        if ensaio_id not in ensaios_cache:
                                            try:
                                                ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                                ensaios_cache[ensaio_id] = {
                                                    'tempo_previsto': ensaio_modelo.tempo_previsto,
                                                    'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                                }
                                            except Ensaio.DoesNotExist:
                                                ensaios_cache[ensaio_id] = {
                                                    'tempo_previsto': None,
                                                    'tempo_trabalho': None
                                                }
                                        
                                        tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                                        if not tempo_previsto:
                                            tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                                    
                                    tempo_previsto_total_min += tempo_para_minutos(tempo_previsto)
                                    tempo_trabalho_total_min += tempo_para_minutos(tempo_trabalho)
                                    total_ensaios_executados += 1
                        
                        # Verificar se é um dicionário com campos tempo diretos
                        elif isinstance(campo_json, dict):
                            ensaio_id = campo_json.get('id')
                            ensaio_desc = campo_json.get('descricao', campo_nome.replace('_', ' ').title())
                            tempo_previsto = campo_json.get('tempo_previsto')
                            tempo_trabalho = campo_json.get('tempo_trabalho')
                            
                            # Filtrar por descrição se fornecida
                            if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                                continue
                            
                            if tempo_previsto or tempo_trabalho:
                                # Buscar do modelo Ensaio se necessário
                                if ensaio_id and not tempo_trabalho:
                                    if ensaio_id not in ensaios_cache:
                                        try:
                                            ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                            ensaios_cache[ensaio_id] = {
                                                'tempo_previsto': ensaio_modelo.tempo_previsto,
                                                'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                            }
                                        except Ensaio.DoesNotExist:
                                            ensaios_cache[ensaio_id] = {
                                                'tempo_previsto': None,
                                                'tempo_trabalho': None
                                            }
                                    
                                    tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                                    if not tempo_previsto:
                                        tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                                
                                tempo_previsto_total_min += tempo_para_minutos(tempo_previsto)
                                tempo_trabalho_total_min += tempo_para_minutos(tempo_trabalho)
                                total_ensaios_executados += 1
                    
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        continue
            
            # Calcular diferença e eficiência
            diferenca_minutos = tempo_trabalho_total_min - tempo_previsto_total_min
            eficiencia = (tempo_previsto_total_min / tempo_trabalho_total_min * 100) if tempo_trabalho_total_min > 0 else 0
            
            return Response({
                'tipo_agrupamento': 'geral',
                'periodo': {
                    'data_inicial': data_inicial,
                    'data_final': data_final
                },
                'totais': {
                    'tempo_previsto_total': minutos_para_horas_str(tempo_previsto_total_min),
                    'tempo_previsto_minutos': round(tempo_previsto_total_min, 2),
                    'tempo_trabalho_total': minutos_para_horas_str(tempo_trabalho_total_min),
                    'tempo_trabalho_minutos': round(tempo_trabalho_total_min, 2),
                    'diferenca': minutos_para_horas_str(abs(diferenca_minutos)),
                    'diferenca_minutos': round(diferenca_minutos, 2),
                    'status': 'No prazo' if diferenca_minutos <= 0 else 'Atrasado',
                    'eficiencia_percentual': round(eficiencia, 2),
                    'total_ensaios_executados': total_ensaios_executados,
                    'total_analises': len(analises_processadas)
                }
            })
    
    @action(detail=False, methods=['post'], url_path='tempo-por-analise')
    def tempo_por_analise(self, request):
        """
        Retorna o tempo total de cada análise (previsto e trabalhado) no período.
        
        Parâmetros esperados (POST):
        - data_inicial: data inicial no formato YYYY-MM-DD (obrigatório)
        - data_final: data final no formato YYYY-MM-DD (obrigatório)
        - analise_ids: lista de IDs de análises específicas (opcional)
        - ensaio_descricao: descrição do ensaio para filtrar (opcional)
        - local_coleta: filtrar por local de coleta da amostra (opcional)
        - laboratorio: filtrar por laboratório da amostra (opcional)
        - apenas_finalizadas: boolean - se True, filtra apenas finalizadas (default: False)
        - agrupar_por: 'analise' (padrão), 'local_coleta' ou 'laboratorio' (opcional)
        - formato_saida: 'json' (padrão) ou 'dataframe' - se dataframe, retorna estrutura para pd.DataFrame
        """
        from django.db.models import Q
        from datetime import datetime
        import json
        
        data = request.data
        data_inicial = data.get('data_inicial')
        data_final = data.get('data_final')
        analise_ids = data.get('analise_ids', [])
        ensaio_descricao = data.get('ensaio_descricao')
        local_coleta = data.get('local_coleta')
        laboratorio = data.get('laboratorio', [])
        apenas_finalizadas = data.get('apenas_finalizadas', False)
        agrupar_por = data.get('agrupar_por', 'analise')  # 'analise', 'local_coleta' ou 'laboratorio'
        formato_saida = data.get('formato_saida', 'json')  # 'json' ou 'dataframe'
        
        # Validações
        if not data_inicial or not data_final:
            return Response({
                "error": "Parâmetros 'data_inicial' e 'data_final' são obrigatórios (formato: YYYY-MM-DD)"
            }, status=400)
        
        try:
            # Validar formato de data sem criar objeto datetime
            datetime.strptime(data_inicial, '%Y-%m-%d')
            datetime.strptime(data_final, '%Y-%m-%d')
            
            # Comparar strings de data diretamente
            if data_inicial > data_final:
                return Response({
                    "error": "A data_inicial deve ser anterior à data_final"
                }, status=400)
        except ValueError:
            return Response({
                "error": "Formato de data inválido. Use YYYY-MM-DD"
            }, status=400)
        
        # Filtrar análises no período
        if apenas_finalizadas:
            queryset = AnaliseEnsaio.objects.filter(
                analise__finalizada_at__gte=data_inicial,
                analise__finalizada_at__lte=data_final,
                analise__finalizada=True
            ).select_related('analise', 'analise__amostra')
        else:
            queryset = AnaliseEnsaio.objects.filter(
                analise__data__gte=data_inicial,
                analise__data__lte=data_final
            ).select_related('analise', 'analise__amostra')
        
        # Filtrar por análises específicas se fornecido
        if analise_ids:
            analise_ids = [int(id) for id in analise_ids]
            queryset = queryset.filter(analise_id__in=analise_ids)
        
        # Filtrar por local de coleta da amostra se fornecido
        if local_coleta:
            if isinstance(local_coleta, list):
                from django.db.models import Q
                filtros_local = Q()
                for local in local_coleta:
                    filtros_local |= Q(analise__amostra__local_coleta__icontains=local)
                queryset = queryset.filter(filtros_local)
            else:
                queryset = queryset.filter(analise__amostra__local_coleta__icontains=local_coleta)
        
        # Filtrar por laboratório da amostra se fornecido
        if laboratorio:
            if isinstance(laboratorio, list):
                from django.db.models import Q
                filtros_lab = Q()
                for lab in laboratorio:
                    filtros_lab |= Q(analise__amostra__laboratorio__icontains=lab)
                queryset = queryset.filter(filtros_lab)
            else:
                queryset = queryset.filter(analise__amostra__laboratorio__icontains=laboratorio)
        
        # Função auxiliar para converter tempo em minutos (reutilizando a mesma do método anterior)
        def tempo_para_minutos(tempo_str):
            if not tempo_str:
                return 0
            
            tempo_str = str(tempo_str).lower().strip()
            total_minutos = 0
            
            try:
                tempo_str = tempo_str.replace('ç', 'c').replace('õ', 'o').replace('ã', 'a')
                
                if 'turno' in tempo_str:
                    numero = ''.join(filter(str.isdigit, tempo_str.split('turno')[0]))
                    if numero:
                        return float(numero) * 8 * 60
                    return 0
                
                if 'hora' in tempo_str or 'h' in tempo_str:
                    if 'hora' in tempo_str:
                        partes = tempo_str.split('hora')
                    else:
                        partes = tempo_str.split('h')
                    
                    numero_str = partes[0].strip()
                    numero = ''.join(filter(lambda x: x.isdigit() or x == '.', numero_str))
                    if numero:
                        horas = float(numero)
                        total_minutos += horas * 60
                    
                    if len(partes) > 1:
                        resto = partes[1]
                        if 'min' in resto:
                            numero_min = ''.join(filter(lambda x: x.isdigit() or x == '.', resto.split('min')[0]))
                            if numero_min:
                                total_minutos += float(numero_min)
                
                elif 'min' in tempo_str:
                    numero = ''.join(filter(lambda x: x.isdigit() or x == '.', tempo_str.split('min')[0]))
                    if numero:
                        total_minutos += float(numero)
                
                elif tempo_str.replace('.', '').replace(',', '').isdigit():
                    total_minutos = float(tempo_str.replace(',', '.'))
                
            except:
                return 0
            
            return total_minutos
        
        def minutos_para_horas_str(minutos):
            if minutos == 0:
                return '0min'
            
            horas = int(minutos // 60)
            mins = int(minutos % 60)
            
            if horas > 0 and mins > 0:
                return f'{horas}h {mins}min'
            elif horas > 0:
                return f'{horas}h'
            else:
                return f'{mins}min'
        
        # Agrupar por análise
        analises_agrupadas = {}
        
        # Criar cache de ensaios do modelo
        from controleQualidade.ensaio.models import Ensaio
        ensaios_cache = {}
        
        for analise_ensaio in queryset:
            analise = analise_ensaio.analise
            analise_id = analise.id
            
            if analise_id not in analises_agrupadas:
                analises_agrupadas[analise_id] = {
                    'analise_id': analise_id,
                    'amostra_numero': analise.amostra.numero if analise.amostra else None,
                    'laboratorio': analise.amostra.laboratorio if (analise.amostra and analise.amostra.laboratorio) else None,
                    'data_finalizacao': str(analise.finalizada_at) if analise.finalizada_at else None,
                    'tempo_previsto_total_minutos': 0,
                    'tempo_trabalho_total_minutos': 0,
                    'quantidade_ensaios': 0,
                    'quantidade_ensaios_diretos': 0,
                    'quantidade_ensaios_calculos': 0,
                    'quantidade_ensaios_campos_json': 0,
                    'ensaios_detalhes': [],
                    'ensaios_por_id': {}  # Rastreia o último ensaio de cada ID
                }
            
            try:
                # Parsear JSON dos ensaios
                if isinstance(analise_ensaio.ensaios_utilizados, list):
                    ensaios_json = analise_ensaio.ensaios_utilizados
                elif isinstance(analise_ensaio.ensaios_utilizados, str):
                    ensaios_json = json.loads(analise_ensaio.ensaios_utilizados)
                else:
                    continue
                
                # Processar cada ensaio (o último sobrescreve os anteriores do mesmo ID)
                for ensaio in ensaios_json:
                    ensaio_id = ensaio.get('id')
                    ensaio_desc = ensaio.get('descricao', 'Sem descrição')
                    tempo_previsto = ensaio.get('tempo_previsto')
                    tempo_trabalho = ensaio.get('tempo_trabalho')
                    
                    # Filtrar por descrição se fornecida
                    if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                        continue
                    
                    # Se tempo_trabalho não está no JSON, buscar do modelo Ensaio
                    if ensaio_id and not tempo_trabalho:
                        if ensaio_id not in ensaios_cache:
                            try:
                                ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                ensaios_cache[ensaio_id] = {
                                    'tempo_previsto': ensaio_modelo.tempo_previsto,
                                    'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                }
                            except Ensaio.DoesNotExist:
                                ensaios_cache[ensaio_id] = {
                                    'tempo_previsto': None,
                                    'tempo_trabalho': None
                                }
                        
                        tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                        if not tempo_previsto:
                            tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                    
                    tempo_prev_min = tempo_para_minutos(tempo_previsto)
                    tempo_trab_min = tempo_para_minutos(tempo_trabalho)
                    
                    # Criar chave única para este ensaio (id + origem)
                    ensaio_key = f"ensaio_{ensaio_id}"
                    
                    # Armazenar/substituir com o ensaio mais recente
                    analises_agrupadas[analise_id]['ensaios_por_id'][ensaio_key] = {
                        'ensaio_id': ensaio_id,
                        'ensaio_descricao': ensaio_desc,
                        'tempo_previsto_min': tempo_prev_min,
                        'tempo_trabalho_min': tempo_trab_min,
                        'origem': 'ensaio',
                        'tipo_contador': 'diretos'
                    }
            
            except (json.JSONDecodeError, TypeError):
                continue
        
        # Processar ensaios dentro dos cálculos
        if apenas_finalizadas:
            calculos_queryset = AnaliseCalculo.objects.filter(
                analise__finalizada_at__gte=data_inicial,
                analise__finalizada_at__lte=data_final,
                analise__finalizada=True
            ).select_related('analise', 'analise__amostra')
        else:
            calculos_queryset = AnaliseCalculo.objects.filter(
                analise__data__gte=data_inicial,
                analise__data__lte=data_final
            ).select_related('analise', 'analise__amostra')
        
        # Filtrar por análises específicas se fornecido
        if analise_ids:
            calculos_queryset = calculos_queryset.filter(analise_id__in=analise_ids)
        
        # Filtrar por local de coleta da amostra se fornecido
        if local_coleta:
            if isinstance(local_coleta, list):
                from django.db.models import Q
                filtros_local = Q()
                for local in local_coleta:
                    filtros_local |= Q(analise__amostra__local_coleta__icontains=local)
                calculos_queryset = calculos_queryset.filter(filtros_local)
            else:
                calculos_queryset = calculos_queryset.filter(analise__amostra__local_coleta__icontains=local_coleta)
        
        # Filtrar por laboratório da amostra se fornecido
        if laboratorio:
            if isinstance(laboratorio, list):
                from django.db.models import Q
                filtros_lab = Q()
                for lab in laboratorio:
                    filtros_lab |= Q(analise__amostra__laboratorio__icontains=lab)
                calculos_queryset = calculos_queryset.filter(filtros_lab)
            else:
                calculos_queryset = calculos_queryset.filter(analise__amostra__laboratorio__icontains=laboratorio)
        
        for analise_calculo in calculos_queryset:
            analise = analise_calculo.analise
            analise_id = analise.id
            
            # Inicializar se ainda não existe
            if analise_id not in analises_agrupadas:
                analises_agrupadas[analise_id] = {
                    'analise_id': analise_id,
                    'amostra_numero': analise.amostra.numero if analise.amostra else None,
                    'laboratorio': analise.amostra.laboratorio if (analise.amostra and analise.amostra.laboratorio) else None,
                    'data_finalizacao': str(analise.finalizada_at) if analise.finalizada_at else None,
                    'tempo_previsto_total_minutos': 0,
                    'tempo_trabalho_total_minutos': 0,
                    'quantidade_ensaios': 0,
                    'quantidade_ensaios_diretos': 0,
                    'quantidade_ensaios_calculos': 0,
                    'ensaios_detalhes': [],
                    'ensaios_por_id': {}  # Rastreia o último ensaio de cada ID
                }
            
            try:
                # Parsear JSON dos ensaios do cálculo
                if isinstance(analise_calculo.ensaios_utilizados, list):
                    ensaios_json = analise_calculo.ensaios_utilizados
                elif isinstance(analise_calculo.ensaios_utilizados, str):
                    ensaios_json = json.loads(analise_calculo.ensaios_utilizados)
                else:
                    continue
                
                # Processar cada ensaio do cálculo
                for ensaio in ensaios_json:
                    ensaio_id = ensaio.get('id')
                    ensaio_desc = ensaio.get('descricao', 'Sem descrição')
                    tempo_previsto = ensaio.get('tempo_previsto')
                    tempo_trabalho = ensaio.get('tempo_trabalho')
                    
                    # Filtrar por descrição se fornecida
                    if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                        continue
                    
                    # Se tempo_trabalho não está no JSON, buscar do modelo Ensaio
                    if ensaio_id and not tempo_trabalho:
                        if ensaio_id not in ensaios_cache:
                            try:
                                ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                ensaios_cache[ensaio_id] = {
                                    'tempo_previsto': ensaio_modelo.tempo_previsto,
                                    'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                }
                            except Ensaio.DoesNotExist:
                                ensaios_cache[ensaio_id] = {
                                    'tempo_previsto': None,
                                    'tempo_trabalho': None
                                }
                        
                        tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                        if not tempo_previsto:
                            tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                    
                    tempo_prev_min = tempo_para_minutos(tempo_previsto)
                    tempo_trab_min = tempo_para_minutos(tempo_trabalho)
                    
                    # Criar chave única para este ensaio (id + origem calculo)
                    ensaio_key = f"calculo_{ensaio_id}_{analise_calculo.calculos}"
                    
                    # Armazenar/substituir com o ensaio mais recente
                    analises_agrupadas[analise_id]['ensaios_por_id'][ensaio_key] = {
                        'ensaio_id': ensaio_id,
                        'ensaio_descricao': f"{ensaio_desc} (via {analise_calculo.calculos})",
                        'tempo_previsto_min': tempo_prev_min,
                        'tempo_trabalho_min': tempo_trab_min,
                        'origem': 'calculo',
                        'calculo': analise_calculo.calculos,
                        'tipo_contador': 'calculos'
                    }
            
            except (json.JSONDecodeError, TypeError):
                continue
        
        # Processar campos JSON do modelo Analise que contêm ensaios
        campos_json_analise = [
            'substrato', 'superficial', 'retracao', 'elasticidade', 
            'flexao', 'compressao', 'peneiras', 'peneiras_umidas',
            'variacao_dimensional', 'variacao_massa', 'tracao_normal',
            'tracao_submersa', 'tracao_estufa', 'tracao_tempo_aberto',
            'modulo_elasticidade', 'deslizamento'
        ]
        
        # Buscar todas as análises do período para processar campos JSON
        if apenas_finalizadas:
            analises_periodo = Analise.objects.filter(
                finalizada_at__gte=data_inicial,
                finalizada_at__lte=data_final,
                finalizada=True
            ).select_related('amostra')
        else:
            analises_periodo = Analise.objects.filter(
                data__gte=data_inicial,
                data__lte=data_final
            ).select_related('amostra')
        
        # Filtrar por análises específicas se fornecido
        if analise_ids:
            analises_periodo = analises_periodo.filter(id__in=analise_ids)
        
        # Filtrar por local de coleta da amostra se fornecido
        if local_coleta:
            if isinstance(local_coleta, list):
                from django.db.models import Q
                filtros_local = Q()
                for local in local_coleta:
                    filtros_local |= Q(amostra__local_coleta__icontains=local)
                analises_periodo = analises_periodo.filter(filtros_local)
            else:
                analises_periodo = analises_periodo.filter(amostra__local_coleta__icontains=local_coleta)
        
        # Filtrar por laboratório da amostra se fornecido
        if laboratorio:
            if isinstance(laboratorio, list):
                from django.db.models import Q
                filtros_lab = Q()
                for lab in laboratorio:
                    filtros_lab |= Q(amostra__laboratorio__icontains=lab)
                analises_periodo = analises_periodo.filter(filtros_lab)
            else:
                analises_periodo = analises_periodo.filter(amostra__laboratorio__icontains=laboratorio)
        
        for analise in analises_periodo:
            analise_id = analise.id
            
            # Inicializar se ainda não existe
            if analise_id not in analises_agrupadas:
                analises_agrupadas[analise_id] = {
                    'analise_id': analise_id,
                    'amostra_numero': analise.amostra.numero if analise.amostra else None,
                    'laboratorio': analise.amostra.laboratorio if (analise.amostra and analise.amostra.laboratorio) else None,
                    'data_finalizacao': str(analise.finalizada_at) if analise.finalizada_at else None,
                    'tempo_previsto_total_minutos': 0,
                    'tempo_trabalho_total_minutos': 0,
                    'quantidade_ensaios': 0,
                    'quantidade_ensaios_diretos': 0,
                    'quantidade_ensaios_calculos': 0,
                    'quantidade_ensaios_campos_json': 0,
                    'ensaios_detalhes': [],
                    'ensaios_por_id': {}  # Rastreia o último ensaio de cada ID
                }
            
            # Processar cada campo JSON
            for campo_nome in campos_json_analise:
                campo_valor = getattr(analise, campo_nome, None)
                
                if not campo_valor:
                    continue
                
                try:
                    # Se for string, parsear JSON
                    if isinstance(campo_valor, str):
                        campo_json = json.loads(campo_valor)
                    else:
                        campo_json = campo_valor
                    
                    # Verificar se é uma lista de ensaios
                    if isinstance(campo_json, list):
                        for item in campo_json:
                            if isinstance(item, dict):
                                ensaio_id = item.get('id')
                                ensaio_desc = item.get('descricao', campo_nome.replace('_', ' ').title())
                                tempo_previsto = item.get('tempo_previsto')
                                tempo_trabalho = item.get('tempo_trabalho')
                                
                                # Filtrar por descrição se fornecida
                                if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                                    continue
                                
                                # Buscar do modelo Ensaio se necessário
                                if ensaio_id and not tempo_trabalho:
                                    if ensaio_id not in ensaios_cache:
                                        try:
                                            ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                            ensaios_cache[ensaio_id] = {
                                                'tempo_previsto': ensaio_modelo.tempo_previsto,
                                                'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                            }
                                        except Ensaio.DoesNotExist:
                                            ensaios_cache[ensaio_id] = {
                                                'tempo_previsto': None,
                                                'tempo_trabalho': None
                                            }
                                    
                                    tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                                    if not tempo_previsto:
                                        tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                                
                                tempo_prev_min = tempo_para_minutos(tempo_previsto)
                                tempo_trab_min = tempo_para_minutos(tempo_trabalho)
                                
                                # Criar chave única para este ensaio
                                ensaio_key = f"json_{campo_nome}_{ensaio_id}"
                                
                                # Armazenar/substituir com o ensaio mais recente
                                analises_agrupadas[analise_id]['ensaios_por_id'][ensaio_key] = {
                                    'ensaio_id': ensaio_id,
                                    'ensaio_descricao': f"{ensaio_desc} ({campo_nome})",
                                    'tempo_previsto_min': tempo_prev_min,
                                    'tempo_trabalho_min': tempo_trab_min,
                                    'origem': 'campo_json',
                                    'campo': campo_nome,
                                    'tipo_contador': 'campos_json'
                                }
                    
                    # Verificar se é um dicionário com campos tempo_previsto/tempo_trabalho diretos
                    elif isinstance(campo_json, dict):
                        ensaio_desc = campo_json.get('descricao', campo_nome.replace('_', ' ').title())
                        tempo_previsto = campo_json.get('tempo_previsto')
                        tempo_trabalho = campo_json.get('tempo_trabalho')
                        
                        # Filtrar por descrição se fornecida
                        if ensaio_descricao and ensaio_descricao.lower() not in ensaio_desc.lower():
                            continue
                        
                        if tempo_previsto or tempo_trabalho:
                            tempo_prev_min = tempo_para_minutos(tempo_previsto)
                            tempo_trab_min = tempo_para_minutos(tempo_trabalho)
                            
                            # Criar chave única para este campo
                            ensaio_key = f"json_{campo_nome}"
                            
                            # Armazenar/substituir com o ensaio mais recente
                            analises_agrupadas[analise_id]['ensaios_por_id'][ensaio_key] = {
                                'ensaio_id': None,
                                'ensaio_descricao': campo_nome.replace('_', ' ').title(),
                                'tempo_previsto_min': tempo_prev_min,
                                'tempo_trabalho_min': tempo_trab_min,
                                'origem': 'campo_json',
                                'campo': campo_nome,
                                'tipo_contador': 'campos_json'
                            }
                
                except (json.JSONDecodeError, TypeError, AttributeError):
                    continue
        
        # Processar ensaios_por_id para criar listas finais e calcular totais
        for analise_id in analises_agrupadas:
            dados = analises_agrupadas[analise_id]
            
            # Processar cada ensaio único e calcular totais
            for ensaio_data in dados['ensaios_por_id'].values():
                tempo_prev_min = ensaio_data['tempo_previsto_min']
                tempo_trab_min = ensaio_data['tempo_trabalho_min']
                
                # Atualizar totais
                dados['tempo_previsto_total_minutos'] += tempo_prev_min
                dados['tempo_trabalho_total_minutos'] += tempo_trab_min
                dados['quantidade_ensaios'] += 1
                
                # Atualizar contadores específicos
                tipo_contador = ensaio_data['tipo_contador']
                if tipo_contador == 'diretos':
                    dados['quantidade_ensaios_diretos'] += 1
                elif tipo_contador == 'calculos':
                    dados['quantidade_ensaios_calculos'] += 1
                elif tipo_contador == 'campos_json':
                    dados['quantidade_ensaios_campos_json'] += 1
                
                # Adicionar aos detalhes formatados
                detalhes = {
                    'ensaio_id': ensaio_data['ensaio_id'],
                    'ensaio_descricao': ensaio_data['ensaio_descricao'],
                    'tempo_previsto': minutos_para_horas_str(tempo_prev_min),
                    'tempo_trabalho': minutos_para_horas_str(tempo_trab_min),
                    'origem': ensaio_data['origem']
                }
                
                # Adicionar campo se existir
                if 'campo' in ensaio_data:
                    detalhes['campo'] = ensaio_data['campo']
                
                dados['ensaios_detalhes'].append(detalhes)
            
            # Remover dicionário temporário
            del dados['ensaios_por_id']
        
        # Formatar resultados
        if agrupar_por == 'local_coleta':
            # Agrupar por local de coleta
            grupos = {}
            for analise_id, dados in analises_agrupadas.items():
                if ensaio_descricao and dados['quantidade_ensaios'] == 0:
                    continue
                
                # Extrair local_coleta da amostra
                amostra = dados.get('amostra_numero', '')
                if amostra:
                    # Assumindo que o local está no formato do número da amostra
                    # Adaptar conforme necessário baseado no formato real
                    partes = amostra.split()
                    local = partes[0] if partes else 'Não especificado'
                else:
                    local = 'Não especificado'
                
                if local not in grupos:
                    grupos[local] = {
                        'local_coleta': local,
                        'tempo_previsto_minutos': 0,
                        'tempo_trabalho_minutos': 0,
                        'quantidade_analises': 0,
                        'laboratorios': set()
                    }
                
                grupos[local]['tempo_previsto_minutos'] += dados['tempo_previsto_total_minutos']
                grupos[local]['tempo_trabalho_minutos'] += dados['tempo_trabalho_total_minutos']
                grupos[local]['quantidade_analises'] += 1
                if dados.get('laboratorio'):
                    grupos[local]['laboratorios'].add(dados['laboratorio'])
            
            # Calcular totais gerais para percentuais
            tempo_previsto_geral = sum(g['tempo_previsto_minutos'] for g in grupos.values())
            tempo_trabalho_geral = sum(g['tempo_trabalho_minutos'] for g in grupos.values())
            
            resultados = []
            for local, grupo_dados in grupos.items():
                tempo_prev_min = grupo_dados['tempo_previsto_minutos']
                tempo_trab_min = grupo_dados['tempo_trabalho_minutos']
                
                # Calcular percentuais
                percentual_previsto = (tempo_prev_min / tempo_previsto_geral * 100) if tempo_previsto_geral > 0 else 0
                percentual_trabalho = (tempo_trab_min / tempo_trabalho_geral * 100) if tempo_trabalho_geral > 0 else 0
                
                resultados.append({
                    'local_coleta': local,
                    'tempo_previsto': minutos_para_horas_str(tempo_prev_min),
                    'tempo_trabalho': minutos_para_horas_str(tempo_trab_min),
                    'laboratorio': ', '.join(sorted(grupo_dados['laboratorios'])) if grupo_dados['laboratorios'] else 'Não especificado',
                    'percentual_previsto': round(percentual_previsto, 2),
                    'percentual_trabalho': round(percentual_trabalho, 2),
                    'tempo_previsto_minutos': round(tempo_prev_min, 2),
                    'tempo_trabalho_minutos': round(tempo_trab_min, 2),
                    'quantidade_analises': grupo_dados['quantidade_analises']
                })
            
            resultados.sort(key=lambda x: x['local_coleta'])
            
            diferenca_geral = tempo_trabalho_geral - tempo_previsto_geral
            eficiencia_geral = (tempo_previsto_geral / tempo_trabalho_geral * 100) if tempo_trabalho_geral > 0 else 0
            
            if formato_saida == 'dataframe':
                # Criar DataFrame do pandas com ordem específica das colunas
                df = pd.DataFrame(resultados)
                
                # Reordenar colunas para match exato com o formato solicitado
                colunas_ordenadas = [
                    'local_coleta',
                    'tempo_previsto', 
                    'tempo_trabalho',
                    'laboratorio',
                    'percentual_previsto',
                    'percentual_trabalho'
                ]
                
                # Renomear colunas para formato de exibição
                df_display = df[colunas_ordenadas].copy()
                df_display.columns = [
                    'LOCAL COLETA',
                    'TEMPO PREVISTO',
                    'TEMPO TRABALHO',
                    'LABORATORIO',
                    '% do total previsto',
                    '% do total trabalho'
                ]
                
                # Adicionar linha de totais
                total_row = pd.DataFrame([{
                    'LOCAL COLETA': 'TOTAL',
                    'TEMPO PREVISTO': minutos_para_horas_str(tempo_previsto_geral),
                    'TEMPO TRABALHO': minutos_para_horas_str(tempo_trabalho_geral),
                    'LABORATORIO': 'Todos',
                    '% do total previsto': 100.00,
                    '% do total trabalho': 100.00
                }])
                
                df_display = pd.concat([df_display, total_row], ignore_index=True)
                
                return Response({
                    'agrupamento': 'local_coleta',
                    'formato': 'dataframe',
                    'dataframe': df_display.to_dict('records'),
                    'dataframe_html': df_display.to_html(index=False, classes='table table-striped'),
                    'colunas': df_display.columns.tolist(),
                    'periodo': {
                        'data_inicial': data_inicial,
                        'data_final': data_final
                    },
                    'metadados': {
                        'quantidade_analises_total': sum(r['quantidade_analises'] for r in resultados),
                        'total_grupos': len(resultados)
                    }
                })
            
            return Response({
                'agrupamento': 'local_coleta',
                'total_grupos': len(resultados),
                'periodo': {
                    'data_inicial': data_inicial,
                    'data_final': data_final
                },
                'totais_gerais': {
                    'tempo_previsto_total': minutos_para_horas_str(tempo_previsto_geral),
                    'tempo_previsto_minutos': round(tempo_previsto_geral, 2),
                    'tempo_trabalho_total': minutos_para_horas_str(tempo_trabalho_geral),
                    'tempo_trabalho_minutos': round(tempo_trabalho_geral, 2),
                    'diferenca': minutos_para_horas_str(abs(diferenca_geral)),
                    'diferenca_minutos': round(diferenca_geral, 2),
                    'status': 'No prazo' if diferenca_geral <= 0 else 'Atrasado',
                    'eficiencia_percentual': round(eficiencia_geral, 2)
                },
                'resultados': resultados
            })
        
        elif agrupar_por == 'laboratorio':
            # Agrupar por laboratório
            grupos = {}
            for analise_id, dados in analises_agrupadas.items():
                if ensaio_descricao and dados['quantidade_ensaios'] == 0:
                    continue
                
                lab = dados.get('laboratorio', 'Não especificado')
                if not lab:
                    lab = 'Não especificado'
                
                if lab not in grupos:
                    grupos[lab] = {
                        'laboratorio': lab,
                        'tempo_previsto_minutos': 0,
                        'tempo_trabalho_minutos': 0,
                        'quantidade_analises': 0,
                        'locais_coleta': set()
                    }
                
                grupos[lab]['tempo_previsto_minutos'] += dados['tempo_previsto_total_minutos']
                grupos[lab]['tempo_trabalho_minutos'] += dados['tempo_trabalho_total_minutos']
                grupos[lab]['quantidade_analises'] += 1
                
                # Extrair local_coleta
                amostra = dados.get('amostra_numero', '')
                if amostra:
                    partes = amostra.split()
                    local = partes[0] if partes else None
                    if local:
                        grupos[lab]['locais_coleta'].add(local)
            
            # Calcular totais gerais para percentuais
            tempo_previsto_geral = sum(g['tempo_previsto_minutos'] for g in grupos.values())
            tempo_trabalho_geral = sum(g['tempo_trabalho_minutos'] for g in grupos.values())
            
            resultados = []
            for lab, grupo_dados in grupos.items():
                tempo_prev_min = grupo_dados['tempo_previsto_minutos']
                tempo_trab_min = grupo_dados['tempo_trabalho_minutos']
                
                # Calcular percentuais
                percentual_previsto = (tempo_prev_min / tempo_previsto_geral * 100) if tempo_previsto_geral > 0 else 0
                percentual_trabalho = (tempo_trab_min / tempo_trabalho_geral * 100) if tempo_trabalho_geral > 0 else 0
                
                resultados.append({
                    'laboratorio': lab,
                    'tempo_previsto': minutos_para_horas_str(tempo_prev_min),
                    'tempo_trabalho': minutos_para_horas_str(tempo_trab_min),
                    'local_coleta': ', '.join(sorted(grupo_dados['locais_coleta'])) if grupo_dados['locais_coleta'] else 'Não especificado',
                    'percentual_previsto': round(percentual_previsto, 2),
                    'percentual_trabalho': round(percentual_trabalho, 2),
                    'tempo_previsto_minutos': round(tempo_prev_min, 2),
                    'tempo_trabalho_minutos': round(tempo_trab_min, 2),
                    'quantidade_analises': grupo_dados['quantidade_analises']
                })
            
            resultados.sort(key=lambda x: x['laboratorio'])
            
            diferenca_geral = tempo_trabalho_geral - tempo_previsto_geral
            eficiencia_geral = (tempo_previsto_geral / tempo_trabalho_geral * 100) if tempo_trabalho_geral > 0 else 0
            
            if formato_saida == 'dataframe':
                # Criar DataFrame do pandas com ordem específica das colunas
                df = pd.DataFrame(resultados)
                
                # Reordenar colunas para formato de laboratório
                colunas_ordenadas = [
                    'laboratorio',
                    'tempo_previsto', 
                    'tempo_trabalho',
                    'local_coleta',
                    'percentual_previsto',
                    'percentual_trabalho'
                ]
                
                # Renomear colunas para formato de exibição
                df_display = df[colunas_ordenadas].copy()
                df_display.columns = [
                    'LABORATORIO',
                    'TEMPO PREVISTO',
                    'TEMPO TRABALHO',
                    'LOCAL COLETA',
                    '% do total previsto',
                    '% do total trabalho'
                ]
                
                # Adicionar linha de totais
                total_row = pd.DataFrame([{
                    'LABORATORIO': 'TOTAL',
                    'TEMPO PREVISTO': minutos_para_horas_str(tempo_previsto_geral),
                    'TEMPO TRABALHO': minutos_para_horas_str(tempo_trabalho_geral),
                    'LOCAL COLETA': 'Todos',
                    '% do total previsto': 100.00,
                    '% do total trabalho': 100.00
                }])
                
                df_display = pd.concat([df_display, total_row], ignore_index=True)
                
                return Response({
                    'agrupamento': 'laboratorio',
                    'formato': 'dataframe',
                    'dataframe': df_display.to_dict('records'),
                    'dataframe_html': df_display.to_html(index=False, classes='table table-striped'),
                    'colunas': df_display.columns.tolist(),
                    'periodo': {
                        'data_inicial': data_inicial,
                        'data_final': data_final
                    },
                    'metadados': {
                        'quantidade_analises_total': sum(r['quantidade_analises'] for r in resultados),
                        'total_grupos': len(resultados)
                    }
                })
            
            return Response({
                'agrupamento': 'laboratorio',
                'total_grupos': len(resultados),
                'periodo': {
                    'data_inicial': data_inicial,
                    'data_final': data_final
                },
                'totais_gerais': {
                    'tempo_previsto_total': minutos_para_horas_str(tempo_previsto_geral),
                    'tempo_previsto_minutos': round(tempo_previsto_geral, 2),
                    'tempo_trabalho_total': minutos_para_horas_str(tempo_trabalho_geral),
                    'tempo_trabalho_minutos': round(tempo_trabalho_geral, 2),
                    'diferenca': minutos_para_horas_str(abs(diferenca_geral)),
                    'diferenca_minutos': round(diferenca_geral, 2),
                    'status': 'No prazo' if diferenca_geral <= 0 else 'Atrasado',
                    'eficiencia_percentual': round(eficiencia_geral, 2)
                },
                'resultados': resultados
            })
        
        else:
            # Agrupar por análise (comportamento padrão)
            resultados = []
            for analise_id, dados in analises_agrupadas.items():
                # Se ensaio_descricao foi fornecido e a análise não tem nenhum ensaio correspondente, pular
                if ensaio_descricao and dados['quantidade_ensaios'] == 0:
                    continue
                
                tempo_prev_min = dados['tempo_previsto_total_minutos']
                tempo_trab_min = dados['tempo_trabalho_total_minutos']
                
                # Calcular diferença e eficiência
                diferenca_minutos = tempo_trab_min - tempo_prev_min
                eficiencia = (tempo_prev_min / tempo_trab_min * 100) if tempo_trab_min > 0 else 0
                
                resultados.append({
                    'analise_id': dados['analise_id'],
                    'amostra_numero': dados['amostra_numero'],
                    'laboratorio': dados['laboratorio'],
                    'data_finalizacao': dados['data_finalizacao'],
                    'tempo_previsto_total': minutos_para_horas_str(tempo_prev_min),
                    'tempo_previsto_minutos': round(tempo_prev_min, 2),
                    'tempo_trabalho_total': minutos_para_horas_str(tempo_trab_min),
                    'tempo_trabalho_minutos': round(tempo_trab_min, 2),
                    # 'diferenca': minutos_para_horas_str(abs(diferenca_minutos)),
                    # 'diferenca_minutos': round(diferenca_minutos, 2),
                    # 'status': 'No prazo' if diferenca_minutos <= 0 else 'Atrasado',
                    # 'eficiencia_percentual': round(eficiencia, 2),
                    # 'quantidade_ensaios': dados['quantidade_ensaios'],
                    # 'quantidade_ensaios_diretos': dados['quantidade_ensaios_diretos'],
                    # 'quantidade_ensaios_calculos': dados['quantidade_ensaios_calculos'],
                    # 'quantidade_ensaios_campos_json': dados.get('quantidade_ensaios_campos_json', 0),
                    # 'ensaios_detalhes': dados['ensaios_detalhes']
                })
            
            # Ordenar por ID da análise (mais recente primeiro)
            resultados.sort(key=lambda x: x['analise_id'], reverse=True)
            
            # Calcular totais gerais de todas as análises
            tempo_previsto_geral = sum(r['tempo_previsto_minutos'] for r in resultados)
            tempo_trabalho_geral = sum(r['tempo_trabalho_minutos'] for r in resultados)
            diferenca_geral = tempo_trabalho_geral - tempo_previsto_geral
            eficiencia_geral = (tempo_previsto_geral / tempo_trabalho_geral * 100) if tempo_trabalho_geral > 0 else 0
            
            if formato_saida == 'dataframe':
                # Criar DataFrame do pandas
                df = pd.DataFrame(resultados)
                
                return Response({
                    'agrupamento': 'analise',
                    'formato': 'dataframe',
                    'dataframe': df.to_dict('records'),
                    'dataframe_html': df.to_html(index=False, classes='table table-striped'),
                    'colunas': df.columns.tolist(),
                    'total_analises': len(resultados),
                    'periodo': {
                        'data_inicial': data_inicial,
                        'data_final': data_final
                    },
                    'totais_gerais': {
                        'tempo_previsto_total': minutos_para_horas_str(tempo_previsto_geral),
                        'tempo_previsto_minutos': round(tempo_previsto_geral, 2),
                        'tempo_trabalho_total': minutos_para_horas_str(tempo_trabalho_geral),
                        'tempo_trabalho_minutos': round(tempo_trabalho_geral, 2),
                        # 'diferenca': minutos_para_horas_str(abs(diferenca_geral)),
                        # 'diferenca_minutos': round(diferenca_geral, 2),
                        # 'status': 'No prazo' if diferenca_geral <= 0 else 'Atrasado',
                        # 'eficiencia_percentual': round(eficiencia_geral, 2)
                    }
                })
            
            return Response({
                'agrupamento': 'analise',
                'total_analises': len(resultados),
                'periodo': {
                    'data_inicial': data_inicial,
                    'data_final': data_final
                },
                'totais_gerais': {
                    'tempo_previsto_total': minutos_para_horas_str(tempo_previsto_geral),
                    'tempo_previsto_minutos': round(tempo_previsto_geral, 2),
                    'tempo_trabalho_total': minutos_para_horas_str(tempo_trabalho_geral),
                    'tempo_trabalho_minutos': round(tempo_trabalho_geral, 2),
                    # 'diferenca': minutos_para_horas_str(abs(diferenca_geral)),
                    # 'diferenca_minutos': round(diferenca_geral, 2),
                    # 'status': 'No prazo' if diferenca_geral <= 0 else 'Atrasado',
                    # 'eficiencia_percentual': round(eficiencia_geral, 2)
                },
                'resultados': resultados
            })
    
class AnaliseCalculoViewSet(viewsets.ModelViewSet):
    queryset = AnaliseCalculo.objects.all()
    serializer_class = AnaliseCalculoSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='byCalculo')
    def byCalculo(self, request):
        calculos = request.query_params.get('calculo')
        print('Nome',calculos)
        if not calculos:
            return Response({"error": "Calculo parameter is required"}, status=400)
        try:
            resultados = AnaliseCalculo.objects.filter(calculos=calculos)
            serializer = self.get_serializer(resultados, many=True)
            return Response(serializer.data)
        except AnaliseCalculo.DoesNotExist:
            return Response({"error": "Calculo not found"}, status=404)

    @action(detail=False, methods=['post'], url_path='medias-por-periodo')
    def medias_por_periodo(self, request):
        """
        Retorna as médias dos resultados de cálculos agrupados por ensaio/cálculo
        dentro de um período específico.
        
        Parâmetros esperados (POST):
        - calculo: descrição do cálculo (opcional) - agrupa por nome
        - calculos_descricoes: lista de descrições de cálculos (opcional)
        - calculos_ids: lista de IDs de cálculos (opcional) - agrupa por ID
        - produto_ids: lista de IDs de produtos da amostra (opcional)
        - agrupar_por: 'id' ou 'descricao' (padrão: 'id' se calculos_ids fornecido, senão 'descricao')
        - data_inicio: data inicial no formato YYYY-MM-DD
        - data_fim: data final no formato YYYY-MM-DD
        """
        from django.db.models import Avg, Count, Min, Max, Q
        from datetime import datetime
        
        data = request.data
        calculo_descricao = data.get('calculo')
        calculos_descricoes = data.get('calculos_descricoes', [])
        calculos_ids = data.get('calculos_ids', [])
        produto_ids = data.get('produto_ids', [])
        agrupar_por = data.get('agrupar_por', 'id' if calculos_ids else 'descricao')
        data_inicial = data.get('data_inicio')
        data_final = data.get('data_fim')
        
        # Validações
        if not data_inicial or not data_final:
            return Response({
                "error": "Parâmetros 'data_inicial' e 'data_final' são obrigatórios (formato: YYYY-MM-DD)"
            }, status=400)
        
        try:
            # Converter strings de data para objetos datetime
            data_inicial_obj = datetime.strptime(data_inicial, '%Y-%m-%d')
            data_final_obj = datetime.strptime(data_final, '%Y-%m-%d')
            
            # Validar que data inicial é menor que data final
            if data_inicial_obj > data_final_obj:
                return Response({
                    "error": "A data_inicial deve ser anterior à data_final"
                }, status=400)
            
        except ValueError:
            return Response({
                "error": "Formato de data inválido. Use YYYY-MM-DD"
            }, status=400)
        
        # Iniciar queryset base com filtro de período
        queryset = AnaliseCalculo.objects.filter(
            analise__data__gte=data_inicial,
            analise__data__lte=data_final,
            #analise__finalizada=True
        ).select_related('analise', 'analise__amostra')
        
        # Filtrar por cálculo(s) se fornecido
        if calculos_descricoes:
            if isinstance(calculos_descricoes, list) and len(calculos_descricoes) > 0:
                filtros_calc = Q()
                for desc in calculos_descricoes:
                    filtros_calc |= Q(calculos__icontains=desc)
                queryset = queryset.filter(filtros_calc)
            else:
                queryset = queryset.filter(calculos__icontains=calculos_descricoes)
        elif calculo_descricao:
            queryset = queryset.filter(calculos__icontains=calculo_descricao)
        
        # Filtrar por cálculos se fornecidos
        if calculos_ids:
            calculos_ids = [int(id) for id in calculos_ids]
            filtros_calculos = Q()
            for calculo_id in calculos_ids:
                filtros_calculos |= Q(ensaios_utilizados__icontains=f'"id": {calculo_id}')
            queryset = queryset.filter(filtros_calculos)
        
        # Filtrar por produto da amostra se fornecido
        if produto_ids:
            if isinstance(produto_ids, list):
                queryset = queryset.filter(analise__amostra__produto_amostra_id__in=produto_ids)
            else:
                queryset = queryset.filter(analise__amostra__produto_amostra_id=produto_ids)
        
        # Processar resultados manualmente
        resultados_por_calculo = {}
        
        for analise_calculo in queryset:
            calculo_nome = analise_calculo.calculos
            ensaios_utilizados = analise_calculo.ensaios_utilizados
            analise_id = analise_calculo.analise_id
            amostra_numero = analise_calculo.analise.amostra.numero if analise_calculo.analise.amostra else None
            
            if agrupar_por == 'descricao':
                # Agrupar apenas por descrição do cálculo
                chave = calculo_nome
                
                if chave not in resultados_por_calculo:
                    resultados_por_calculo[chave] = {
                        'nome': calculo_nome,
                        'valores_por_analise': {},  # Rastrear por análise
                        'quantidade': 0
                    }
                
                # Armazenar apenas o último resultado desta análise para este cálculo
                if analise_calculo.resultados is not None:
                    resultados_por_calculo[chave]['valores_por_analise'][analise_id] = {
                        'valor': analise_calculo.resultados,
                        'amostra_numero': amostra_numero
                    }
            else:
                # Agrupar por ID de cálculo
                if not ensaios_utilizados:
                    continue
                
                # Dicionário para rastrear o último resultado de cada cálculo nesta análise
                calculos_nesta_analise = {}
                
                # Encontrar os IDs dos cálculos neste registro (o último sobrescreve)
                for ensaio in ensaios_utilizados:
                    if isinstance(ensaio, dict):
                        ensaio_id = ensaio.get('id')
                        if ensaio_id:
                            # Se calculos_ids foi fornecido, verificar se este ID está na lista
                            if not calculos_ids or ensaio_id in calculos_ids:
                                calculos_nesta_analise[ensaio_id] = True
                
                # Se não encontrou nenhum ID relevante, pular este registro
                if not calculos_nesta_analise:
                    continue
                
                # Agrupar por cada ID de cálculo encontrado
                for calculo_id in calculos_nesta_analise.keys():
                    # Criar chave única combinando ID e nome
                    chave = f"{calculo_id}|{calculo_nome}"
                    
                    if chave not in resultados_por_calculo:
                        resultados_por_calculo[chave] = {
                            'id': calculo_id,
                            'nome': calculo_nome,
                            'valores_por_analise': {},  # Rastrear por análise
                            'quantidade': 0
                        }
                    
                    # Armazenar apenas o último resultado desta análise para este cálculo
                    if analise_calculo.resultados is not None:
                        resultados_por_calculo[chave]['valores_por_analise'][analise_id] = {
                            'valor': analise_calculo.resultados,
                            'amostra_numero': amostra_numero
                        }
        
        # Calcular médias usando apenas um valor por análise
        resultados = []
        for chave, dados in resultados_por_calculo.items():
            # Extrair valores únicos por análise
            valores = []
            detalhes = []
            for analise_id, info in dados['valores_por_analise'].items():
                valores.append(info['valor'])
                detalhes.append({
                    'analise_id': analise_id,
                    'amostra_numero': info['amostra_numero'],
                    'valor': info['valor']
                })
            
            if valores:
                resultado = {
                    'calculo': dados['nome'],
                    'media': round(sum(valores) / len(valores), 4),
                    'quantidade_analises': len(valores),
                    'valor_minimo': min(valores),
                    'valor_maximo': max(valores),
                    'detalhes': detalhes,
                    'periodo': {
                        'data_inicial': data_inicial,
                        'data_final': data_final
                    }
                }
                # Adicionar ID apenas se agrupando por ID
                if agrupar_por == 'id':
                    resultado['calculo_id'] = dados['id']
                
                resultados.append(resultado)
        
        return Response({
            'total_calculos': len(resultados),
            'resultados': resultados
        })
    
    @action(detail=False, methods=['post'], url_path='totais-tempo-por-periodo')
    def totais_tempo_por_periodo(self, request):
        """
        Retorna os totais de tempo previsto e tempo trabalhado dos ensaios
        contidos nos cálculos, agrupados por período e cálculo.
        
        Parâmetros esperados (POST):
        - data_inicial: data inicial no formato YYYY-MM-DD (obrigatório)
        - data_final: data final no formato YYYY-MM-DD (obrigatório)
        - calculo_descricao: descrição do cálculo para filtrar (opcional)
        - calculos_ids: lista de IDs de cálculos (opcional)
        - agrupar_por_calculo: boolean - se True, agrupa por cálculo (default: False)
        """
        from django.db.models import Q
        from datetime import datetime
        import json
        
        data = request.data
        data_inicial = data.get('data_inicial')
        data_final = data.get('data_final')
        calculo_descricao = data.get('calculo_descricao')
        calculos_ids = data.get('calculos_ids', [])
        agrupar_por_calculo = data.get('agrupar_por_calculo', False)
        
        # Validações
        if not data_inicial or not data_final:
            return Response({
                "error": "Parâmetros 'data_inicial' e 'data_final' são obrigatórios (formato: YYYY-MM-DD)"
            }, status=400)
        
        try:
            data_inicial_obj = datetime.strptime(data_inicial, '%Y-%m-%d')
            data_final_obj = datetime.strptime(data_final, '%Y-%m-%d')
            
            if data_inicial_obj > data_final_obj:
                return Response({
                    "error": "A data_inicial deve ser anterior à data_final"
                }, status=400)
        except ValueError:
            return Response({
                "error": "Formato de data inválido. Use YYYY-MM-DD"
            }, status=400)
        
        # Filtrar análises finalizadas no período
        queryset = AnaliseCalculo.objects.filter(
            analise__finalizada_at__gte=data_inicial,
            analise__finalizada_at__lte=data_final,
            analise__finalizada=True
        )
        
        # Filtrar por descrição do cálculo se fornecido
        if calculo_descricao:
            queryset = queryset.filter(calculos__icontains=calculo_descricao)
        
        # Filtrar por IDs de cálculos se fornecidos
        if calculos_ids:
            calculos_ids = [int(id) for id in calculos_ids]
            filtros_calculos = Q()
            for calculo_id in calculos_ids:
                filtros_calculos |= Q(ensaios_utilizados__icontains=f'"id": {calculo_id}')
            queryset = queryset.filter(filtros_calculos)
        
        # Função auxiliar para converter tempo em minutos
        def tempo_para_minutos(tempo_str):
            """
            Converte string de tempo para minutos.
            Formatos suportados: 
            - '2h', '30min', '1h30min'
            - '2 Horas', '540 Minutos', '90 minutos'
            - '2 Turnos' (considerando 8h por turno)
            - Números: '120' (assume minutos)
            """
            if not tempo_str:
                return 0
            
            tempo_str = str(tempo_str).lower().strip()
            total_minutos = 0
            
            try:
                # Remover acentos e normalizar
                tempo_str = tempo_str.replace('ç', 'c').replace('õ', 'o').replace('ã', 'a')
                
                # Turnos (8 horas cada)
                if 'turno' in tempo_str:
                    numero = ''.join(filter(str.isdigit, tempo_str.split('turno')[0]))
                    if numero:
                        return float(numero) * 8 * 60
                    return 0
                
                # Horas
                if 'hora' in tempo_str or 'h' in tempo_str:
                    # Separar por 'hora' ou 'h'
                    if 'hora' in tempo_str:
                        partes = tempo_str.split('hora')
                    else:
                        partes = tempo_str.split('h')
                    
                    # Extrair número antes de 'hora' ou 'h'
                    numero_str = partes[0].strip()
                    numero = ''.join(filter(lambda x: x.isdigit() or x == '.', numero_str))
                    if numero:
                        horas = float(numero)
                        total_minutos += horas * 60
                    
                    # Verificar se há minutos depois
                    if len(partes) > 1:
                        resto = partes[1]
                        if 'min' in resto:
                            numero_min = ''.join(filter(lambda x: x.isdigit() or x == '.', resto.split('min')[0]))
                            if numero_min:
                                total_minutos += float(numero_min)
                
                # Minutos
                elif 'min' in tempo_str:
                    numero = ''.join(filter(lambda x: x.isdigit() or x == '.', tempo_str.split('min')[0]))
                    if numero:
                        total_minutos += float(numero)
                
                # Apenas número (assume minutos)
                elif tempo_str.replace('.', '').replace(',', '').isdigit():
                    total_minutos = float(tempo_str.replace(',', '.'))
                
            except Exception as e:
                print(f"Erro ao converter tempo '{tempo_str}': {e}")
                return 0
            
            return total_minutos
        
        def minutos_para_horas_str(minutos):
            """Converte minutos para formato legível (ex: '2h 30min')"""
            if minutos == 0:
                return '0min'
            
            horas = int(minutos // 60)
            mins = int(minutos % 60)
            
            if horas > 0 and mins > 0:
                return f'{horas}h {mins}min'
            elif horas > 0:
                return f'{horas}h'
            else:
                return f'{mins}min'
        
        # Criar cache de ensaios do modelo
        from controleQualidade.ensaio.models import Ensaio
        ensaios_cache = {}
        
        # Processar resultados
        if agrupar_por_calculo:
            # Agrupar por cálculo
            calculos_agrupados = {}
            
            for analise_calculo in queryset:
                calculo_nome = analise_calculo.calculos
                
                if calculo_nome not in calculos_agrupados:
                    calculos_agrupados[calculo_nome] = {
                        'calculo_descricao': calculo_nome,
                        'tempo_previsto_total_minutos': 0,
                        'tempo_trabalho_total_minutos': 0,
                        'quantidade_execucoes': 0,
                        'ensaios_unicos': set()
                    }
                
                try:
                    # Parsear JSON dos ensaios
                    if isinstance(analise_calculo.ensaios_utilizados, list):
                        ensaios_json = analise_calculo.ensaios_utilizados
                    elif isinstance(analise_calculo.ensaios_utilizados, str):
                        ensaios_json = json.loads(analise_calculo.ensaios_utilizados)
                    else:
                        continue
                    
                    # Processar cada ensaio
                    for ensaio in ensaios_json:
                        ensaio_id = ensaio.get('id')
                        tempo_previsto = ensaio.get('tempo_previsto')
                        tempo_trabalho = ensaio.get('tempo_trabalho')
                        
                        if ensaio_id is None:
                            continue
                        
                        # Se tempo_trabalho não está no JSON, buscar do modelo Ensaio
                        if not tempo_trabalho:
                            if ensaio_id not in ensaios_cache:
                                try:
                                    ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                    ensaios_cache[ensaio_id] = {
                                        'tempo_previsto': ensaio_modelo.tempo_previsto,
                                        'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                    }
                                except Ensaio.DoesNotExist:
                                    ensaios_cache[ensaio_id] = {
                                        'tempo_previsto': None,
                                        'tempo_trabalho': None
                                    }
                            
                            tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                            # Se tempo_previsto também não está no JSON, usar do modelo
                            if not tempo_previsto:
                                tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                        
                        calculos_agrupados[calculo_nome]['tempo_previsto_total_minutos'] += tempo_para_minutos(tempo_previsto)
                        calculos_agrupados[calculo_nome]['tempo_trabalho_total_minutos'] += tempo_para_minutos(tempo_trabalho)
                        calculos_agrupados[calculo_nome]['quantidade_execucoes'] += 1
                        calculos_agrupados[calculo_nome]['ensaios_unicos'].add(ensaio_id)
                
                except (json.JSONDecodeError, TypeError):
                    continue
            
            # Formatar resultados
            resultados = []
            for calculo_nome, dados in calculos_agrupados.items():
                tempo_prev_min = dados['tempo_previsto_total_minutos']
                tempo_trab_min = dados['tempo_trabalho_total_minutos']
                
                # Calcular diferença e eficiência
                diferenca_minutos = tempo_trab_min - tempo_prev_min
                eficiencia = (tempo_prev_min / tempo_trab_min * 100) if tempo_trab_min > 0 else 0
                
                resultados.append({
                    'calculo_descricao': dados['calculo_descricao'],
                    'tempo_previsto_total': minutos_para_horas_str(tempo_prev_min),
                    'tempo_previsto_minutos': round(tempo_prev_min, 2),
                    'tempo_trabalho_total': minutos_para_horas_str(tempo_trab_min),
                    'tempo_trabalho_minutos': round(tempo_trab_min, 2),
                    'diferenca': minutos_para_horas_str(abs(diferenca_minutos)),
                    'diferenca_minutos': round(diferenca_minutos, 2),
                    'status': 'No prazo' if diferenca_minutos <= 0 else 'Atrasado',
                    'eficiencia_percentual': round(eficiencia, 2),
                    'quantidade_execucoes': dados['quantidade_execucoes'],
                    'ensaios_diferentes': len(dados['ensaios_unicos'])
                })
            
            # Ordenar por descrição
            resultados.sort(key=lambda x: x['calculo_descricao'])
            
            return Response({
                'tipo_agrupamento': 'por_calculo',
                'total_calculos': len(resultados),
                'periodo': {
                    'data_inicial': data_inicial,
                    'data_final': data_final
                },
                'resultados': resultados
            })
        
        else:
            # Totais gerais (sem agrupar por cálculo)
            tempo_previsto_total_min = 0
            tempo_trabalho_total_min = 0
            total_ensaios_executados = 0
            calculos_processados = set()
            ensaios_unicos = set()
            
            for analise_calculo in queryset:
                calculos_processados.add(analise_calculo.calculos)
                
                try:
                    # Parsear JSON dos ensaios
                    if isinstance(analise_calculo.ensaios_utilizados, list):
                        ensaios_json = analise_calculo.ensaios_utilizados
                    elif isinstance(analise_calculo.ensaios_utilizados, str):
                        ensaios_json = json.loads(analise_calculo.ensaios_utilizados)
                    else:
                        continue
                    
                    # Processar cada ensaio
                    for ensaio in ensaios_json:
                        ensaio_id = ensaio.get('id')
                        tempo_previsto = ensaio.get('tempo_previsto')
                        tempo_trabalho = ensaio.get('tempo_trabalho')
                        
                        # Se tempo_trabalho não está no JSON, buscar do modelo Ensaio
                        if ensaio_id and not tempo_trabalho:
                            if ensaio_id not in ensaios_cache:
                                try:
                                    ensaio_modelo = Ensaio.objects.get(id=ensaio_id)
                                    ensaios_cache[ensaio_id] = {
                                        'tempo_previsto': ensaio_modelo.tempo_previsto,
                                        'tempo_trabalho': ensaio_modelo.tempo_trabalho
                                    }
                                except Ensaio.DoesNotExist:
                                    ensaios_cache[ensaio_id] = {
                                        'tempo_previsto': None,
                                        'tempo_trabalho': None
                                    }
                            
                            tempo_trabalho = ensaios_cache[ensaio_id]['tempo_trabalho']
                            # Se tempo_previsto também não está no JSON, usar do modelo
                            if not tempo_previsto:
                                tempo_previsto = ensaios_cache[ensaio_id]['tempo_previsto']
                        
                        tempo_previsto_total_min += tempo_para_minutos(tempo_previsto)
                        tempo_trabalho_total_min += tempo_para_minutos(tempo_trabalho)
                        total_ensaios_executados += 1
                        if ensaio_id:
                            ensaios_unicos.add(ensaio_id)
                
                except (json.JSONDecodeError, TypeError):
                    continue
            
            # Calcular diferença e eficiência
            diferenca_minutos = tempo_trabalho_total_min - tempo_previsto_total_min
            eficiencia = (tempo_previsto_total_min / tempo_trabalho_total_min * 100) if tempo_trabalho_total_min > 0 else 0
            
            return Response({
                'tipo_agrupamento': 'geral',
                'periodo': {
                    'data_inicial': data_inicial,
                    'data_final': data_final
                },
                'totais': {
                    'tempo_previsto_total': minutos_para_horas_str(tempo_previsto_total_min),
                    'tempo_previsto_minutos': round(tempo_previsto_total_min, 2),
                    'tempo_trabalho_total': minutos_para_horas_str(tempo_trabalho_total_min),
                    'tempo_trabalho_minutos': round(tempo_trabalho_total_min, 2),
                    'diferenca': minutos_para_horas_str(abs(diferenca_minutos)),
                    'diferenca_minutos': round(diferenca_minutos, 2),
                    'status': 'No prazo' if diferenca_minutos <= 0 else 'Atrasado',
                    'eficiencia_percentual': round(eficiencia, 2),
                    'total_ensaios_executados': total_ensaios_executados,
                    'ensaios_diferentes': len(ensaios_unicos),
                    'calculos_diferentes': len(calculos_processados)
                }
            })


###############################################################################################
# URLs e configurações da sua API do Azure OpenAI
AZURE_OPENAI_ENDPOINT = "https://troop-mg863zkh-eastus2.cognitiveservices.azure.com/openai/deployments/o4-mini-labDb/chat/completions?api-version=2025-01-01-preview"
AZURE_OPENAI_DEPLOYMENT = "o4-mini-labDb"
AZURE_OPENAI_API_VERSION = "2024-04-01-preview"

class ChatViewSet(viewsets.ViewSet):
    """
    ViewSet para interagir com a API de Chat do Azure OpenAI.
    """
    @action(detail=False, methods=['post'], url_path='completions')
    def chat_completions(self, request):
        prompt = request.data.get('prompt')

        if not prompt:
            return Response({"error": "Prompt não fornecido"}, status=http_status.HTTP_400_BAD_REQUEST)

        try:
            # 1. Crie o cliente da Azure OpenAI com as credenciais seguras
            client = AzureOpenAI(
                api_version=settings.AZURE_OPENAI_API_VERSION,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.OPENAI_API_KEY,
            )

            # 2. Faça a chamada para a API usando o cliente
            response = client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": """
                            Você vai receber dados de 
                            resultados de analises e vai verificar se estão de acordo com a Ficha Tecnica que voce vai receber na requisição e tambem vai verifiar se estao de acordo 
                            com as normas NBR recebidas para emissão de um laudo. 
                            Se o produto for Argamassa tipo Assentamento ou Fixação usar NBR 13281-2, 
                            Se for Argamassa tipo Revestimento usar NBR 13281-1,
                            Separe o paracer em uma parte de acordo com a ficha técnica e na outra parte de acordo com as normas NBR.
                            Se estiver tudo em conformidade responda Conforme, se não responsa Nao Conforme
                            e justifique o porquê como os valores exigidos pela ficha técnica e pela norma NBR.
                            Se o produto não for argamassa, utilize a norma mais recenente equivalente ao produto, mas somente informe os valores desta para refferência e informação. Não precisa verificar conformidade.
                        """,
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model=settings.AZURE_OPENAI_DEPLOYMENT
            )

            # 3. Extraia e retorne a resposta do modelo
            model_response = response.choices[0].message.content

            return Response({"message": model_response}, status=http_status.HTTP_200_OK)

        except APIError as e:
            # Captura erros específicos da API da OpenAI
            return Response(
                {"error": f"Erro da API do Azure OpenAI: {e.status_code} - {e.body.get('message')}"},
                status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            # Captura outros erros inesperados
            return Response(
                {"error": f"Ocorreu um erro inesperado: {str(e)}"},
                status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
#------------------------------------ ------------------------------------############

