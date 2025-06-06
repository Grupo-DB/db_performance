from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework.routers import DefaultRouter
from .views import AnaliseViewSet

router = DefaultRouter()

router.register(r'analise', AnaliseViewSet, basename='Analise')

urlpatterns = [
    path('', include(router.urls)),
] 
