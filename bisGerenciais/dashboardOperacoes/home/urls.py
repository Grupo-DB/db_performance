from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . import views
from .views import calculos_calcario
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'home', calculos_calcario, basename='Calcario')


urlpatterns = [
    path('calcular_calcario/', calculos_calcario, name='cal'),
]