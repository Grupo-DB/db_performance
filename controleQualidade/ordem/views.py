from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.decorators import action
from controleQualidade.ordem.OrdemHistorySerializer import OrdemHistorySerializer
from controleQualidade.ordem.serializers import OrdemSerializer, OrdemExpressaSerializer
from .models import Ordem, OrdemExpressa, OrdemExpressaCalculo, OrdemExpressaEnsaio
from django.db.models import Max, Func, IntegerField
from rest_framework.response import Response
from simple_history.utils import update_change_reason
from django.contrib.auth import get_user_model
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend, FilterSet, DateFromToRangeFilter


import pandas as pd
import requests

class OrdemViewSet(viewsets.ModelViewSet):
    # O `OrdemSerializer` expande `plano_detalhes`, e o `PlanoAnaliseSerializer`
    # expande os ensaios e os cálculos de cada plano — com `tipo_ensaio` e
    # `variavel` de CADA ensaio. Sem prefetch isso vira uma cascata de queries por
    # ordem, e a tela de Ordens pede a lista inteira ao abrir. É o mesmo padrão que
    # custava ~6.200 queries na listagem de análises (ver `_RELACOES_LISTA_M2M` em
    # analise/views.py), e os caminhos aqui são os mesmos de lá, sem o prefixo.
    queryset = Ordem.objects.prefetch_related(
        'plano_analise',
        'plano_analise__ensaios__tipo_ensaio',
        'plano_analise__ensaios__variavel',
        'plano_analise__calculos_ensaio__ensaios__tipo_ensaio',
        'plano_analise__calculos_ensaio__ensaios__variavel',
    )
    serializer_class = OrdemSerializer
    def partial_update(self, request, *args, **kwargs):
        istance = self.get_object()
        serializer = self.get_serializer(istance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='proximo-numero')
    def proximo_numero(self, request):
        # Só a coluna `numero`: instanciar o model inteiro de cada ordem (e arrastar
        # o prefetch da listagem junto) para ler um campo é desperdício. O filtro
        # continua em Python porque `numero` é texto e a base tem valores não
        # numéricos — uma agregação SQL engasgaria neles.
        numeros = []
        for numero in Ordem.objects.values_list('numero', flat=True):
            try:
                numeros.append(int(numero))
            except (ValueError, TypeError):
                continue
        max_numero = max(numeros) if numeros else 0
        proximo = max_numero + 1
        return Response({'numero': proximo})
    

class ExpressaViewSet(viewsets.ModelViewSet):
    # Mesma história da OrdemViewSet: `get_ensaio_detalhes` e
    # `get_calculo_ensaio_detalhes` percorrem as tabelas intermediárias e
    # serializam cada ensaio com tipo e variáveis.
    queryset = OrdemExpressa.objects.prefetch_related(
        'ensaios_intermediarios__ensaio__tipo_ensaio',
        'ensaios_intermediarios__ensaio__variavel',
        'calculos_intermediarios__calculo__ensaios__tipo_ensaio',
        'calculos_intermediarios__calculo__ensaios__variavel',
    )
    serializer_class = OrdemExpressaSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()     
        # Separar ensaios/calculos dos outros campos
        ensaios_data = request.data.pop('ensaios', None)
        calculos_data = request.data.pop('calculos_ensaio', None)
        
        # ===== PROCESSAR ENSAIOS =====
        if ensaios_data is not None:            
            # Limpar ensaios existentes da tabela intermediária
            OrdemExpressaEnsaio.objects.filter(ordem_expressa=instance).delete()
            
            # Criar novos registros na tabela intermediária
            for idx, ensaio_item in enumerate(ensaios_data):
                if isinstance(ensaio_item, dict):
                    # Formato: {"id": 76, ...}
                    ensaio_id = ensaio_item.get('id')
                    OrdemExpressaEnsaio.objects.create(
                        ordem_expressa=instance,
                        ensaio_id=ensaio_id,
                        ordem=idx
                    )
                else:
                    # Formato antigo: apenas ID numérico
                    OrdemExpressaEnsaio.objects.create(
                        ordem_expressa=instance,
                        ensaio_id=ensaio_item,
                        ordem=idx
                    )
        
        # ===== PROCESSAR CÁLCULOS =====
        if calculos_data is not None:           
            OrdemExpressaCalculo.objects.filter(ordem_expressa=instance).delete()
            
            for idx, calculo_item in enumerate(calculos_data):
                if isinstance(calculo_item, dict):
                    calculo_id = calculo_item.get('id')
                    OrdemExpressaCalculo.objects.create(
                        ordem_expressa=instance,
                        calculo_id=calculo_id,
                        ordem=idx
                    )
                else:
                    OrdemExpressaCalculo.objects.create(
                        ordem_expressa=instance,
                        calculo_id=calculo_item,
                        ordem=idx
                    )              
        # Atualizar campos simples (numero, data, responsavel, etc.)
        if request.data:  # Se ainda tem outros campos
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
        
        # Retornar dados atualizados
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='proximo-numero')
    def proximo_numero(self, request):
        qs = OrdemExpressa.objects.all()
        numeros = []
        for ordem in qs:
            try:
                numeros.append(int(ordem.numero))
            except (ValueError, TypeError):
                continue
        max_numero = max(numeros) if numeros else 0
        proximo = max_numero + 1
        return Response({'numero': proximo})
    
    @action(detail=False, methods=['post'], url_path='register')
    def registerExpressa(self, request):
        try:
            data = request.data          
            # Extrair listas de IDs
            ensaios_ids = data.pop('ensaios', [])
            calculos_ids = data.pop('calculos_ensaio', []) 
            # Pegar laboratório do usuário logado
            laboratorio_usuario = request.user.colaborador.laboratorio  # Ajuste conforme sua model            
            # Criar ordem expressa
            ordem_expressa = OrdemExpressa.objects.create(**data)
            
            # Salvar ensaios na tabela intermediária COM laboratório
            for ordem, ensaio_id in enumerate(ensaios_ids):
                OrdemExpressaEnsaio.objects.create(
                    ordem_expressa=ordem_expressa,
                    ensaio_id=ensaio_id,
                    ordem=ordem,
                    laboratorio=laboratorio_usuario  # ✅ Salvar lab do criador
                )
            
            # Salvar cálculos na tabela intermediária COM laboratório
            for ordem, calculo_id in enumerate(calculos_ids):
                OrdemExpressaCalculo.objects.create(
                    ordem_expressa=ordem_expressa,
                    calculo_id=calculo_id,
                    ordem=ordem,
                    laboratorio=laboratorio_usuario  # ✅ Salvar lab do criador
                )
      
            # Serializar e retornar
            serializer = self.get_serializer(ordem_expressa)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

# History ViewSet    
class OrdemHistoryFilter(FilterSet):
    history_date = DateFromToRangeFilter()  # permite filtrar por intervalo de datas

    class Meta:
        model = Ordem.history.model  # pega o modelo histórico
        fields = ['history_user', 'history_type', 'history_date']

class OrdemHistoryViewSet(ReadOnlyModelViewSet):
    serializer_class = OrdemHistorySerializer
    #permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = OrdemHistoryFilter
    ordering_fields = ['history_date']
    ordering = ['-history_date']  # ordenação padrão
    pagination_class = None  # ou defina uma paginação global ou customizada

    def get_queryset(self):
        ordem_pk = self.kwargs.get('ordem_pk')
        return Ordem.history.filter(id=ordem_pk)   