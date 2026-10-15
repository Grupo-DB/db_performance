from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ConfiguracaoMonitorView, ExecucoesMonitorView, NormaViewSet, OrgaoMonitorViewSet, PalavraChaveViewSet,
    PlanoAcaoViewSet, PublicacaoViewSet, RequisitoViewSet, ResponsaveisView, TestarPalavrasView, VerificacaoViewSet,
    TerceiroViewSet, DocumentoTerceiroViewSet, AvisosView, AvisosTesteView, AvisosDestinatariosView, UnidadesView,
)

router = DefaultRouter()
router.register(r'normas', NormaViewSet, basename='conformidade-norma')
router.register(r'requisitos', RequisitoViewSet, basename='conformidade-requisito')
router.register(r'verificacoes', VerificacaoViewSet, basename='conformidade-verificacao')
router.register(r'planos-acao', PlanoAcaoViewSet, basename='conformidade-plano')
router.register(r'terceiros', TerceiroViewSet, basename='conformidade-terceiro')
router.register(r'documentos-terceiros', DocumentoTerceiroViewSet, basename='conformidade-documento-terceiro')
router.register(r'novidades', PublicacaoViewSet, basename='conformidade-novidade')
router.register(r'monitor/palavras', PalavraChaveViewSet, basename='conformidade-monitor-palavra')
router.register(r'monitor/orgaos', OrgaoMonitorViewSet, basename='conformidade-monitor-orgao')

urlpatterns = [
    path('avisos/', AvisosView.as_view(), name='conformidade-avisos'),
    path('avisos/testar/', AvisosTesteView.as_view(), name='conformidade-avisos-testar'),
    path('avisos/destinatarios/', AvisosDestinatariosView.as_view(), name='conformidade-avisos-destinatarios'),
    path('unidades/', UnidadesView.as_view(), name='conformidade-unidades'),
    path('responsaveis/', ResponsaveisView.as_view(), name='conformidade-responsaveis'),
    path('monitor/configuracao/', ConfiguracaoMonitorView.as_view(), name='conformidade-monitor-configuracao'),
    path('monitor/execucoes/', ExecucoesMonitorView.as_view(), name='conformidade-monitor-execucoes'),
    path('monitor/testar/', TestarPalavrasView.as_view(), name='conformidade-monitor-testar'),
] + router.urls
