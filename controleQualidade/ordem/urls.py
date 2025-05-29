from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from rest_framework.routers import DefaultRouter

from .views import OrdemViewSet

router = DefaultRouter()

router.register(r'ordem', OrdemViewSet, basename='Ordem')
urlpatterns = [
    path('', include(router.urls)),
]


