from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from .views import TipoEnsaioViewSet, EnsaioViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register(r'tipos_ensaio', TipoEnsaioViewSet, basename='TipoEnsaio'),
router.register(r'ensaio', EnsaioViewSet, basename='Ensaio')

urlpatterns = [
    path('', include(router.urls)),
]