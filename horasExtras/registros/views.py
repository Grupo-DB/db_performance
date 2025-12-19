from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.decorators import action
from .models import RegistroHoraExtra
from .serializers import RegistroHoraExtraSerializer
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status, viewsets
from django.db.models import Sum
import pandas as pd
from avaliacoes.management.models import Colaborador

class RegistroHoraExtraViewSet(viewsets.ModelViewSet):
    queryset = RegistroHoraExtra.objects.all()
    serializer_class = RegistroHoraExtraSerializer

    def get_queryset(self):
        queryset = RegistroHoraExtra.objects.all()
        
        # Filtro por colaborador
        colaborador = self.request.query_params.get('colaborador', None)
        if colaborador:
            queryset = queryset.filter(colaborador__icontains=colaborador)
        
        # Filtro por filial do colaborador
        filial_id = self.request.query_params.get('filial', None)
        if filial_id:
            colaboradores_filial = Colaborador.objects.filter(filial_id=filial_id).values_list('nome', flat=True)
            queryset = queryset.filter(colaborador__in=colaboradores_filial)
        
        # Filtro por ambiente do colaborador
        ambiente_id = self.request.query_params.get('ambiente', None)
        if ambiente_id:
            colaboradores_ambiente = Colaborador.objects.filter(ambiente_id=ambiente_id).values_list('nome', flat=True)
            queryset = queryset.filter(colaborador__in=colaboradores_ambiente)
        
        # Filtro por responsável
        responsavel = self.request.query_params.get('responsavel', None)
        if responsavel:
            queryset = queryset.filter(responsavel__icontains=responsavel)
        
        # Filtro por mês e ano
        mes = self.request.query_params.get('mes', None)
        ano = self.request.query_params.get('ano', None)
        if mes and ano:
            queryset = queryset.filter(data__month=mes, data__year=ano)
        elif mes:
            queryset = queryset.filter(data__month=mes)
        elif ano:
            queryset = queryset.filter(data__year=ano)
        
        # Filtro por data
        data_inicial = self.request.query_params.get('data_inicial', None)
        data_final = self.request.query_params.get('data_final', None)
        if data_inicial:
            queryset = queryset.filter(data__gte=data_inicial)
        if data_final:
            queryset = queryset.filter(data__lte=data_final)
        
        return queryset.order_by('-data', '-hora_inicial')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        
        # Calcular soma total de horas
        total_horas = queryset.aggregate(total=Sum('horas'))['total'] or 0
        
        return Response({
            'registros': serializer.data,
            'total_horas': float(total_horas),
            'quantidade_registros': queryset.count()
        })

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)