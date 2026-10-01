from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ErpViewSet, EuView, NotificacaoViewSet, PedidoVendaViewSet, VendedorPerfilViewSet

router = DefaultRouter()
router.register(r'pedidos', PedidoVendaViewSet, basename='pedido-venda')
router.register(r'vendedores', VendedorPerfilViewSet, basename='vendedor-perfil')
router.register(r'erp', ErpViewSet, basename='pedido-venda-erp')
router.register(r'notificacoes', NotificacaoViewSet, basename='pedido-venda-notificacao')

urlpatterns = [
    path('eu/', EuView.as_view(), name='pedido-venda-eu'),
] + router.urls
