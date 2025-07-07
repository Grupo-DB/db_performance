from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.decorators import action
from controleQualidade.ordem.OrdemHistorySerializer import OrdemHistorySerializer
from controleQualidade.ordem.serializers import OrdemSerializer
from .models import Ordem, OrdemExpressa
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
    queryset = Ordem.objects.all()
    serializer_class = OrdemSerializer
    def partial_update(self, request, *args, **kwargs):
        istance = self.get_object()
        serializer = self.get_serializer(istance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='proximo-numero')
    def proximo_numero(self, request):
        # Filtra apenas números válidos
        qs = Ordem.objects.all()
        numeros = []
        for ordem in qs:
            try:
                numeros.append(int(ordem.numero))
            except (ValueError, TypeError):
                continue
        max_numero = max(numeros) if numeros else 0
        proximo = max_numero + 1
        return Response({'numero': proximo})
    

class ExpressaViewSet(viewsets.ModelViewSet):
    queryset = OrdemExpressa.objects.all()
    serializer_class = OrdemSerializer  # Use the same serializer for simplicity

    def partial_update(self, request, *args, **kwargs):
        istance = self.get_object()
        serializer = self.get_serializer(istance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='proximo-numero')
    def proximo_numero(self, request):
        # Filtra apenas números válidos
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