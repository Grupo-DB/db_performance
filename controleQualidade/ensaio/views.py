from django.shortcuts import render
from rest_framework import viewsets
from .models import TipoEnsaio, Ensaio, Variavel, PlanoPeneira, Finalidade, Fornecedor
from .serializers import (
    TipoEnsaioSerializer, EnsaioSerializer, VariavelSerializer, PlanoPeneiraSerializer,
    FinalidadeSerializer, FornecedorSerializer,
)
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
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
    
class VariavelViewSet(viewsets.ModelViewSet):
    queryset = Variavel.objects.all()
    serializer_class = VariavelSerializer
    
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)    
    
class EnsaioViewSet(viewsets.ModelViewSet):
    queryset = Ensaio.objects.all()
    serializer_class = EnsaioSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)



class PlanoPeneiraViewSet(viewsets.ModelViewSet):
    """CRUD dos planos de peneiramento (cadastro do Controle de Qualidade).

    Aceita `?tipo=peneiras_secas|peneiras_umidas` e `?ativo=true|false`: a tela
    de análise e a de relatórios pedem só os ativos, enquanto o cadastro lista
    tudo para poder reativar um plano desligado.
    """

    queryset = PlanoPeneira.objects.all()
    serializer_class = PlanoPeneiraSerializer
    # O projeto não define DEFAULT_PERMISSION_CLASSES (tudo fica AllowAny). Aqui
    # é cadastro que muda o que o laboratório inteiro enxerga na digitação, então
    # exige o token — o front já manda o Bearer em toda requisição.
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        tipo = self.request.query_params.get('tipo')
        if tipo:
            qs = qs.filter(tipo=tipo)
        ativo = self.request.query_params.get('ativo')
        if ativo is not None:
            qs = qs.filter(ativo=str(ativo).lower() in ('1', 'true', 'sim'))
        return qs

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


class CadastroSimplesViewSet(viewsets.ModelViewSet):
    """CRUD dos cadastros de lista da amostra (finalidade, fornecedor).

    `?ativo=true` é o que a tela de Amostras pede: o select só oferece o que está
    em uso, enquanto o cadastro lista tudo para poder reativar.
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        ativo = self.request.query_params.get('ativo')
        if ativo is not None:
            qs = qs.filter(ativo=str(ativo).lower() in ('1', 'true', 'sim'))
        return qs

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


class FinalidadeViewSet(CadastroSimplesViewSet):
    queryset = Finalidade.objects.all()
    serializer_class = FinalidadeSerializer


class FornecedorViewSet(CadastroSimplesViewSet):
    queryset = Fornecedor.objects.all()
    serializer_class = FornecedorSerializer
