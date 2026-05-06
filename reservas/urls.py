from rest_framework.routers import DefaultRouter
from .views import ObjetoViewSet, ReservaViewSet

router = DefaultRouter()
router.register(r'objetos', ObjetoViewSet, basename='objeto')
router.register(r'reservas', ReservaViewSet, basename='reserva')

urlpatterns = router.urls