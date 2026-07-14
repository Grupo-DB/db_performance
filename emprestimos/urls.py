from rest_framework.routers import DefaultRouter

from .views import AplicacaoViewSet, BancoViewSet, CredorViewSet, EmpresaViewSet, ResgateViewSet

router = DefaultRouter()
router.register(r'credores', CredorViewSet, basename='credor')
router.register(r'empresas', EmpresaViewSet, basename='empresa')
router.register(r'bancos', BancoViewSet, basename='banco')
router.register(r'aplicacoes', AplicacaoViewSet, basename='aplicacao')
router.register(r'resgates', ResgateViewSet, basename='resgate')

urlpatterns = router.urls
