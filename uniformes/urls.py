from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CampanhaViewSet, ItemPedidoViewSet, PecaViewSet, PedidoViewSet

router = DefaultRouter()
router.register(r'campanhas', CampanhaViewSet, basename='UniformeCampanha')
router.register(r'pecas', PecaViewSet, basename='UniformePeca')
router.register(r'pedidos', PedidoViewSet, basename='UniformePedido')
router.register(r'itens', ItemPedidoViewSet, basename='UniformeItem')

urlpatterns = [path('', include(router.urls))]
