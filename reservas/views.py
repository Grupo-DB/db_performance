from django.shortcuts import render
from rest_framework import viewsets
from .models import Reserva, Objeto
from .serializers import ReservaSerializer, ObjetoSerializer

class ObjetoViewSet(viewsets.ModelViewSet):
    queryset = Objeto.objects.all()
    serializer_class = ObjetoSerializer

class ReservaViewSet(viewsets.ModelViewSet):
    queryset = Reserva.objects.all()
    serializer_class = ReservaSerializer
