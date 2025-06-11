from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework.routers import DefaultRouter
from .views import AnaliseViewSet, AnaliseCalculoViewSet, AnaliseEnsaioViewSet

router = DefaultRouter()

router.register(r'analise', AnaliseViewSet, basename='Analise')
router.register(r'analiseEnsaio', AnaliseEnsaioViewSet, basename='AnaliseEnsaio')
router.register(r'analiseCalculo', AnaliseCalculoViewSet, basename='AnaliseCalculo')

urlpatterns = [
    path('', include(router.urls)),
] 
