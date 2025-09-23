from django.shortcuts import render
from rest_framework.response import Response
from rest_framework import viewsets
from .models import Analise, AnaliseEnsaio, AnaliseCalculo
from rest_framework.decorators import action
from .serializer import AnaliseSerializer, AnaliseEnsaioSerializer, AnaliseCalculoSerializer
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone

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
                
class AnaliseEnsaioViewSet(viewsets.ModelViewSet):
    queryset = AnaliseEnsaio.objects.all()
    serializer_class = AnaliseEnsaioSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
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

