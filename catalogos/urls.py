from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    FabricanteViewSet, EquipamentoViewSet, VeiculoViewSet, SecaoViewSet, ItemViewSet,
    PedidoViewSet, PedidoNotificacaoViewSet,
    CatalogoPDFViewSet, ItemErpCatalogoViewSet,
    consultar_produtos, consultar_imagem_produto,
)

router = DefaultRouter()
router.register(r'fabricantes',       FabricanteViewSet,        basename='fabricante')
router.register(r'equipamentos',      EquipamentoViewSet,       basename='equipamento')
router.register(r'veiculos',          VeiculoViewSet,           basename='veiculo')
router.register(r'secoes',            SecaoViewSet,             basename='secao')
router.register(r'itens',             ItemViewSet,              basename='item')
router.register(r'pedidos',           PedidoViewSet,            basename='pedido')
router.register(r'notificacoes',      PedidoNotificacaoViewSet, basename='notificacao')
router.register(r'catalogos-pdf',     CatalogoPDFViewSet,       basename='catalogo-pdf')
router.register(r'erp-catalogo',      ItemErpCatalogoViewSet,   basename='erp-catalogo')

urlpatterns = [
    path('', include(router.urls)),
    path('erp/produtos/',       consultar_produtos,       name='erp-produtos'),
    path('erp/produto-imagem/', consultar_imagem_produto, name='erp-produto-imagem'),
]
