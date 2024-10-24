from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . import views
from .views import calculos_calcario,calculos_graficos_calcario,calculos_equipamentos_detalhes,calculos_calcario_graficos_carregamento
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'home', calculos_calcario, basename='Calcario')
urlpatterns = [
    path('calcular_calcario/', calculos_calcario, name='calcario'),
    path('calcular_calcario_graficos/', calculos_graficos_calcario, name='calcario_graficos'),
    path('calcular_calcario_carregamento_graficos/', calculos_calcario_graficos_carregamento, name='calcarioGraficosCarregamento'),
    path('calcular_equipamentos_detalhes/',calculos_equipamentos_detalhes,name='EquipamentosDetalhes')
]