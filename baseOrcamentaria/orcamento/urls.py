from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . import views
from .views import RaizAnaliticaViewSet,CentroCustoPaiViewSet,CentroCustoViewSet,RaizSinteticaViewSet,GrupoItensViewSet,ContaContabilViewSet,OrcamentoBaseViewSet,ChoicesView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'raizesanaliticas', RaizAnaliticaViewSet, basename='RaizAnalitica')
router.register(r'centroscustopai', CentroCustoPaiViewSet, basename='CentroCustoPai')
router.register(r'centroscusto', CentroCustoViewSet, basename='CentroCusto')
router.register(r'raizessinteticas', RaizSinteticaViewSet, basename='RaízesSintéticas')
router.register(r'grupositens', GrupoItensViewSet, basename='GruposItens')
router.register(r'contascontabeis', ContaContabilViewSet, basename='ContasContabeis')
router.register(r'orcamentosbase', OrcamentoBaseViewSet, basename='OrcamnroBase')

urlpatterns = [
    path('', include(router.urls)),
    path('choises/', ChoicesView, name='choises')
]