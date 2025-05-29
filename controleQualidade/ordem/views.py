from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status, viewsets

from controleQualidade.ordem.serializers import OrdemSerializer
from .models import Ordem
from rest_framework.response import Response


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