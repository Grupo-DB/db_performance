from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    NormaViewSet, PlanoAcaoViewSet, PublicacaoViewSet, RequisitoViewSet, ResponsaveisView, VerificacaoViewSet,
)

router = DefaultRouter()
router.register(r'normas', NormaViewSet, basename='conformidade-norma')
router.register(r'requisitos', RequisitoViewSet, basename='conformidade-requisito')
router.register(r'verificacoes', VerificacaoViewSet, basename='conformidade-verificacao')
router.register(r'planos-acao', PlanoAcaoViewSet, basename='conformidade-plano')
router.register(r'novidades', PublicacaoViewSet, basename='conformidade-novidade')

urlpatterns = [
    path('responsaveis/', ResponsaveisView.as_view(), name='conformidade-responsaveis'),
] + router.urls
