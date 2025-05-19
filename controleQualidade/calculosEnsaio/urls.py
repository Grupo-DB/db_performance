from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from .views import CalculoEnsaioViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register(r'calculoEnsaio', CalculoEnsaioViewSet, basename='CalculoEnsaio'),
urlpatterns = [
    path('', include(router.urls)),
]