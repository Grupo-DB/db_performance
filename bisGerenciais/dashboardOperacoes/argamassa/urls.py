from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . import views
from .views import calculos_argamassa,calculos_argamassa_produtos,calculos_argamassa_graficos,calculos_argamassa_graficos_carregamento,calculos_argamassa_equipamentos,calculos_argamassa_produto_individual
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView
from rest_framework.routers import DefaultRouter


router = DefaultRouter()
router.register(r'argamassa',calculos_argamassa, basename='argamassa')

urlpatterns = [
    path('calcular_argamassa/', calculos_argamassa, name='argamassa'),
    path('calcular_argamassa_equipamentos/',calculos_argamassa_equipamentos,name='argamassaEquipamentos'),
    path('calcular_argamassa_produtos/', calculos_argamassa_produtos, name='argamassaProdutos'),
    path('calcular_produto_individual/',calculos_argamassa_produto_individual, name='argamassaProdutoIndividual'),
    path('calcular_argamassa_graficos/', calculos_argamassa_graficos, name='argamassaGraficos'),
    path('calcular_argamassa_graficos_carregamento/', calculos_argamassa_graficos_carregamento, name='argamassaGraficosCarregamento'),
]