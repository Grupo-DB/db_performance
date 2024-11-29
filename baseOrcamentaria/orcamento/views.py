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
#from .permissions import IsInGroup


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
            for mes in range(1, 13):
                orcamento = OrcamentoBase(
                    **base_data,  # Dados base sem `mes_especifico`
                    mes_especifico=mes
                )
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
        orcamentos = OrcamentoBase.objects.filter(mes_especifico__in=meses_recorrentes, raiz_analitica_cod=raiz_analitica_cod)
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