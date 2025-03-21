from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . views import calculos_realizados_grupo_itens
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

urlpatterns = [ 
    path('', include(router.urls)),
    path('calculos_realizados_grupo_itens/',calculos_realizados_grupo_itens, name='CalculosRealizadosGrupoItens')
]