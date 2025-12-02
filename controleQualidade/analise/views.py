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
        - data_inicial: data inicial no formato YYYY-MM-DD
        - data_final: data final no formato YYYY-MM-DD
        """
        from django.db.models import Q
        from datetime import datetime
        import json
        
        data = request.data
        ensaio_ids = data.get('ensaios_ids', [])
        ensaio_descricao = data.get('ensaio_descricao')
        data_inicial = data.get('data_inicio')
        data_final = data.get('data_fim')
        
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
        
        # Processar resultados e calcular médias manualmente
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
                    
                    # Agrupar por ID do ensaio
                    key = f"{ensaio_id}_{ensaio_desc}"
                    if key not in ensaios_agrupados:
                        ensaios_agrupados[key] = {
                            'ensaio_id': ensaio_id,
                            'ensaio_descricao': ensaio_desc,
                            'valores': [],
                            'unidade': ensaio.get('unidade', '')
                        }
                    
                    ensaios_agrupados[key]['valores'].append(valor_float)
            
            except (json.JSONDecodeError, TypeError) as e:
                continue
        
        # Calcular estatísticas
        resultados = []
        for key, dados in ensaios_agrupados.items():
            valores = dados['valores']
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
        
        # Filtrar análises finalizadas no período
        queryset = AnaliseEnsaio.objects.filter(
            analise__finalizada_at__gte=data_inicial,
            analise__finalizada_at__lte=data_final,
            analise__finalizada=True
        )
        
        # Filtrar por análise específica se fornecido
        if analise_id:
            queryset = queryset.filter(analise_id=analise_id)
        
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
        if agrupar_por_ensaio:
            # Agrupar por ensaio
            ensaios_agrupados = {}
            
            # Criar cache de ensaios do modelo para buscar tempo_trabalho
            from controleQualidade.ensaio.models import Ensaio
            ensaios_cache = {}
            
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
        """
        from django.db.models import Q
        from datetime import datetime
        import json
        
        data = request.data
        data_inicial = data.get('data_inicial')
        data_final = data.get('data_final')
        analise_ids = data.get('analise_ids', [])
        
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
        queryset = AnaliseEnsaio.objects.filter(
            analise__finalizada_at__gte=data_inicial,
            analise__finalizada_at__lte=data_final,
            analise__finalizada=True
        ).select_related('analise', 'analise__amostra')
        
        # Filtrar por análises específicas se fornecido
        if analise_ids:
            analise_ids = [int(id) for id in analise_ids]
            queryset = queryset.filter(analise_id__in=analise_ids)
        
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
                    'data_finalizacao': str(analise.finalizada_at) if analise.finalizada_at else None,
                    'tempo_previsto_total_minutos': 0,
                    'tempo_trabalho_total_minutos': 0,
                    'quantidade_ensaios': 0,
                    'quantidade_ensaios_diretos': 0,
                    'quantidade_ensaios_calculos': 0,
                    'ensaios_detalhes': []
                }
            
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
                    
                    analises_agrupadas[analise_id]['tempo_previsto_total_minutos'] += tempo_prev_min
                    analises_agrupadas[analise_id]['tempo_trabalho_total_minutos'] += tempo_trab_min
                    analises_agrupadas[analise_id]['quantidade_ensaios'] += 1
                    analises_agrupadas[analise_id]['quantidade_ensaios_diretos'] += 1
                    
                    # Adicionar detalhes do ensaio
                    analises_agrupadas[analise_id]['ensaios_detalhes'].append({
                        'ensaio_id': ensaio_id,
                        'ensaio_descricao': ensaio_desc,
                        'tempo_previsto': minutos_para_horas_str(tempo_prev_min),
                        'tempo_trabalho': minutos_para_horas_str(tempo_trab_min),
                        'origem': 'ensaio'
                    })
            
            except (json.JSONDecodeError, TypeError):
                continue
        
        # Processar ensaios dentro dos cálculos
        calculos_queryset = AnaliseCalculo.objects.filter(
            analise__finalizada_at__gte=data_inicial,
            analise__finalizada_at__lte=data_final,
            analise__finalizada=True
        ).select_related('analise', 'analise__amostra')
        
        # Filtrar por análises específicas se fornecido
        if analise_ids:
            calculos_queryset = calculos_queryset.filter(analise_id__in=analise_ids)
        
        for analise_calculo in calculos_queryset:
            analise = analise_calculo.analise
            analise_id = analise.id
            
            # Inicializar se ainda não existe
            if analise_id not in analises_agrupadas:
                analises_agrupadas[analise_id] = {
                    'analise_id': analise_id,
                    'amostra_numero': analise.amostra.numero if analise.amostra else None,
                    'data_finalizacao': str(analise.finalizada_at) if analise.finalizada_at else None,
                    'tempo_previsto_total_minutos': 0,
                    'tempo_trabalho_total_minutos': 0,
                    'quantidade_ensaios': 0,
                    'quantidade_ensaios_diretos': 0,
                    'quantidade_ensaios_calculos': 0,
                    'ensaios_detalhes': []
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
                    
                    analises_agrupadas[analise_id]['tempo_previsto_total_minutos'] += tempo_prev_min
                    analises_agrupadas[analise_id]['tempo_trabalho_total_minutos'] += tempo_trab_min
                    analises_agrupadas[analise_id]['quantidade_ensaios'] += 1
                    analises_agrupadas[analise_id]['quantidade_ensaios_calculos'] += 1
                    
                    # Adicionar detalhes do ensaio (com indicação de que vem de cálculo)
                    analises_agrupadas[analise_id]['ensaios_detalhes'].append({
                        'ensaio_id': ensaio_id,
                        'ensaio_descricao': f"{ensaio_desc} (via {analise_calculo.calculos})",
                        'tempo_previsto': minutos_para_horas_str(tempo_prev_min),
                        'tempo_trabalho': minutos_para_horas_str(tempo_trab_min),
                        'origem': 'calculo',
                        'calculo': analise_calculo.calculos
                    })
            
            except (json.JSONDecodeError, TypeError):
                continue
        
        # Formatar resultados
        resultados = []
        for analise_id, dados in analises_agrupadas.items():
            tempo_prev_min = dados['tempo_previsto_total_minutos']
            tempo_trab_min = dados['tempo_trabalho_total_minutos']
            
            # Calcular diferença e eficiência
            diferenca_minutos = tempo_trab_min - tempo_prev_min
            eficiencia = (tempo_prev_min / tempo_trab_min * 100) if tempo_trab_min > 0 else 0
            
            resultados.append({
                'analise_id': dados['analise_id'],
                'amostra_numero': dados['amostra_numero'],
                'data_finalizacao': dados['data_finalizacao'],
                'tempo_previsto_total': minutos_para_horas_str(tempo_prev_min),
                'tempo_previsto_minutos': round(tempo_prev_min, 2),
                'tempo_trabalho_total': minutos_para_horas_str(tempo_trab_min),
                'tempo_trabalho_minutos': round(tempo_trab_min, 2),
                'diferenca': minutos_para_horas_str(abs(diferenca_minutos)),
                'diferenca_minutos': round(diferenca_minutos, 2),
                'status': 'No prazo' if diferenca_minutos <= 0 else 'Atrasado',
                'eficiencia_percentual': round(eficiencia, 2),
                'quantidade_ensaios': dados['quantidade_ensaios'],
                'quantidade_ensaios_diretos': dados['quantidade_ensaios_diretos'],
                'quantidade_ensaios_calculos': dados['quantidade_ensaios_calculos'],
                'ensaios_detalhes': dados['ensaios_detalhes']
            })
        
        # Ordenar por ID da análise (mais recente primeiro)
        resultados.sort(key=lambda x: x['analise_id'], reverse=True)
        
        return Response({
            'total_analises': len(resultados),
            'periodo': {
                'data_inicial': data_inicial,
                'data_final': data_final
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
        - calculos_ids: lista de IDs de cálculos (opcional) - agrupa por ID
        - agrupar_por: 'id' ou 'descricao' (padrão: 'id' se calculos_ids fornecido, senão 'descricao')
        - data_inicial: data inicial no formato YYYY-MM-DD
        - data_final: data final no formato YYYY-MM-DD
        """
        from django.db.models import Avg, Count, Min, Max, Q
        from datetime import datetime
        
        data = request.data
        calculo_descricao = data.get('calculo')
        calculos_ids = data.get('calculos_ids', [])
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
        )
        
        # Filtrar por cálculo se fornecido
        if calculo_descricao:
            queryset = queryset.filter(calculos__icontains=calculo_descricao)
        
        # Filtrar por cálculos se fornecidos
        if calculos_ids:
            calculos_ids = [int(id) for id in calculos_ids]
            filtros_calculos = Q()
            for calculo_id in calculos_ids:
                filtros_calculos |= Q(ensaios_utilizados__icontains=f'"id": {calculo_id}')
            queryset = queryset.filter(filtros_calculos)
        
        # Processar resultados manualmente
        resultados_por_calculo = {}
        
        for analise_calculo in queryset:
            calculo_nome = analise_calculo.calculos
            ensaios_utilizados = analise_calculo.ensaios_utilizados
            
            if agrupar_por == 'descricao':
                # Agrupar apenas por descrição do cálculo
                chave = calculo_nome
                
                if chave not in resultados_por_calculo:
                    resultados_por_calculo[chave] = {
                        'nome': calculo_nome,
                        'valores': [],
                        'quantidade': 0
                    }
                
                if analise_calculo.resultados is not None:
                    resultados_por_calculo[chave]['valores'].append(analise_calculo.resultados)
                    resultados_por_calculo[chave]['quantidade'] += 1
            else:
                # Agrupar por ID de cálculo
                if not ensaios_utilizados:
                    continue
                
                # Encontrar os IDs dos cálculos neste registro
                ids_encontrados = []
                for ensaio in ensaios_utilizados:
                    if isinstance(ensaio, dict):
                        ensaio_id = ensaio.get('id')
                        if ensaio_id:
                            # Se calculos_ids foi fornecido, verificar se este ID está na lista
                            if not calculos_ids or ensaio_id in calculos_ids:
                                ids_encontrados.append(ensaio_id)
                
                # Se não encontrou nenhum ID relevante, pular este registro
                if not ids_encontrados:
                    continue
                
                # Agrupar por cada ID de cálculo encontrado
                for calculo_id in ids_encontrados:
                    # Criar chave única combinando ID e nome
                    chave = f"{calculo_id}|{calculo_nome}"
                    
                    if chave not in resultados_por_calculo:
                        resultados_por_calculo[chave] = {
                            'id': calculo_id,
                            'nome': calculo_nome,
                            'valores': [],
                            'quantidade': 0
                        }
                    
                    if analise_calculo.resultados is not None:
                        resultados_por_calculo[chave]['valores'].append(analise_calculo.resultados)
                        resultados_por_calculo[chave]['quantidade'] += 1
        
        # Calcular médias
        resultados = []
        for chave, dados in resultados_por_calculo.items():
            valores = dados['valores']
            if valores:
                resultado = {
                    'calculo': dados['nome'],
                    'media': round(sum(valores) / len(valores), 4),
                    'quantidade_analises': dados['quantidade'],
                    'valor_minimo': min(valores),
                    'valor_maximo': max(valores),
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

