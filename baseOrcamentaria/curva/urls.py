from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . views import calculos_curva,meus_calculos_gp_curva,meus_calculos_cc_curva
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

urlpatterns = [ 
    path('', include(router.urls)),
    path('calculos_realizados_curva/',calculos_curva, name='CalculosRealizadosCurva'),
    path('meus_calculos_realizados_curva/',meus_calculos_gp_curva, name='MeusCalculosCurva'),
    path('meus_calculos_cc_curva/',meus_calculos_cc_curva, name='MeusCalculosCCCurva'),
]