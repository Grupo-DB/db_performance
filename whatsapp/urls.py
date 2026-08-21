from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_nested.routers import NestedDefaultRouter

from .views import (
    WebhookView, FilaViewSet, ConversaViewSet, MensagemViewSet, WhatsAppNotificacaoViewSet,
    ContatoViewSet, DisparoViewSet, NumeroNegocioViewSet,
)

router = DefaultRouter()
router.register(r'filas', FilaViewSet, basename='fila')
router.register(r'conversas', ConversaViewSet, basename='conversa')
router.register(r'notificacoes', WhatsAppNotificacaoViewSet, basename='whatsapp-notificacao')
router.register(r'contatos', ContatoViewSet, basename='whatsapp-contato')
router.register(r'disparos', DisparoViewSet, basename='whatsapp-disparo')
router.register(r'numeros', NumeroNegocioViewSet, basename='whatsapp-numero')

conversas_router = NestedDefaultRouter(router, r'conversas', lookup='conversa')
conversas_router.register(r'mensagens', MensagemViewSet, basename='conversa-mensagens')

urlpatterns = [
    path('webhook/', WebhookView.as_view(), name='whatsapp-webhook'),
    path('', include(router.urls)),
    path('', include(conversas_router.urls)),
]
