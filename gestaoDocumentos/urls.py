from rest_framework.routers import DefaultRouter
from gestaoDocumentos.views import (
    DiretorioViewSet,
    ContratoViewSet,
    ProcessoInternoViewSet,
    AcaoViewSet,
    AlvaraViewSet,
    ProcuracaoViewSet,
    PatrimonialViewSet,
    AtasViewSet,
    SocietarioViewSet,
    SeguroViewSet,
    ProcessoExternoViewSet,
    VeiculoViewSet
)

router = DefaultRouter()
router.register(r'diretorios', DiretorioViewSet, basename='diretorio')
router.register(r'contratos', ContratoViewSet, basename='contrato')
router.register(r'processos-internos', ProcessoInternoViewSet, basename='processo-interno')
router.register(r'acoes', AcaoViewSet, basename='acao')
router.register(r'alvaras', AlvaraViewSet, basename='alvara')
router.register(r'procuracoes', ProcuracaoViewSet, basename='procuracao')
router.register(r'patrimoniais', PatrimonialViewSet, basename='patrimonial')
router.register(r'atas', AtasViewSet, basename='atas')
router.register(r'societarios', SocietarioViewSet, basename='societario')
router.register(r'seguros', SeguroViewSet, basename='seguro')
router.register(r'processos-externos', ProcessoExternoViewSet, basename='processo-externo')
router.register(r'veiculos', VeiculoViewSet, basename='veiculo')

urlpatterns = router.urls