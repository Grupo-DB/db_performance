from django.shortcuts import render
from rest_framework import viewsets
from .models import Reserva, Objeto
from .permissions import VerTodosGerirGestores
from .serializers import ReservaSerializer, ObjetoSerializer

class ObjetoViewSet(viewsets.ModelViewSet):
    permission_classes = [VerTodosGerirGestores]
    queryset = Objeto.objects.all()
    serializer_class = ObjetoSerializer

class ReservaViewSet(viewsets.ModelViewSet):
    permission_classes = [VerTodosGerirGestores]
    queryset = Reserva.objects.all()
    serializer_class = ReservaSerializer
