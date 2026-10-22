from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AcompanhamentoViewSet, AutoavaliacaoPublicaView, AvaliacaoJovemAprendizViewSet, ConviteAutoavaliacaoViewSet, EtapaViewSet

router = DefaultRouter()
router.register(r'acompanhamentos', AcompanhamentoViewSet, basename='AprendizAcompanhamento')
router.register(r'etapas', EtapaViewSet, basename='AprendizEtapa')
router.register(r'jovem-aprendiz/convites', ConviteAutoavaliacaoViewSet, basename='JovemAprendizConvite')
router.register(r'jovem-aprendiz', AvaliacaoJovemAprendizViewSet, basename='JovemAprendizAvaliacao')

urlpatterns = [
    # Público (sem login): o jovem responde pelo link do convite.
    path('publico/autoavaliacao/<str:token>/', AutoavaliacaoPublicaView.as_view()),
    path('', include(router.urls)),
]
