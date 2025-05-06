from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from .views import calculos_realizado_ppr,calculos_realizado_matriz
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

urlpatterns = [
    path('',include(router.urls)),
    path('realizado_ppr/',calculos_realizado_ppr, name='calculos_realizado_ppr'),
    path('realizado_matriz/',calculos_realizado_matriz, name='calculos_realizado_matriz'),
]