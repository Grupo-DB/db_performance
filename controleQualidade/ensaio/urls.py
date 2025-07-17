from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from .views import TipoEnsaioViewSet, EnsaioViewSet, VariavelViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register(r'tipos_ensaio', TipoEnsaioViewSet, basename='TipoEnsaio'),
router.register(r'ensaio', EnsaioViewSet, basename='Ensaio'),
router.register(r'variavel', VariavelViewSet, basename='Variavel'),

urlpatterns = [
    path('', include(router.urls)),
]