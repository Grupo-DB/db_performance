from rest_framework.routers import DefaultRouter

from .views import EventoViewSet, ParticipanteViewSet, PremioViewSet, SorteioViewSet

router = DefaultRouter()
router.register(r'eventos', EventoViewSet, basename='sipat-evento')
router.register(r'participantes', ParticipanteViewSet, basename='sipat-participante')
router.register(r'premios', PremioViewSet, basename='sipat-premio')
router.register(r'sorteios', SorteioViewSet, basename='sipat-sorteio')

urlpatterns = router.urls
