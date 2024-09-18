from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . import views
from .views import calculos_rebritagem,calculos_rebritagem_paradas
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'home', calculos_rebritagem, basename='Rebritagem')


urlpatterns = [
    path('calcular_rebritagem/', calculos_rebritagem, name='rebritagem'),
    path('calcular_rebritagem_paradas/',calculos_rebritagem_paradas,name= 'rebritagem_paradas')
]