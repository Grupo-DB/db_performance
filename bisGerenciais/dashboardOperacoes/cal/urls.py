from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . import views
from .views import calculos_cal,calculos_cal_produtos,calculos_cal_equipamentos,calculos_cal_graficos
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'cal', calculos_cal, basename='Cal')


urlpatterns = [
    path('calcular_cal/', calculos_cal, name='cal'),
    path('calcular_cal_produtos/', calculos_cal_produtos,name='calProdutos'),
    path( 'calcular_cal_equipamentos/',calculos_cal_equipamentos,name='calEquipamentos'),
    path( 'calcular_cal_graficos/',calculos_cal_graficos,name='calGraficos')
]