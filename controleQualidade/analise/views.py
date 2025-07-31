from django.shortcuts import render
from rest_framework.response import Response
from rest_framework import viewsets
from .models import Analise, AnaliseEnsaio, AnaliseCalculo
from rest_framework.decorators import action
from .serializer import AnaliseSerializer, AnaliseEnsaioSerializer, AnaliseCalculoSerializer
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

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

    @csrf_exempt
    @action(detail=False, methods=['post'], url_path='resultados-anteriores')
    def resultados_anteriores(self, request):
        """
        Busca resultados anteriores de análises com o mesmo cálculo e ensaios,
        podendo pesquisar por ID e/ou nome do ensaio.
        """
        if request.method == 'POST':
            data = request.data
            calculo_descricao = data.get('calculo')
            ensaio_ids = data.get('ensaioIds', [])
            ensaio_nome = data.get('ensaio_nome', None)
            limit = int(data.get('limit', 10))

            print(f"✅ POST - Parâmetros recebidos: calculo={calculo_descricao}, ensaio_ids={ensaio_ids}, ensaio_nome={ensaio_nome}, limit={limit}")

            if not calculo_descricao and not ensaio_ids and not ensaio_nome:
                return Response({
                    "error": "Parâmetros 'calculo', 'ensaioIds' ou 'ensaio_nome' são obrigatórios"
                }, status=400)

            try:
                from .models import AnaliseCalculo, AnaliseEnsaio

                # Converter IDs para inteiros se existirem
                if ensaio_ids:
                    ensaio_ids = [int(id) for id in ensaio_ids]
                    print(f"✅ Buscando análises com ensaios IDs: {ensaio_ids}")

                # Buscar análises através da tabela AnaliseCalculo
                analises_com_calculo = Analise.objects.filter(
                    id__in=AnaliseCalculo.objects.filter(
                        calculos=calculo_descricao
                    ).values_list('analise_id', flat=True)
                ).distinct()
                print(f"✅ Análises com cálculo encontradas: {analises_com_calculo.count()}")

                # Buscar análises que têm os ensaios especificados por ID ou nome
                analises_com_ensaios = Analise.objects.none()
                if ensaio_ids:
                    analises_com_ensaios = Analise.objects.filter(
                        id__in=AnaliseEnsaio.objects.filter(
                            ensaios_id__in=ensaio_ids
                        ).values_list('analise_id', flat=True)
                    )
                if ensaio_nome:
                    analises_por_nome = Analise.objects.filter(
                        id__in=AnaliseEnsaio.objects.filter(
                            ensaios__descricao__iexact=ensaio_nome
                        ).values_list('analise_id', flat=True)
                    )
                    analises_com_ensaios = analises_com_ensaios | analises_por_nome if analises_com_ensaios.exists() else analises_por_nome

                analises_com_ensaios = analises_com_ensaios.distinct()
                print(f"✅ Análises com ensaios encontradas: {analises_com_ensaios.count()}")

                # Intersecção das duas consultas
                analises_filtradas = analises_com_calculo.union(analises_com_ensaios)
                print(f"✅ Análises filtradas (intersecção): {analises_filtradas.count()}")

                # Ordenar por ID mais recente e limitar
                analises_filtradas = analises_filtradas.order_by('-id')[:limit]

                resultados = []

                for analise in analises_filtradas:
                    print(f"✅ Processando análise ID: {analise.id}")
                    analise_data = {
                        'analise_id': analise.id,
                        'amostra_numero': analise.amostra.numero if analise.amostra else None,
                        'data_analise': analise.data if hasattr(analise, 'data') else None,
                        'responsavel': None,
                        'digitador': None,
                    }

                    # Buscar resultado do cálculo na tabela AnaliseCalculo
                    try:
                        calculo_analise = AnaliseCalculo.objects.filter(
                            analise_id=analise.id,
                            calculos=calculo_descricao
                        ).first()
                        if calculo_analise:
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
                    except Exception as e:
                        print(f"❌ Erro ao buscar cálculo: {e}")

                    # Buscar ensaios utilizados na tabela AnaliseEnsaio
                    filtro_ensaio = {}
                    if ensaio_ids:
                        filtro_ensaio['ensaios_id__in'] = ensaio_ids
                    if ensaio_nome:
                        filtro_ensaio['ensaios__descricao__iexact'] = ensaio_nome

                    if filtro_ensaio:
                        print('kkkkkkkkkkkkkkkkkk')
                        for ensaio_analise in AnaliseEnsaio.objects.filter(
                            analise_id=analise.id, **filtro_ensaio
                        ):
                            resultados.append({
                                **analise_data,
                                'tipo': 'ENSAIO',
                                'resultado_calculo': None,
                                'ensaio_id': ensaio_analise.ensaios_id,
                                'ensaio_descricao': ensaio_analise.ensaios.descricao,
                                'valor_ensaio': ensaio_analise.ensaios_utilizados,
                                'ensaio_responsavel': ensaio_analise.responsavel,
                                'ensaio_digitador': ensaio_analise.digitador,
                            })
                            if not analise_data['responsavel']:
                                analise_data['responsavel'] = ensaio_analise.responsavel

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

