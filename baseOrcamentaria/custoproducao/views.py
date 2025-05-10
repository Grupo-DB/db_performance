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
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes   
from baseOrcamentaria.custoproducao.models import CustoProducao
from baseOrcamentaria.dre.models import Produto
from baseOrcamentaria.dre.serializers import ProdutoSerializer
from baseOrcamentaria.orcamento.models import CentroCustoPai,CentroCusto
from baseOrcamentaria.orcamento.serializers import CentroCustoPaiSerializer
from baseOrcamentaria.orcamento.models import OrcamentoBase
from baseOrcamentaria.orcamento.serializers import OrcamentoBaseSerializer
from baseOrcamentaria.custoproducao.serializers import CustoProducaoSerializer
from django.test import RequestFactory
from baseOrcamentaria.realizado.views import calculos_realizado
import pandas as pd
import requests
import locale
import numpy as np
from collections import defaultdict
from rest_framework.response import Response
from rest_framework import status


class CustoProducaoViewSet(viewsets.ModelViewSet):
    queryset = CustoProducao.objects.all()
    serializer_class = CustoProducaoSerializer
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
    
    @action(detail=False, methods=['post'], url_path='calculosCustoProducao')
    def calculosCustoProducao(self,request):
        ano = request.data.get('ano')
        periodo = request.data.get('periodo')
        
        filters = {}
        if ano: 
            filters['ano'] = ano

        if periodo:  
            filters['periodo__in'] = [periodo] if isinstance(periodo, int) else periodo


        if filters: 
            custos = CustoProducao.objects.filter(**filters)
        else:
            custos = CustoProducao.objects.all()    
    

        serializer = self.get_serializer(custos, many=True)
        serialized_custos = serializer.data

        if not serialized_custos:
            return JsonResponse({"error": "Nenhum registro encontrado."}, status=status.HTTP_404_NOT_FOUND)

        df = pd.DataFrame(serialized_custos)
        
        ############## PEGAR NOME DO PRODUTO E DO CENTRO DE CUSTO PAI ##############
        meses_recorrentes = request.data.get('periodo',[])
        produtos = Produto.objects.all()
        serializer = ProdutoSerializer(produtos, many=True)
        serialized_produtos = serializer.data
        df_produtos = pd.DataFrame(serialized_produtos)
        
        orcamentos = OrcamentoBase.objects.filter(mes_especifico__in=meses_recorrentes)
        serializer = OrcamentoBaseSerializer(orcamentos, many=True)
        serialized_orcamentos = serializer.data
        df_orcamentos = pd.DataFrame(serialized_orcamentos)
        
        # Garante que as colunas sejam numéricas
        df_orcamentos['valor_real'] = pd.to_numeric(df_orcamentos['valor_real'], errors='coerce')
        df_orcamentos['valor'] = pd.to_numeric(df_orcamentos['valor'], errors='coerce')

        # Usa 'valor_real' se não for nulo, caso contrário usa 'valor'
        #df_orcamentos['valor_usado'] = np.where(df_orcamentos['valor_real'].notnull(), df_orcamentos['valor_real'], df_orcamentos['valor'])
        #df_orcamentos['nome_cc_pai'] = df_orcamentos['cc_pai_detalhes'].apply(lambda x: x['nome'])
        
        df_orcamentos['valor_usado'] = np.where((df_orcamentos['valor_real'].notnull()) & (df_orcamentos['valor_real'] > 0), df_orcamentos['valor_real'], df_orcamentos['valor'])

        ccs_pai = CentroCustoPai.objects.all().values('id', 'nome')
        cc_pai_id_to_name = {cc_pai['id']: cc_pai['nome'] for cc_pai in ccs_pai}

        df_orcamentos['nome_cc_pai'] = df_orcamentos['centro_de_custo_pai'].apply(lambda x: cc_pai_id_to_name[x])
        df_orcamentos['nome_cc_pai'] = df_orcamentos['nome_cc_pai'].astype(str)
        total_orcado = df_orcamentos.groupby('nome_cc_pai')['valor_usado'].sum().to_dict()
       
        # Extraindo o nome do produto de 'produto_detalhes'
        df["produto"] = df["produto_detalhes"].apply(lambda x: x["nome"])
        df["centro_custo_pai"] = df["centro_custo_pai_detalhes"].apply(lambda x: x["nome"])
        df["quantidade"] = df["quantidade"].astype(float)
        df['projetado_cc_pai'] = df['centro_custo_pai'].map(total_orcado)
        df['projetado'] = df['projetado_cc_pai'] / df['quantidade']

        quantidade = df.groupby("produto")["quantidade"].sum()
        quantidade_dict = df.groupby("produto")["quantidade"].sum().to_dict()

        ccPai = df.groupby("produto")["projetado"].sum().to_dict()

        df["centro_custo_pai"] = df["centro_custo_pai_detalhes"].apply(lambda x: x["id"])
         # Para cada centro de custo pai, obter os centros de custo associados
        centro_custo_realizado = {}
        for cc_pai_id in df['centro_custo_pai'].unique():
            centros_custo = CentroCusto.objects.filter(cc_pai_id=cc_pai_id).values_list('codigo', flat=True)
            centros_custo_list = list(centros_custo)
            #print(f"Centros de custo para cc_pai_id {cc_pai_id}: {centros_custo_list}")
            # Chamar o método calculos_realizado com a lista de centros de custo
            factory = RequestFactory()
            data = request.data.copy()
             # Verifica se o cc_pai_id é 57 e ajusta as filiais
            
            # Verifica se o cc_pai_id é 57 e ajusta as filiais
            if cc_pai_id == 59:
                data['filiais'] = [3]  # Apenas filial 3
                #print(f"Filiais ajustadas para cc_pai_id {cc_pai_id}: {data['filiais']}")
            else:
                data['filiais'] = [0, 1, 2, 3, 4, 5, 6, 7, 8]  # Todas as filiais
                #print(f"Filiais ajustadas para cc_pai_id {cc_pai_id}: {data['filiais']}")

            data['ano'] = ano  # Ano recebido na requisição
            data['meses'] = [periodo] if isinstance(periodo, int) else periodo
            data['ccs'] = centros_custo_list  # Adiciona a lista de centros de custo

            new_request = factory.post('http://172.50.10.79:8008/realizado/realizado/', data=data, content_type='application/json')
            response = calculos_realizado(new_request)

            if response.status_code == 200:
                import json
                realizado_data = json.loads(response.content)  # Converte o conteúdo do JsonResponse para um dicionário
                centro_custo_realizado[cc_pai_id] = realizado_data.get('total_real', 0)
            else:
                centro_custo_realizado[cc_pai_id] = 0

        fabricas_metodos = {
            '05 - Fábrica de Calcário': '/calcario/indicadores/',
            '08 - F08 - UP ATM':'/calcario/indicadores_atm/',
            '04 - Fábrica de Cal': '/cal/indicadores/',
            '06 - Fábrica de Argamassa': '/argamassa/indicadores/',
            '03 - Fábrica de Calcinação': '/cal/indicadores_calcinacao/',
            '07 - Fábrica de Fertilizantes': '/fertilizante/indicadores/',
            '02 - Britagem': '/britagem/indicadores_britagem/',
            '01 - Mineração': '/britagem/indicadores_mineracao/',
        }      

         # Adicionar os valores realizados ao DataFrame
        df['realizado_cc_pai'] = df['centro_custo_pai'].map(centro_custo_realizado)
        #print('df',df['realizado_cc_pai'])
        df['producao'] = None

        for fabrica, endpoint in fabricas_metodos.items():
            # Filtra o DataFrame para a fábrica atual
            df_fabrica = df[df['fabrica'] == fabrica]

            if not df_fabrica.empty:
                # Prepara os dados para a requisição
                data = request.data.copy()
                data['fabrica'] = fabrica  # Adiciona o nome da fábrica aos dados

                # Faz a requisição ao endpoint correspondente
                url = f'http://172.50.10.79:8008{endpoint}'
                response = requests.post(url, json=data)  # Usa requests para fazer a requisição
                #print(request.data)
                #print(response.text)
                if response.status_code == 200:
                    fabricado_data = response.json()  # Converte a resposta para um dicionário
                    total_fabricado = fabricado_data.get('total', 0)

                    # Atualiza a coluna 'fabricado' no DataFrame
                    df.loc[df['fabrica'] == fabrica, 'producao'] = total_fabricado
                else:
                    # Em caso de erro, define o valor como 0
                    df.loc[df['fabrica'] == fabrica, 'producao'] = 0

        #df['realizado'] = df['realizado_cc_pai'] / df['producao']
        df['realizado'] = df.apply(
            lambda row: row['realizado_cc_pai'] / row['producao'] if row['producao'] and row['realizado_cc_pai'] else 0,
        axis=1
    )
       
        df['diferenca'] = df['projetado'] - df['realizado']
        
        df_grouped = df.groupby('centro_custo_pai')

        # df_aggregated["produto"] = df_aggregated["produto_detalhes"].apply(lambda x: x["nome"])
        # df_aggregated["centro_custo_pai"] = df_aggregated["centro_custo_pai_detalhes"].apply(lambda x: x["nome"])

        df_aggregated = df_grouped.agg({
            'id': 'first',
            'produto_detalhes': 'first',
            'centro_custo_pai_detalhes': 'first',
            'fabrica': 'first',
            'periodo': 'first',
            'ano': 'first',
            'quantidade': 'sum',
            'produto': 'first',
            'producao': 'first',
            'projetado_cc_pai': 'first',
            'realizado_cc_pai': 'first',
        }).reset_index()

        # Calcular a coluna 'projetado' no DataFrame agregado
        df_aggregated['projetado'] = df_aggregated['projetado_cc_pai'] / df_aggregated['quantidade']
        df_aggregated['realizado'] = df_aggregated.apply(
            lambda row: row['realizado_cc_pai'] / row['producao'] if row['producao'] and row['realizado_cc_pai'] else 0,
        axis=1
    )
        df_aggregated['diferenca'] = df_aggregated['projetado'] - df_aggregated['realizado']
        df_aggregated['percentual'] = 1 - (df_aggregated['realizado'] / df_aggregated['projetado'])
        #print('llll',df_aggregated)
        #print('df',df)
        response_data = {
            "quantidade": quantidade_dict,
            "total_orcado": total_orcado,
            'resultados': df_aggregated.to_dict(orient='records'),
            'ccPai': ccPai
        }


        return JsonResponse(response_data, safe=False)
    
    # def calculosRealizados(self,request):
    #     ano = request.data.get('ano')