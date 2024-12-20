from django.shortcuts import render

# Create your views here.nnbmbnmbmb
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
from baseOrcamentaria.orcamento.models import RaizAnalitica,CentroCustoPai,CentroCusto,RaizSintetica,ContaContabil,GrupoItens,OrcamentoBase
from baseOrcamentaria.orcamento.serializers import RaizAnaliticaSerializer,CentroCustoPaiSerializer,CentroCustoSerializer,RaizSinteticaSerializer,ContaContabilSerializer,GrupoItensSerializer,OrcamentoBaseSerializer
import pandas as pd
import locale
from collections import defaultdict

locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')  # br

class RaizAnaliticaViewSet(viewsets.ModelViewSet):
    queryset = RaizAnalitica.objects.all()
    serializer_class = RaizAnaliticaSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
class CentroCustoPaiViewSet(viewsets.ModelViewSet):
    queryset = CentroCustoPai.objects.all() 
    serializer_class = CentroCustoPaiSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
class CentroCustoViewSet(viewsets.ModelViewSet):
    queryset = CentroCusto.objects.all()
    serializer_class = CentroCustoSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='byCcPai')
    def byCcPai(self, request):
        cc_pai_id = request.query_params.get('cc_pai_id')
        centros_custo = CentroCusto.objects.filter(cc_pai_id=cc_pai_id)
        serializer = self.get_serializer(centros_custo, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
     
class RaizSinteticaViewSet(viewsets.ModelViewSet):
    queryset = RaizSintetica.objects.all() 
    serializer_class = RaizSinteticaSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='byCc')
    def byCc(self, request):
        cc_id = request.query_params.get('centro_custo_id') 
        
        if not cc_id:
            return Response(
                {"error": "O parâmetro 'gestor_id' é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            raiz_sintetica = RaizSintetica.objects.filter(centro_custo_id=cc_id)
            serializer = self.get_serializer(raiz_sintetica, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": f"Erro ao buscar registros: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
     
    
class GrupoItensViewSet(viewsets.ModelViewSet):
    queryset = GrupoItens.objects.all()
    serializer_class = GrupoItensSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

class ContaContabilViewSet(viewsets.ModelViewSet):
    queryset = ContaContabil.objects.all()
    serializer_class = ContaContabilSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='byOb')
    def byOb(self, request):
        n4_conta = request.query_params.get('nivel_analitico_conta')
        conta_contabil = ContaContabil.objects.filter(nivel_analitico_conta=n4_conta)
        serializer = self.get_serializer(conta_contabil, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OrcamentoBaseViewSet(viewsets.ModelViewSet):
    queryset = OrcamentoBase.objects.all()
    serializer_class = OrcamentoBaseSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        data = request.data

        try:
            # Validação básica para periodicidade
            periodicidade = data.get("periodicidade")
            if not periodicidade:
                return Response(
                    {"error": "O campo 'periodicidade' é obrigatório."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Criação dos orçamentos com base na periodicidade
            orcamentos = self._criar_orcamentos(data)

            # Serializar os objetos criados para retorno
            serializer = self.get_serializer(orcamentos, many=True)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def _criar_orcamentos(self, data):
        """
        Lógica para criar os orçamentos com base na periodicidade.
        """
        periodicidade = data.get("periodicidade")  # anual ou mensal
        mensal_tipo = data.get("mensal_tipo")  # específico ou recorrente
        mes_especifico = data.get("mes_especifico")  # 1-12
        meses_recorrentes = data.get("meses_recorrentes")  # lista de meses

        # Obter as instâncias relacionadas
        centro_de_custo_pai_id = data.get("centro_de_custo_pai")
        centro_custo_nome_id = data.get("centro_custo_nome")
        raiz_analitica_id = data.get("raiz_analitica")

        try:
            # Buscar as instâncias relacionadas no banco de dados
            centro_de_custo_pai = CentroCustoPai.objects.get(id=centro_de_custo_pai_id)
            centro_custo_nome = CentroCusto.objects.get(id=centro_custo_nome_id)
            raiz_analitica = RaizAnalitica.objects.get(id=raiz_analitica_id)
        except CentroCustoPai.DoesNotExist:
            raise ValueError(f"Centro de Custo Pai com ID {centro_de_custo_pai_id} não encontrado.")
        except CentroCusto.DoesNotExist:
            raise ValueError(f"Centro de Custo com ID {centro_custo_nome_id} não encontrado.")
        except RaizAnalitica.DoesNotExist:
            raise ValueError(f"Raiz Analítica com ID {raiz_analitica_id} não encontrada.")

        # Criar uma cópia do dicionário para evitar alterar o original
        base_data = data.copy()

        # Substituir os IDs pelas instâncias correspondentes
        base_data["centro_de_custo_pai"] = centro_de_custo_pai
        base_data["centro_custo_nome"] = centro_custo_nome
        base_data["raiz_analitica"] = raiz_analitica

        # Remover o campo 'mes_especifico' da base, pois será tratado individualmente
        base_data.pop("mes_especifico", None)

        orcamentos = []

        if periodicidade == "anual":
            valor_anual = data.get('valor', 0)  # Supondo que 'valor' seja o campo com o valor total
            valor_mensal = valor_anual / 12  # Divide o valor por 12
            for mes in range(1, 13):
                orcamento_data = {
                    **base_data,  # Copia os dados base
                    'mes_especifico': mes,  # Adiciona o mês específico
                    'valor': valor_mensal  # Sobrescreve o valor mensal
                }
                orcamento = OrcamentoBase(**orcamento_data)  # Cria o objeto com os dados ajustados
                orcamentos.append(orcamento)

        elif periodicidade == "mensal" and mensal_tipo == "especifico":
            if mes_especifico:
                orcamento = OrcamentoBase(
                    **base_data,
                    mes_especifico=mes_especifico
                )
                orcamentos.append(orcamento)

        elif periodicidade == "mensal" and mensal_tipo == "recorrente":
            if isinstance(meses_recorrentes, list):
                # Certifique-se de que todos os valores são inteiros
                meses_recorrentes = [int(mes) for mes in meses_recorrentes]
                for mes in meses_recorrentes:
                    orcamento = OrcamentoBase(
                        **base_data,
                        mes_especifico=mes
                    )
                    orcamentos.append(orcamento)
            else:
                raise ValueError("Meses recorrentes devem ser uma lista de inteiros.")

        # Salvar todos os objetos no banco
        OrcamentoBase.objects.bulk_create(orcamentos)
        return orcamentos
    

    @action(detail=False, methods=['get'], url_path='byCcPai')
    def byCcPai(self, request):
        centro_de_custo_pai_id = request.query_params.get('centro_de_custo_pai_id')
        ano = request.query_params.get('ano')
        mes = request.query_params.get('mes')
        filial = request.query_params.get('filial')

        # Filtro inicial obrigatório
        filters = Q(centro_de_custo_pai_id=centro_de_custo_pai_id)

        # Adiciona filtros opcionais
        if ano:
            filters &= Q(ano=ano)
        if mes:
            filters &= Q(mes_especifico=mes)
        if filial:
            filiais = filial.split(",")  # Divide a string em uma lista de filiais
            filters &= Q(filial__in=filiais)   

        # Consulta no banco
        orcamentos_base = OrcamentoBase.objects.filter(filters)
        serializer = self.get_serializer(orcamentos_base, many=True)
        serialized_data = serializer.data

        # Converte dados para DataFrame
        df = pd.DataFrame(serialized_data)

        # Variáveis para totais e distribuições
        total = 0
        total_mensal = 0
        total_anual = 0

        # Dicionários para armazenar totais e detalhamento das linhas
        mensal_por_mes = defaultdict(float)
        anual_por_mes = defaultdict(float)
        conta_por_mes = defaultdict(float)
        conta_por_ano = defaultdict(float)
        raiz_por_mes = defaultdict(float)
        raiz_por_ano = defaultdict(float)
        tipo_por_mes = defaultdict(float)
        tipo_por_ano = defaultdict(float)

        # Dicionários para detalhamento das linhas
        detalhamento_mensal = defaultdict(list)
        detalhamento_anual = defaultdict(list)

        # Verifica se as colunas necessárias existem no DataFrame
        if 'valor' in df.columns and 'valor_real' in df.columns:
            df['valor'] = pd.to_numeric(df['valor'], errors='coerce').fillna(0)
            df['valor_real'] = pd.to_numeric(df['valor_real'], errors='coerce').fillna(0)

            for _, row in df.iterrows():
                mes = row.get('mes_especifico')
                conta = row.get('raiz_contabil_grupo_desc')
                raiz = row.get('raiz_analitica_desc')
                tipo = row.get('tipo_custo')
                periodicidade = row.get('periodicidade')
                valor_real = row['valor_real']
                valor = row['valor']

                valor_utilizado = valor_real if valor_real > 0 else valor

                total += valor_utilizado
                if periodicidade == 'mensal':
                    total_mensal += valor_utilizado
                    mensal_por_mes[mes] += valor_utilizado
                    conta_por_mes[conta] += valor_utilizado
                    raiz_por_mes[raiz] += valor_utilizado
                    tipo_por_mes[tipo] += valor_utilizado
                    detalhamento_mensal[mes].append(row.to_dict())
                elif periodicidade == 'anual':
                    total_anual += valor_utilizado
                    anual_por_mes[mes] += valor_utilizado
                    conta_por_ano[conta] += valor_utilizado
                    raiz_por_ano[raiz] += valor_utilizado
                    tipo_por_ano[tipo] += valor_utilizado
                    detalhamento_anual[mes].append(row.to_dict())

       
        total = locale.format_string("%.0f",total,grouping=True) if total > 0 else 0
        total_mensal = locale.format_string("%.0f",total_mensal,grouping=True) if total_mensal > 0 else 0
        total_anual = locale.format_string("%.0f",total_anual,grouping=True) if total_anual > 0 else 0

        # Função para formatar valores com locale
        def format_locale(value):
            return locale.format_string("%.0f",value, grouping=True) 

       
        mensal_por_mes_formatted = {mes: format_locale(valor) for mes, valor in mensal_por_mes.items()}
        anual_por_mes_formatted = {mes: format_locale(valor) for mes, valor in anual_por_mes.items()}

        conta_por_mes_formatted = {conta: format_locale(valor) for conta, valor in conta_por_mes.items()}
        conta_por_ano_formatted = {conta: format_locale(valor) for conta, valor in conta_por_ano.items()}

        raiz_por_mes_formatted = {raiz: format_locale(valor) for raiz, valor in raiz_por_mes.items()}
        raiz_por_ano_formatted = {raiz: format_locale(valor) for raiz, valor in raiz_por_ano.items()}
        
        tipo_por_mes_formatted = {tipo: format_locale(valor) for tipo, valor in tipo_por_mes.items()}
        tipo_por_ano_formatted = {tipo: format_locale(valor) for tipo, valor in tipo_por_ano.items()}

        response_data = {
            "orcamentosBase": serialized_data,
            "total": total,
            'total_mensal': total_mensal,
            'total_anual': total_anual,
            "mensal_por_mes": mensal_por_mes_formatted,
            "anual_por_mes": anual_por_mes_formatted,
            "conta_por_mes": conta_por_mes_formatted,
            'conta_por_ano': conta_por_ano_formatted,
            "raiz_por_mes": raiz_por_mes_formatted,
            "raiz_por_ano": raiz_por_ano_formatted,
            "tipo_por_mes": tipo_por_mes_formatted,
            "tipo_por_ano": tipo_por_ano_formatted,
            'detalhamento_mensal': detalhamento_mensal,
            'detalhamento_anual': detalhamento_anual,
        }      


        return Response(response_data, status=status.HTTP_200_OK)

@api_view(['POST'])
def AplicarPorcentagem(request):
    try:
        # Obter a porcentagem e meses do corpo da requisição
        porcentagem = request.data.get('porcentagem')
        meses_recorrentes = [4, 5, 6, 7, 8, 9, 10, 11, 12]
        raiz_analitica_cod = '011000001'
        if not porcentagem or not meses_recorrentes:
            return Response(
                {"error": "A porcentagem e os meses recorrentes são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Garantir que meses_recorrentes é uma lista de inteiros
        if isinstance(meses_recorrentes, str):
            meses_recorrentes = [int(mes.strip()) for mes in meses_recorrentes.split(',')]

        # Obter os registros da tabela OrcamentoBase onde o mes_especifico está entre 4 e 12
        orcamentos = OrcamentoBase.objects.filter(mes_especifico__in=meses_recorrentes, raiz_analitica_cod__endswith=raiz_analitica_cod)
        porcentagem_decimal = Decimal(porcentagem)

        # Atualizar o campo valor com a porcentagem
        for orcamento in orcamentos:

            if orcamento.valor_ajustado is None:
                orcamento.valor_ajustado = Decimal(0.00)

            orcamento.valor_ajustado = orcamento.valor * (porcentagem_decimal /Decimal(100))
            orcamento.valor_real = orcamento.valor + orcamento.valor_ajustado
            orcamento.save()

        return Response(
            {"message": f"Porcentagem de {porcentagem}% aplicada com sucesso."},
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        return Response(
            {"error": f"Ocorreu um erro: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )