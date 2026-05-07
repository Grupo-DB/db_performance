from rest_framework.routers import DefaultRouter
from .views import DespesaViewSet, DocumentoAnexoViewSet

router = DefaultRouter()
router.register(r'despesas', DespesaViewSet, basename='despesa')
router.register(r'documento-anexos', DocumentoAnexoViewSet, basename='documento-anexo')

urlpatterns = router.urls

