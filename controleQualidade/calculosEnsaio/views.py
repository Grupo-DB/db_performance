from django.shortcuts import render
from rest_framework import viewsets
from .models import CalculoEnsaio
from .serializers import CalculoEnsaioSerializer
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status, viewsets
import pandas as pd

class CalculoEnsaioViewSet(viewsets.ModelViewSet):
    queryset = CalculoEnsaio.objects.all()
    serializer_class = CalculoEnsaioSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)