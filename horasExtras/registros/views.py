from django.shortcuts import render
from rest_framework import viewsets
from .models import RegistroHoraExtra
from .serializers import RegistroHoraExtraSerializer
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status, viewsets
import pandas as pd

class RegistroHoraExtraViewSet(viewsets.ModelViewSet):
    queryset = RegistroHoraExtra.objects.all()
    serializer_class = RegistroHoraExtraSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)