from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . import views
from .views import calculos_fertilizante,calculos_indicadores_realizado
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'home', calculos_fertilizante, basename='fertilizante')
urlpatterns = [
    path('calcular_fertilizante/',calculos_fertilizante,name='fertilizante'),
    path('indicadores/',calculos_indicadores_realizado, name='Indicadores')
]