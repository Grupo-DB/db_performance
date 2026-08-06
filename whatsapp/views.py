import hmac
import hashlib
import json
import logging
from datetime import date

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import graph_api
from .models import Fila, Conversa, Mensagem, MensagemAnexo, WhatsAppNotificacao
from .serializers import (
    FilaSerializer, ConversaListSerializer, ConversaDetailSerializer,
    MensagemSerializer, WhatsAppNotificacaoSerializer,
)
from .tasks import processar_webhook_whatsapp, enviar_mensagem_whatsapp, enviar_template_whatsapp

logger = logging.getLogger(__name__)


class WebhookView(APIView):
    """Endpoint público exigido pela Meta Cloud API — fora do DefaultRouter."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge', '')
        if mode == 'subscribe' and token == settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(challenge, content_type='text/plain')
        return HttpResponse(status=403)

    def post(self, request):
        assinatura = request.headers.get('X-Hub-Signature-256', '')
        if not self._assinatura_valida(request.body, assinatura):
            return HttpResponse(status=403)
        try:
            payload = json.loads(request.body.decode('utf-8'))
            processar_webhook_whatsapp.delay(payload)
        except Exception:
            logger.exception('Payload de webhook do WhatsApp inválido')
        # Sempre 200 — a Meta reenvia agressivamente em caso de erro/timeout
        return Response({'status': 'ok'})

    @staticmethod
    def _assinatura_valida(body: bytes, assinatura_header: str) -> bool:
        if not settings.WHATSAPP_APP_SECRET or not assinatura_header.startswith('sha256='):
            return False
        esperado = hmac.new(
            settings.WHATSAPP_APP_SECRET.encode('utf-8'), body, hashlib.sha256
        ).hexdigest()
        recebido = assinatura_header.split('sha256=', 1)[1]
        return hmac.compare_digest(esperado, recebido)


class FilaViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = FilaSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Fila.objects.all() if user.is_staff else Fila.objects.filter(membros=user)
        return qs.distinct()

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)


class ConversaViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        return Conversa.objects.filter(fila__membros=self.request.user).distinct()

    def get_serializer_class(self):
        if self.action == 'list':
            return ConversaListSerializer
        return ConversaDetailSerializer

    def filter_queryset(self, queryset):
        fila_id = self.request.query_params.get('fila')
        status_param = self.request.query_params.get('status')
        if fila_id:
            queryset = queryset.filter(fila_id=fila_id)
        if status_param:
            queryset = queryset.filter(status=status_param)
        return queryset

    @action(detail=True, methods=['post'])
    def assumir(self, request, pk=None):
        atualizados = Conversa.objects.filter(pk=pk, responsavel__isnull=True).update(responsavel=request.user)
        if not atualizados:
            return Response({'detail': 'Conversa já foi assumida por outro usuário.'}, status=status.HTTP_409_CONFLICT)
        return Response(ConversaDetailSerializer(self.get_object()).data)

    @action(detail=True, methods=['post'])
    def liberar(self, request, pk=None):
        conversa = self.get_object()
        conversa.responsavel = None
        conversa.save(update_fields=['responsavel'])
        return Response(ConversaDetailSerializer(conversa).data)

    @action(detail=True, methods=['post'])
    def transferir(self, request, pk=None):
        conversa = self.get_object()
        fila_id = request.data.get('fila_id')
        usuario_id = request.data.get('usuario_id')
        if fila_id:
            conversa.fila_id = fila_id
        conversa.responsavel_id = usuario_id or None
        conversa.save(update_fields=['fila', 'responsavel'])
        WhatsAppNotificacao.objects.bulk_create([
            WhatsAppNotificacao(
                conversa=conversa, usuario_notificado=membro,
                tipo='CONVERSA_TRANSFERIDA', mensagem=f"Conversa de {conversa.contato_nome or conversa.contato_telefone} transferida para sua fila",
            )
            for membro in (conversa.fila.membros.all() if conversa.fila_id else [])
        ])
        return Response(ConversaDetailSerializer(conversa).data)

    @action(detail=True, methods=['post'])
    def encerrar(self, request, pk=None):
        conversa = self.get_object()
        conversa.status = 'ENCERRADA'
        conversa.save(update_fields=['status'])
        return Response(ConversaDetailSerializer(conversa).data)

    @action(detail=True, methods=['post'])
    def reabrir(self, request, pk=None):
        conversa = self.get_object()
        conversa.status = 'ABERTA'
        conversa.save(update_fields=['status'])
        return Response(ConversaDetailSerializer(conversa).data)

    @action(detail=False, methods=['get'])
    def recebidas(self, request):
        qs = self.get_queryset().filter(responsavel=request.user)
        return Response(ConversaListSerializer(qs, many=True).data)

    @action(detail=True, methods=['post'], url_path='criar-tarefa')
    def criar_tarefa(self, request, pk=None):
        """
        Abre uma tarefa no Kanban a partir desta conversa.

        Existe para o pedido que chega pelo WhatsApp não morrer quando o
        atendimento é encerrado: o que ficou pendente vira cartão no quadro, com
        link de volta para a conversa que o originou.

        A descrição é montada aqui, e não no navegador, para pegar o histórico
        real da conversa — a tela só tem em memória o que já foi rolado.
        """
        from kanban.models import KanbanColumn, KanbanTask

        conversa = self.get_object()
        if not conversa.fila or not conversa.fila.membros.filter(pk=request.user.pk).exists():
            raise PermissionDenied('Você não pertence à fila desta conversa.')

        try:
            coluna = KanbanColumn.objects.select_related('quadro').get(pk=request.data.get('coluna_id'))
        except (KanbanColumn.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'Lista do Kanban inválida.'}, status=status.HTTP_400_BAD_REQUEST)

        # Mesma regra do KanbanTaskViewSet: só quem é dono ou membro do quadro.
        quadro = coluna.quadro
        if request.user != quadro.criado_por and not quadro.membros.filter(pk=request.user.pk).exists():
            return Response({'detail': 'Você não é membro deste quadro.'}, status=status.HTTP_403_FORBIDDEN)

        titulo = (request.data.get('titulo') or '').strip()
        if not titulo:
            titulo = f'WhatsApp — {conversa.contato_nome or conversa.contato_telefone}'

        descricao = (request.data.get('descricao') or '').strip()
        if not descricao:
            descricao = self._resumo_da_conversa(conversa)

        # Um id de usuário inexistente estouraria IntegrityError (500); aqui vira 400.
        responsavel_id = request.data.get('responsavel_id') or None
        if responsavel_id and not User.objects.filter(pk=responsavel_id).exists():
            return Response({'detail': 'Responsável inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        prazo = request.data.get('prazo') or None
        if prazo:
            try:
                prazo = date.fromisoformat(str(prazo)[:10])
            except ValueError:
                return Response({'detail': 'Prazo inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        prioridade = request.data.get('prioridade') or 'media'
        if prioridade not in dict(KanbanTask.PRIORIDADE_CHOICES):
            prioridade = 'media'

        ultima = KanbanTask.objects.filter(coluna=coluna).order_by('-ordem').values_list('ordem', flat=True).first()
        tarefa = KanbanTask.objects.create(
            coluna=coluna,
            ordem=(ultima or 0) + 1,
            dono=request.user,
            responsavel_id=responsavel_id,
            titulo=titulo[:255],
            descricao=descricao,
            prioridade=prioridade,
            prazo=prazo,
            conversa_whatsapp=conversa,
        )
        return Response({
            'id': tarefa.id,
            'titulo': tarefa.titulo,
            'quadro_id': quadro.id,
            'quadro_nome': quadro.nome,
            'coluna_id': coluna.id,
            'coluna_titulo': coluna.titulo,
        }, status=status.HTTP_201_CREATED)

    @staticmethod
    def _resumo_da_conversa(conversa, limite=15):
        """Cabeçalho de contato + as últimas mensagens, em ordem cronológica."""
        linhas = [
            f'Contato: {conversa.contato_nome or "sem nome"} — {conversa.contato_telefone}',
            f'Fila: {conversa.fila.nome if conversa.fila else "sem fila"}',
            '',
        ]
        recentes = list(conversa.mensagens.order_by('-created_at')[:limite])
        for m in reversed(recentes):
            marcador = '>' if m.direcao == 'ENTRADA' else '<'
            texto = (m.texto or '').strip() or f'[{m.get_tipo_display()}]'
            linhas.append(f'{marcador} {m.created_at:%d/%m %H:%M} {texto}')
        return '\n'.join(linhas)

    @action(detail=False, methods=['get'])
    def templates(self, request):
        """Templates aprovados na conta, para a tela oferecer só o que existe."""
        try:
            todos = graph_api.listar_templates()
        except Exception:
            logger.exception('Falha ao listar templates do WhatsApp')
            return Response(
                {'detail': 'Não foi possível consultar os templates na Meta.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        # Só APPROVED: oferecer um template em análise ou reprovado só gera erro
        # na hora do envio.
        return Response([t for t in todos if t.get('status') == 'APPROVED'])

    @action(detail=True, methods=['post'], url_path='enviar-template')
    def enviar_template(self, request, pk=None):
        """
        Envia um template aprovado para reabrir o contato.

        Diferente do envio comum, isto é permitido FORA da janela de 24h — é
        justamente para isso que o template existe. Por isso não passa pela
        checagem de janela do MensagemViewSet.
        """
        conversa = self.get_object()
        if not conversa.fila or not conversa.fila.membros.filter(pk=request.user.pk).exists():
            raise PermissionDenied('Você não pertence à fila desta conversa.')

        nome_template = (request.data.get('template') or '').strip()
        if not nome_template:
            return Response({'detail': 'Informe o template.'}, status=status.HTTP_400_BAD_REQUEST)
        idioma = (request.data.get('idioma') or 'pt_BR').strip()
        componentes = request.data.get('componentes') or None

        # O texto guardado é só o rastro para o histórico: o corpo real do
        # template mora na Meta, e pode ser alterado lá sem passar por aqui.
        mensagem = Mensagem.objects.create(
            conversa=conversa, direcao='SAIDA', tipo='TEXTO', autor=request.user,
            texto=request.data.get('previa') or f'[template: {nome_template}]',
            template_nome=nome_template, status_entrega='PENDENTE',
            payload_bruto={'template': nome_template, 'idioma': idioma, 'componentes': componentes},
        )
        conversa.ultima_mensagem_em = timezone.now()
        # `ultima_mensagem_cliente_em` NÃO é tocado de propósito: template não
        # reabre a janela de 24h — só uma resposta do cliente reabre.
        conversa.save(update_fields=['ultima_mensagem_em'])

        enviar_template_whatsapp.delay(mensagem.id, nome_template, idioma, componentes)
        return Response(MensagemSerializer(mensagem).data, status=status.HTTP_201_CREATED)


class JanelaExpirada(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Janela de 24h expirada — é necessário usar um template aprovado.'


class MensagemViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = MensagemSerializer
    http_method_names = ['get', 'post', 'head', 'options']
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return Mensagem.objects.filter(
            conversa_id=self.kwargs['conversa_pk'],
            conversa__fila__membros=self.request.user,
        ).distinct()

    def perform_create(self, serializer):
        conversa = Conversa.objects.get(pk=self.kwargs['conversa_pk'])
        if not conversa.fila or not conversa.fila.membros.filter(pk=self.request.user.pk).exists():
            raise PermissionDenied('Você não pertence à fila desta conversa.')
        if not conversa.dentro_da_janela_24h:
            raise JanelaExpirada()

        anexo = serializer.validated_data.pop('anexo', None)
        mime = getattr(anexo, 'content_type', '') if anexo else ''
        nome = getattr(anexo, 'name', '') if anexo else ''

        mensagem = serializer.save(
            conversa=conversa, direcao='SAIDA', autor=self.request.user,
            # O tipo sai do arquivo: marcar tudo como DOCUMENTO fazia foto virar
            # anexo genérico no histórico e na tela do cliente.
            tipo=graph_api.tipo_interno_da_midia(mime, nome) if anexo else 'TEXTO',
            status_entrega='PENDENTE',
        )
        if anexo:
            MensagemAnexo.objects.create(mensagem=mensagem, arquivo=anexo, mime_type=mime)
        conversa.ultima_mensagem_em = timezone.now()
        conversa.save(update_fields=['ultima_mensagem_em'])
        enviar_mensagem_whatsapp.delay(mensagem.id)


class WhatsAppNotificacaoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WhatsAppNotificacaoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return WhatsAppNotificacao.objects.filter(usuario_notificado=self.request.user)

    @action(detail=False, methods=['post'])
    def marcar_como_lido(self, request):
        ids = request.data.get('notificacao_ids', [])
        WhatsAppNotificacao.objects.filter(id__in=ids, usuario_notificado=request.user).update(lido=True)
        return Response({'status': 'notificacoes marcadas como lidas'})

    @action(detail=False, methods=['get'])
    def nao_lidas(self, request):
        count = WhatsAppNotificacao.objects.filter(usuario_notificado=request.user, lido=False).count()
        return Response({'nao_lidas': count})
