from datetime import datetime
from django.shortcuts import render
from rest_framework import viewsets,status
from rest_framework.decorators import action
from .models import Amostra, TipoAmostra, ProdutoAmostra
from .serializers import AmostraSerializer, TipoAmostraSerializer, ProdutoAmostraSerializer
from rest_framework.response import Response
import pandas as pd

class TipoAmostraViewSet(viewsets.ModelViewSet):
    queryset = TipoAmostra.objects.all()
    serializer_class = TipoAmostraSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    

class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = ProdutoAmostra.objects.all()
    serializer_class = ProdutoAmostraSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
class AmostraViewSet(viewsets.ModelViewSet):
    queryset = Amostra.objects.all()
    serializer_class = AmostraSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='proximo-sequencial/(?P<material_id>[^/.]+)')
    def proximo_sequencial(self, request, material_id=None):
        ano = datetime.now().year % 100  # dois últimos dígitos do ano
        # Busca todas as amostras do material e ano atual
        amostras = Amostra.objects.filter(material_id=material_id, numero__icontains=str(ano))
        sequenciais = []
        for amostra in amostras:
            try:
                # Exemplo: 'Calc25 08.392' -> pega '08.392', remove ponto, converte para int
                seq_str = amostra.numero.split(' ')[-1].replace('.', '')
                sequenciais.append(int(seq_str))
            except Exception:
                pass
        proximo = max(sequenciais) + 1 if sequenciais else 1
        return Response(proximo)