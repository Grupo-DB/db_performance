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

