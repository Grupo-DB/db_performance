from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import Fabricante, Equipamento, Veiculo, Secao, Produto, Pedido, ItemPedido, PedidoNotificacao
from .serializers import (
    FabricanteSerializer, EquipamentoSerializer, VeiculoListSerializer, VeiculoDetailSerializer,
    VeiculoCreateUpdateSerializer, SecaoSerializer, SecaoCreateUpdateSerializer,
    ProdutoListSerializer, ProdutoDetailSerializer, ProdutoCreateUpdateSerializer,
    PedidoListSerializer, PedidoDetailSerializer, PedidoCreateSerializer,
    PedidoUpdateStatusSerializer, PedidoNotificacaoSerializer
)


class FabricanteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Fabricante.objects.all()
    serializer_class = FabricanteSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nome']
    ordering_fields = ['nome', 'created_at']


class EquipamentoViewSet(viewsets.ModelViewSet):
    queryset = Equipamento.objects.all()
    serializer_class = EquipamentoSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nome']
    ordering_fields = ['nome', 'created_at']
    ordering = ['nome']


class VeiculoViewSet(viewsets.ModelViewSet):
    queryset = Veiculo.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['fabricante', 'equipamento', 'ativo']
    search_fields = ['nome', 'modelo', 'descricao']
    ordering_fields = ['nome', 'modelo', 'created_at']
    ordering = ['nome']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return VeiculoDetailSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return VeiculoCreateUpdateSerializer
        return VeiculoListSerializer


class SecaoViewSet(viewsets.ModelViewSet):
    queryset = Secao.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['veiculo', 'ativo']
    search_fields = ['nome', 'descricao']
    ordering_fields = ['nome', 'created_at']
    ordering = ['nome']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return SecaoCreateUpdateSerializer
        return SecaoSerializer


class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = Produto.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['veiculo', 'secao', 'ativo']
    search_fields = ['nome', 'descricao']
    ordering_fields = ['nome', 'preco', 'created_at']
    ordering = ['nome']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProdutoDetailSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ProdutoCreateUpdateSerializer
        return ProdutoListSerializer


class PedidoViewSet(viewsets.ModelViewSet):
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['status', 'usuario', 'created_at']
    ordering_fields = ['created_at', 'numero_referencia', 'status']
    ordering = ['-created_at']
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return PedidoCreateSerializer
        elif self.action == 'retrieve':
            return PedidoDetailSerializer
        elif self.action == 'update_status':
            return PedidoUpdateStatusSerializer
        return PedidoListSerializer

    def get_queryset(self):
        return Pedido.objects.all()

    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        pedido = self.get_object()
        serializer = PedidoUpdateStatusSerializer(pedido, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        pedido = self.get_object()
        if pedido.status == 'CANCELADO':
            return Response({'erro': 'Pedido já foi cancelado'}, status=status.HTTP_400_BAD_REQUEST)
        pedido.status = 'CANCELADO'
        pedido.save()
        return Response(PedidoDetailSerializer(pedido).data)


class PedidoNotificacaoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PedidoNotificacaoSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['lido']
    ordering = ['-created_at']

    def get_queryset(self):
        return PedidoNotificacao.objects.filter(usuario_notificado=self.request.user)

    @action(detail=False, methods=['post'])
    def marcar_como_lido(self, request):
        notificacao_ids = request.data.get('notificacao_ids', [])
        PedidoNotificacao.objects.filter(
            id__in=notificacao_ids,
            usuario_notificado=request.user
        ).update(lido=True)
        return Response({'status': 'notificacoes marcadas como lidas'})

    @action(detail=False, methods=['get'])
    def nao_lidas(self, request):
        nao_lidas = PedidoNotificacao.objects.filter(
            usuario_notificado=request.user,
            lido=False
        ).count()
        return Response({'nao_lidas': nao_lidas})

