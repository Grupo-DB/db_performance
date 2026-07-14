from django.db.models import Q, Sum
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Aplicacao, Banco, Credor, Empresa, Resgate
from .serializers import (
    AplicacaoCreateUpdateSerializer,
    AplicacaoDetailSerializer,
    AplicacaoListSerializer,
    BancoSerializer,
    CredorSerializer,
    EmpresaSerializer,
    ResgateSerializer,
)

APLICACOES_EM_ABERTO = [
    Aplicacao.STATUS_ATIVA,
    Aplicacao.STATUS_RENOVADA,
    Aplicacao.STATUS_RESGATE_PARCIAL,
]


class CredorViewSet(viewsets.ModelViewSet):
    serializer_class = CredorSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter]
    search_fields = ['nome', 'cpf']

    def get_queryset(self):
        return Credor.objects.annotate(
            capital_total=Sum(
                'aplicacoes__valor_aplicacao',
                filter=Q(aplicacoes__status__in=APLICACOES_EM_ABERTO),
            )
        )


class EmpresaViewSet(viewsets.ModelViewSet):
    queryset = Empresa.objects.all()
    serializer_class = EmpresaSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter]
    search_fields = ['nome', 'cnpj']


class BancoViewSet(viewsets.ModelViewSet):
    queryset = Banco.objects.all()
    serializer_class = BancoSerializer
    permission_classes = [IsAuthenticated]


class AplicacaoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['empresa', 'credor', 'banco', 'status', 'ano_referencia', 'dia_vencimento', 'descendio']
    search_fields = ['numero_contrato', 'credor__nome', 'empresa__nome']

    def get_queryset(self):
        return Aplicacao.objects.select_related('credor', 'empresa', 'banco').prefetch_related('resgates')

    def get_serializer_class(self):
        if self.action == 'list':
            return AplicacaoListSerializer
        if self.action in ('create', 'update', 'partial_update'):
            return AplicacaoCreateUpdateSerializer
        return AplicacaoDetailSerializer

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        qs = self.filter_queryset(self.get_queryset()).filter(status__in=APLICACOES_EM_ABERTO)
        totais = qs.aggregate(
            capital_aplicado=Sum('valor_aplicacao'),
            juros_mensal=Sum('juros'),
            irrf_mensal=Sum('irrf'),
        )
        return Response({
            'capital_aplicado': totais['capital_aplicado'] or 0,
            'juros_mensal': totais['juros_mensal'] or 0,
            'irrf_mensal': totais['irrf_mensal'] or 0,
            'aplicacoes_ativas': qs.count(),
        })

    @action(detail=False, methods=['get'], url_path='resumo-bancos')
    def resumo_bancos(self, request):
        qs = self.filter_queryset(self.get_queryset()).filter(status__in=APLICACOES_EM_ABERTO, banco__isnull=False)
        dados = (
            qs.values('banco__id', 'banco__nome', 'dia_vencimento')
            .annotate(total_juros=Sum('juros'), total_aplicado=Sum('valor_aplicacao'))
            .order_by('banco__nome', 'dia_vencimento')
        )
        return Response(list(dados))

    @action(detail=False, methods=['get'], url_path='resumo-dirf')
    def resumo_dirf(self, request):
        qs = self.filter_queryset(self.get_queryset())
        dados = (
            qs.values('ano_referencia', 'descendio')
            .annotate(total_irrf=Sum('irrf'))
            .order_by('ano_referencia', 'descendio')
        )
        return Response(list(dados))

    @action(detail=True, methods=['get'], url_path='contrato-dados')
    def contrato_dados(self, request, pk=None):
        aplicacao = self.get_object()
        return Response(AplicacaoDetailSerializer(aplicacao).data)


class ResgateViewSet(viewsets.ModelViewSet):
    serializer_class = ResgateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['aplicacao']

    def get_queryset(self):
        return Resgate.objects.select_related('aplicacao').all()
