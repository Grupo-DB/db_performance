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

class OrcamentoBaseViewSet(viewsets.ModelViewSet):
    queryset = OrcamentoBase.objects.all
    serializer_class = OrcamentoBaseSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)  
@api_view(['GET'])
def ChoicesView(request):
        return Response({
            "periodicidade_choices": OrcamentoBase.PERIODICIDADE_CHOICES,
            "mensal_choices": OrcamentoBase.MENSAL_CHOICES,
        })