from django.shortcuts import render
from rest_framework import viewsets
from .models import Local, Royalty, Fatura
from .serializers import LocalSerializer, RoyaltySerializer, FaturaSerializer

class LocalViewSet(viewsets.ModelViewSet):
    queryset = Local.objects.all()
    serializer_class = LocalSerializer

class RoyaltyViewSet(viewsets.ModelViewSet):
    queryset = Royalty.objects.all()
    serializer_class = RoyaltySerializer

class FaturaViewSet(viewsets.ModelViewSet):
    queryset = Fatura.objects.all()
    serializer_class = FaturaSerializer

