from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework.routers import DefaultRouter
from .views import TipoAmostraViewSet, ProdutoViewSet, AmostraViewSet, AmostraImagemViewSet

router = DefaultRouter()

router.register(r'tipoAmostra', TipoAmostraViewSet, basename='TipoAmostra')
router.register(r'produto', ProdutoViewSet,basename='Produto')
router.register(r'amostra', AmostraViewSet,basename='Amostra')
router.register(r'amostraImagem', AmostraImagemViewSet, basename='AmostraImagem')

urlpatterns = [
    path('', include(router.urls)),
]