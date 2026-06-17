from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    FabricanteViewSet, EquipamentoViewSet, VeiculoViewSet, SecaoViewSet, ProdutoViewSet,
    PedidoViewSet, PedidoNotificacaoViewSet
)

router = DefaultRouter()
router.register(r'fabricantes', FabricanteViewSet, basename='fabricante')
router.register(r'equipamentos', EquipamentoViewSet, basename='equipamento')
router.register(r'veiculos', VeiculoViewSet, basename='veiculo')
router.register(r'secoes', SecaoViewSet, basename='secao')
router.register(r'produtos', ProdutoViewSet, basename='produto')
router.register(r'pedidos', PedidoViewSet, basename='pedido')
router.register(r'notificacoes', PedidoNotificacaoViewSet, basename='notificacao')

urlpatterns = [
    path('', include(router.urls)),
]
