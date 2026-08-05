from rest_framework.routers import DefaultRouter

from .views import (
    AreaInteresseViewSet,
    CandidatoViewSet,
    FichaEntrevistaViewSet,
    IndicadoresViewSet,
    ProcessoViewSet,
    VagaViewSet,
)

router = DefaultRouter()
router.register(r'areas', AreaInteresseViewSet, basename='area-interesse')
router.register(r'candidatos', CandidatoViewSet, basename='candidato')
router.register(r'vagas', VagaViewSet, basename='vaga')
router.register(r'processos', ProcessoViewSet, basename='processo')
router.register(r'fichas', FichaEntrevistaViewSet, basename='ficha-entrevista')
router.register(r'indicadores', IndicadoresViewSet, basename='indicador')

urlpatterns = router.urls
