from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from .views import LinhaViewSet,ProdutoViewSet
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
from rest_framework.routers import DefaultRouter


router = DefaultRouter()

router.register(r'linhas', LinhaViewSet, basename='Linha'),
router.register(r'produtos', ProdutoViewSet, basename='Produto')

urlpatterns = [
    path('', include(router.urls)),
]