from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AcompanhamentoViewSet, EtapaViewSet

router = DefaultRouter()
router.register(r'acompanhamentos', AcompanhamentoViewSet, basename='AprendizAcompanhamento')
router.register(r'etapas', EtapaViewSet, basename='AprendizEtapa')

urlpatterns = [path('', include(router.urls))]
