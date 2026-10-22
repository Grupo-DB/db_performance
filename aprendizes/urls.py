from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AcompanhamentoViewSet, AvaliacaoJovemAprendizViewSet, EtapaViewSet

router = DefaultRouter()
router.register(r'acompanhamentos', AcompanhamentoViewSet, basename='AprendizAcompanhamento')
router.register(r'etapas', EtapaViewSet, basename='AprendizEtapa')
router.register(r'jovem-aprendiz', AvaliacaoJovemAprendizViewSet, basename='JovemAprendizAvaliacao')

urlpatterns = [path('', include(router.urls))]
