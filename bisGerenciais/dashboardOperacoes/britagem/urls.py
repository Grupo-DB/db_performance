from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . import views
from .views import calculos_britagem,calculos_graficos,calculos_britagem_indicadores
from .views import calculos_minerecao_indicadores,calculos_pedras
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'home', calculos_britagem, basename='Calcario')


urlpatterns = [
    path('calcular_britagem/', calculos_britagem, name='britagem'),
    path('calcular_graficos/',calculos_graficos,name= 'graficos'),
    path('indicadores_britagem/',calculos_britagem_indicadores, name='Indicadores'),
    path('indicadores_mineracao/',calculos_minerecao_indicadores, name='IndicadoresMineracao'),
    path('calcular_pedras/',calculos_pedras, name='pedras'),
]