from rest_framework.routers import DefaultRouter
from .views import RegiaoViewSet, RepresentanteViewSet, MetaViewSet, ComissaoViewSet, calculos_comissoes
from django.urls import path

router = DefaultRouter()
router.register(r'regiao', RegiaoViewSet, basename='regiao')
router.register(r'representante', RepresentanteViewSet, basename='representante')
router.register(r'meta', MetaViewSet, basename='meta')
router.register(r'comissao', ComissaoViewSet, basename='comissao')  

urlpatterns = [
    path('calculos_comissoes/', calculos_comissoes, name='calculos_comissoes'),
] + router.urls