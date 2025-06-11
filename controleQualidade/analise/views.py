from django.shortcuts import render
from rest_framework.response import Response
from rest_framework import viewsets
from .models import Analise, AnaliseEnsaio, AnaliseCalculo
from rest_framework.decorators import action
from .serializer import AnaliseSerializer, AnaliseEnsaioSerializer, AnaliseCalculoSerializer


class AnaliseViewSet(viewsets.ModelViewSet):
    queryset = Analise.objects.all()
    serializer_class = AnaliseSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
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

