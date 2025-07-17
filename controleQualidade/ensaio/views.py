from django.shortcuts import render
from rest_framework import viewsets
from .models import TipoEnsaio, Ensaio, Variavel
from .serializers import TipoEnsaioSerializer, EnsaioSerializer, VariavelSerializer
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status, viewsets
import pandas as pd

class TipoEnsaioViewSet(viewsets.ModelViewSet):
    queryset = TipoEnsaio.objects.all()
    serializer_class = TipoEnsaioSerializer
    
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
class EnsaioViewSet(viewsets.ModelViewSet):
    queryset = Ensaio.objects.all()
    serializer_class = EnsaioSerializer
    
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

class VariavelViewSet(viewsets.ModelViewSet):
    queryset = Variavel.objects.all()
    serializer_class = VariavelSerializer
    
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)