from rest_framework.routers import DefaultRouter
from gestaoDocumentos.views import (
    DiretorioViewSet,
    ContratoViewSet,
    ProcessoViewSet,
    AcaoViewSet,
    AlvaraViewSet,
    ProcuracaoViewSet,
    PatrimonialViewSet,
)

router = DefaultRouter()
router.register(r'diretorios', DiretorioViewSet, basename='diretorio')
router.register(r'contratos', ContratoViewSet, basename='contrato')
router.register(r'processos', ProcessoViewSet, basename='processo')
router.register(r'acoes', AcaoViewSet, basename='acao')
router.register(r'alvaras', AlvaraViewSet, basename='alvara')
router.register(r'procuracoes', ProcuracaoViewSet, basename='procuracao')
router.register(r'patrimoniais', PatrimonialViewSet, basename='patrimonial')

urlpatterns = router.urls