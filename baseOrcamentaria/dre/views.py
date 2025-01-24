from django.shortcuts import render
from django.utils import timezone
from django.shortcuts import HttpResponse, get_list_or_404
from django.contrib.auth.models import User,Group
from django.contrib.auth import authenticate
from django.contrib.auth import login as login_django
from django.contrib.auth.decorators import login_required 
from rolepermissions.roles import assign_role
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from rest_framework.parsers import MultiPartParser,FormParser,FileUploadParser,JSONParser
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated,AllowAny,IsAdminUser,DjangoModelPermissions
from rest_framework.decorators import api_view,authentication_classes, permission_classes,parser_classes,action
from django.views.decorators.csrf import csrf_exempt
from rest_framework.response import Response
from rest_framework import status, viewsets
from django.conf import settings
from django.core.mail import send_mail
from datetime import datetime
from django.db.models import Q
from decimal import Decimal
from notifications.signals import notify
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from baseOrcamentaria.dre.models import Linha,Produto
from baseOrcamentaria.dre.serializers import LinhaSerializer,ProdutoSerializer
import pandas as pd
import locale
from collections import defaultdict
from rest_framework.response import Response
from rest_framework import status
from baseOrcamentaria .orcamento.models import OrcamentoBase

class LinhaViewSet(viewsets.ModelViewSet):
    queryset = Linha.objects.all()
    serializer_class = LinhaSerializer
    def partial_update(self, request, *args, **kwargs):
        istance = self.get_object()
        serializer = self.get_serializer(istance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        # Verifica se o corpo da requisição é uma lista
        if isinstance(request.data, list):
            serializer = self.get_serializer(data=request.data, many=True)
        else:
            serializer = self.get_serializer(data=request.data)
        
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='calculosDre')
    def calculosDre(self,request):
        linhas = Linha.objects.all()
        serializer = self.get_serializer(linhas, many=True)
        serialized_linhas = serializer.data

        df = pd.DataFrame(serialized_linhas)

        produtos = Produto.objects.all()
        serializer = ProdutoSerializer(produtos, many=True)
        serialized_produtos = serializer.data

        df_produtos = pd.DataFrame(serialized_produtos)


        # Extraindo o nome do produto de 'produto_detalhes'
        df["produto"] = df["produto_detalhes"].apply(lambda x: x["nome"])
        df["aliquota"] = df["produto_detalhes"].apply(lambda x: float(x["aliquota"]))

        # Convertendo 'quantidade_carregada' para float
        df["quantidade_carregada"] = df["quantidade_carregada"].astype(float)

        # Agrupando por produto e somando a quantidade carregada
        quantidade = df.groupby("produto")["quantidade_carregada"].sum()
        quantidade_dict = df.groupby("produto")["quantidade_carregada"].sum().to_dict()

        # Convertendo 'quantidade_carregada' e 'preco_medio_venda' para float
        df["quantidade_carregada"] = df["quantidade_carregada"].astype(float)
        df["preco_medio_venda"] = df["preco_medio_venda"].astype(float)

        # Calculando o faturamento por linha
        df["faturamento"] = df["quantidade_carregada"] * df["preco_medio_venda"]

        # Agrupando por produto e somando o faturamento
        faturamento = df.groupby("produto")["faturamento"].sum().to_dict()

        # Extraindo o nome do produto de 'produto_detalhes'
        df["aliquota"] = df["produto_detalhes"].apply(lambda x: float(x["aliquota"]))

        # Calculando a média da aliquota agrupada por produto
        media_aliquota = df.groupby("produto")["aliquota"].mean()

        # Calculando o faturamento total por produto
        faturamento_por_produto = df.groupby("produto")["faturamento"].sum()

          
        # Extraindo a alíquota de 'produto_detalhes'
        aliquota_dict = df.groupby("produto")["aliquota"].first().to_dict()

        deducao = (media_aliquota * faturamento_por_produto).to_dict()

        # Multiplicando a média da aliquota pelo faturamento total por produto
        deducao_produto = (media_aliquota * faturamento_por_produto)
        #receita liquida
        receita_liquida = faturamento_por_produto - deducao_produto 
        receita_liquida_dict = receita_liquida.to_dict()

        receita_bruta = faturamento_por_produto.sum()
        deducao_total = deducao_produto.sum()

        receita_liquida_total = receita_liquida.sum()
        quantidade_total = quantidade.sum()

        response_data = {
            'quantidade': quantidade_dict,
            'quantidade_total': quantidade_total,
            'faturamento': faturamento,
            'deudcao': deducao,
            'receita_liquida': receita_liquida_dict,
            'receita_bruta': receita_bruta,
            'deducao_total': deducao_total,
            'receita_liquida_total': receita_liquida_total,
            'aliquota': aliquota_dict
        }

        return JsonResponse(response_data, safe=False)
    


class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = Produto.objects.all()
    serializer_class = ProdutoSerializer
    def partial_update(self, request, *args, **kwargs):
        istance = self.get_object()
        serializer = self.get_serializer(istance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
