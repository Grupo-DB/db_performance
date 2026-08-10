from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BoletimSemanalViewSet, IndicadorBoletimViewSet, ResultadoBoletimViewSet

router = DefaultRouter()
router.register(r'indicador', IndicadorBoletimViewSet, basename='IndicadorBoletim')
router.register(r'resultado', ResultadoBoletimViewSet, basename='ResultadoBoletim')
router.register(r'boletim', BoletimSemanalViewSet, basename='BoletimSemanal')

urlpatterns = [
    path('', include(router.urls)),
]
