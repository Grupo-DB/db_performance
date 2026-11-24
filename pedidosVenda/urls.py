from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CarteiraView, PacoteOfflineView, ErpViewSet, FolhaCargaViewSet, EuView, FotoProdutoViewSet, NotificacaoViewSet, PainelCargasView, PedidoVendaViewSet, VendedorPerfilViewSet

router = DefaultRouter()
router.register(r'pedidos', PedidoVendaViewSet, basename='pedido-venda')
router.register(r'vendedores', VendedorPerfilViewSet, basename='vendedor-perfil')
router.register(r'fotos', FotoProdutoViewSet, basename='foto-produto')
router.register(r'erp', ErpViewSet, basename='pedido-venda-erp')
router.register(r'folhas-carga', FolhaCargaViewSet, basename='folha-carga')
router.register(r'notificacoes', NotificacaoViewSet, basename='pedido-venda-notificacao')

urlpatterns = [
    path('eu/', EuView.as_view(), name='pedido-venda-eu'),
    path('cargas/', PainelCargasView.as_view(), name='pedido-venda-cargas'),
    path('carteira/', CarteiraView.as_view(), name='pedido-venda-carteira'),
    path('offline/', PacoteOfflineView.as_view(), name='pedido-venda-offline'),
] + router.urls
