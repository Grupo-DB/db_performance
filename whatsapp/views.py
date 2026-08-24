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

from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import graph_api, services
from .models import (
    Contato, Disparo, DisparoDestinatario, Fila, Conversa, Mensagem, MensagemAnexo,
    NumeroNegocio, WhatsAppNotificacao,
)
from .serializers import (
    FilaSerializer, ConversaListSerializer, ConversaDetailSerializer,
    MensagemSerializer, WhatsAppNotificacaoSerializer,
    ContatoSerializer, ContatoDaAgendaSerializer,
    DisparoSerializer, DisparoDetalheSerializer, NumeroNegocioSerializer,
)
from .tasks import (
    processar_webhook_whatsapp, enviar_mensagem_whatsapp, enviar_template_whatsapp,
    enviar_contato_whatsapp, processar_disparo,
)

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
        # Gestor do atendimento vê todas as filas: é a condição para ele assumir
        # um chamado de qualquer setor (ver services.GRUPO_GESTOR).
        qs = Fila.objects.all() if services.eh_gestor(user) else Fila.objects.filter(membros=user)
        return qs.distinct()

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)


class ConversaViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    Conversa nasce do webhook do WhatsApp, nunca de um POST da tela — daí os
    mixins em vez de ModelViewSet (fica sem create e sem destroy).

    Isso antes era feito com `http_method_names = ['get', 'patch', ...]`, que
    derrubava também os POSTs das @action: assumir, encerrar, criar-tarefa e
    enviar-template respondiam 405 'Method "POST" not allowed'. As ações são
    rotas do MESMO viewset e passam pela mesma checagem de método, que não sabe
    distinguir "criar conversa" de "encerrar conversa". Não voltar a usá-la aqui.
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if services.eh_gestor(self.request.user):
            return Conversa.objects.all()
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
        # get_object antes do UPDATE para a checagem de acesso valer: sem ele, um
        # pk conhecido deixaria assumir conversa de fila alheia.
        conversa = self.get_object()

        if services.eh_gestor(request.user):
            # Gestor tira o chamado de quem estiver com ele — é justamente para
            # isso que o grupo existe (atendente de folga, chamado parado).
            anterior_id = conversa.responsavel_id
            if anterior_id == request.user.pk:
                return Response(ConversaDetailSerializer(conversa).data)
            Conversa.objects.filter(pk=conversa.pk).update(responsavel=request.user)
            conversa.refresh_from_db(fields=['responsavel'])
            services.marcar_avisos_lidos(conversa, usuario=request.user)
            if anterior_id:
                # Quem perdeu o chamado precisa saber: ele estava respondendo.
                WhatsAppNotificacao.objects.create(
                    conversa=conversa, usuario_notificado_id=anterior_id,
                    tipo='CONVERSA_TRANSFERIDA',
                    mensagem=f'{request.user.username} assumiu o atendimento de '
                             f'{conversa.contato_nome or conversa.contato_telefone}'[:255],
                )
            return Response(ConversaDetailSerializer(conversa).data)

        # UPDATE condicional em vez de ler-e-salvar: dois atendentes clicando no
        # mesmo instante, só um leva.
        atualizados = Conversa.objects.filter(pk=conversa.pk, responsavel__isnull=True).update(responsavel=request.user)
        if not atualizados:
            return Response({'detail': 'Conversa já foi assumida por outro usuário.'}, status=status.HTTP_409_CONFLICT)
        # Quem assume está com a conversa aberta na frente: são avisos lidos.
        services.marcar_avisos_lidos(conversa, usuario=request.user)
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
        # Baixa para TODO MUNDO, e não só para quem encerrou.
        #
        # O `lido` é pessoal em todo o resto do atendimento, e aqui era também: o
        # colega que nunca abriu a conversa ficava com o aviso. Só que a conversa
        # encerrada sai da lista de abertas — o aviso apontava para um atendimento
        # que ele não tinha como abrir e nem precisava mais atender. O resultado
        # era badge aceso para sempre, que é o oposto do que ele serve.
        services.marcar_avisos_lidos(conversa)
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
        if not services.pode_atender(request.user, conversa):
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
            # Opt-in explícito: o atendente acabou de falar com o cliente e é quem
            # sabe se ele pediu acompanhamento. Ausente no payload = não avisar.
            notificar_whatsapp=bool(request.data.get('notificar_whatsapp')),
        )
        return Response({
            'id': tarefa.id,
            'titulo': tarefa.titulo,
            'quadro_id': quadro.id,
            'quadro_nome': quadro.nome,
            'coluna_id': coluna.id,
            'coluna_titulo': coluna.titulo,
            'notificar_whatsapp': tarefa.notificar_whatsapp,
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

    @action(detail=True, methods=['post'], url_path='enviar-contato')
    def enviar_contato(self, request, pk=None):
        """
        Compartilha cartões de contato na conversa.

        Recebe `contatos` (ids da agenda) e/ou `avulsos` ([{nome, telefone,
        empresa}]) — o avulso existe para mandar o telefone de alguém que não
        está cadastrado sem obrigar a cadastrar primeiro.

        Exige janela aberta: cartão de contato é mensagem livre, não template.
        """
        conversa = self.get_object()
        if not services.pode_atender(request.user, conversa):
            raise PermissionDenied('Você não pertence à fila desta conversa.')
        if not conversa.dentro_da_janela_24h:
            raise JanelaExpirada()

        cartoes = []
        for contato in Contato.objects.filter(id__in=request.data.get('contatos') or []):
            cartoes.append(graph_api.montar_cartao_contato(
                contato.nome, contato.telefone, contato.empresa))
        for avulso in request.data.get('avulsos') or []:
            telefone = ''.join(c for c in str(avulso.get('telefone') or '') if c.isdigit())
            if len(telefone) < 10:
                continue
            cartoes.append(graph_api.montar_cartao_contato(
                avulso.get('nome') or telefone, telefone, avulso.get('empresa') or ''))

        if not cartoes:
            return Response({'detail': 'Nenhum contato válido para enviar.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # O texto é o rastro legível do histórico; o cartão real vai em
        # `payload_bruto`, que é de onde a bolha desenha os nomes.
        nomes = ', '.join(c['name']['formatted_name'] for c in cartoes)
        mensagem = Mensagem.objects.create(
            conversa=conversa, direcao='SAIDA', tipo='CONTATO', autor=request.user,
            texto=nomes, status_entrega='PENDENTE',
            payload_bruto={'contacts': cartoes},
            responde_a_id=request.data.get('responde_a') or None,
        )
        conversa.ultima_mensagem_em = timezone.now()
        conversa.save(update_fields=['ultima_mensagem_em'])

        enviar_contato_whatsapp.delay(mensagem.id)
        return Response(MensagemSerializer(mensagem).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='enviar-template')
    def enviar_template(self, request, pk=None):
        """
        Envia um template aprovado para reabrir o contato.

        Diferente do envio comum, isto é permitido FORA da janela de 24h — é
        justamente para isso que o template existe. Por isso não passa pela
        checagem de janela do MensagemViewSet.
        """
        conversa = self.get_object()
        if not services.pode_atender(request.user, conversa):
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


class ContatoViewSet(viewsets.ModelViewSet):
    """
    Agenda do atendimento + o cruzamento dela com quem já conversou.

    A Cloud API não tem catálogo de contatos, então a agenda é nossa. A tela
    precisa das DUAS fontes: quem foi cadastrado à mão (e talvez nunca escreveu)
    e quem existe só porque mandou mensagem um dia.
    """

    serializer_class = ContatoSerializer
    permission_classes = [IsAuthenticated]
    queryset = Contato.objects.all()

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    @action(detail=False, methods=['get'], url_path='agenda')
    def agenda(self, request):
        """
        Uma linha por telefone, juntando agenda e conversas.

        Só entram conversas de filas das quais a pessoa participa (gestor vê
        tudo) — a agenda não pode virar a porta dos fundos para ler atendimento
        de outro setor.
        """
        conversas = Conversa.objects.all()
        if not services.eh_gestor(request.user):
            conversas = conversas.filter(fila__membros=request.user)

        # Uma volta só no banco: a linha mais recente de cada telefone é a
        # primeira, porque a ordenação desce por data.
        por_telefone: dict = {}
        for conversa in conversas.order_by('contato_telefone', '-created_at').distinct():
            atual = por_telefone.get(conversa.contato_telefone)
            if atual is None:
                por_telefone[conversa.contato_telefone] = {
                    'nome': conversa.contato_nome or '',
                    'total_conversas': 1,
                    'ultima_conversa_id': conversa.id,
                    'ultima_mensagem_em': conversa.ultima_mensagem_em,
                    'ultima_conversa_status': conversa.status,
                    'janela_aberta': conversa.dentro_da_janela_24h,
                }
            else:
                atual['total_conversas'] += 1

        linhas = []
        vistos = set()
        for contato in Contato.objects.filter(ativo=True):
            de_conversa = por_telefone.get(contato.telefone)
            vistos.add(contato.telefone)
            linhas.append({
                'telefone': contato.telefone,
                # O nome da agenda vence o do perfil do WhatsApp: é o nome que a
                # empresa usa, e o do perfil o cliente troca quando quer.
                'nome': contato.nome,
                'empresa': contato.empresa,
                'observacoes': contato.observacoes,
                'fonte': 'AMBOS' if de_conversa else 'AGENDA',
                'contato_id': contato.id,
                'total_conversas': (de_conversa or {}).get('total_conversas', 0),
                'ultima_conversa_id': (de_conversa or {}).get('ultima_conversa_id'),
                'ultima_mensagem_em': (de_conversa or {}).get('ultima_mensagem_em'),
                'ultima_conversa_status': (de_conversa or {}).get('ultima_conversa_status'),
                'janela_aberta': (de_conversa or {}).get('janela_aberta', False),
            })

        for telefone, dados in por_telefone.items():
            if telefone in vistos:
                continue
            linhas.append({
                'telefone': telefone,
                'nome': dados['nome'] or telefone,
                'empresa': '',
                'observacoes': '',
                'fonte': 'CONVERSA',
                'contato_id': None,
                **{k: v for k, v in dados.items() if k != 'nome'},
            })

        linhas.sort(key=lambda linha: (linha['nome'] or '').lower())
        return Response(ContatoDaAgendaSerializer(linhas, many=True).data)

    @action(detail=False, methods=['post'], url_path='iniciar-conversa')
    def iniciar_conversa(self, request):
        """
        Começa um atendimento a partir da agenda, com template.

        Fora da janela de 24h a Meta só aceita template — e para quem nunca
        escreveu a janela nunca esteve aberta. Por isso o template é obrigatório
        aqui, e não um detalhe opcional.

        A conversa nasce com fila e responsável preenchidos de propósito: o
        `get_queryset` da conversa filtra por `fila__membros`, então conversa sem
        fila ficaria invisível para quem acabou de criá-la.
        """
        telefone = ''.join(c for c in str(request.data.get('telefone') or '') if c.isdigit())
        if len(telefone) < 10:
            return Response({'detail': 'Telefone inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        nome_template = (request.data.get('template') or '').strip()
        if not nome_template:
            return Response(
                {'detail': 'Escolha um template: só ele pode iniciar conversa.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fila = self._fila_para_iniciar(request)
        if fila is None:
            return Response(
                {'detail': 'Você não participa de nenhuma fila — não é possível iniciar conversa.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reaproveita conversa aberta em vez de criar outra: dois registros para o
        # mesmo cliente partiriam o histórico em dois lugares.
        conversa = (Conversa.objects
                    .filter(contato_telefone=telefone, status='ABERTA')
                    .order_by('-created_at').first())
        if conversa is None:
            contato = Contato.objects.filter(telefone=telefone).first()
            conversa = Conversa.objects.create(
                contato_telefone=telefone,
                contato_nome=(contato.nome if contato else ''),
                fila=fila,
                responsavel=request.user,
                # De qual número sai: o da fila quando ela é de um setor, senão o
                # padrão. Sem isso a conversa nasceria sem número e a resposta iria
                # pelo número do .env, que pode não ser o do setor.
                numero=fila.numero or NumeroNegocio.objects.filter(
                    is_padrao=True, ativo=True).first(),
                # Nós iniciamos: não faz sentido mandar o menu de setores para
                # quem foi procurado pela empresa.
                estado_menu='EM_ATENDIMENTO',
            )

        idioma = (request.data.get('idioma') or 'pt_BR').strip()
        componentes = request.data.get('componentes') or None
        mensagem = Mensagem.objects.create(
            conversa=conversa, direcao='SAIDA', tipo='TEXTO', autor=request.user,
            texto=request.data.get('previa') or f'[template: {nome_template}]',
            template_nome=nome_template, status_entrega='PENDENTE',
            payload_bruto={'template': nome_template, 'idioma': idioma, 'componentes': componentes},
        )
        conversa.ultima_mensagem_em = timezone.now()
        conversa.save(update_fields=['ultima_mensagem_em'])

        enviar_template_whatsapp.delay(mensagem.id, nome_template, idioma, componentes)
        return Response(ConversaDetailSerializer(conversa).data, status=status.HTTP_201_CREATED)

    def _fila_para_iniciar(self, request):
        """A fila pedida, se a pessoa participa dela; senão a primeira que for dela."""
        pedida = request.data.get('fila')
        minhas = Fila.objects.filter(ativa=True, membros=request.user)
        if pedida:
            return minhas.filter(id=pedida).first()
        return minhas.order_by('ordem', 'nome').first()


class JanelaExpirada(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Janela de 24h expirada — é necessário usar um template aprovado.'


class MensagemViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = MensagemSerializer
    http_method_names = ['get', 'post', 'head', 'options']
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = Mensagem.objects.filter(conversa_id=self.kwargs['conversa_pk'])
        if not services.eh_gestor(self.request.user):
            qs = qs.filter(conversa__fila__membros=self.request.user)
        # A citada e os anexos entram em toda bolha: sem o prefetch a listagem
        # fazia duas consultas por mensagem do histórico.
        return qs.select_related('autor', 'responde_a', 'responde_a__autor').prefetch_related('anexos').distinct()

    def perform_create(self, serializer):
        conversa = Conversa.objects.get(pk=self.kwargs['conversa_pk'])
        if not services.pode_atender(self.request.user, conversa):
            raise PermissionDenied('Você não pertence à fila desta conversa.')
        if not conversa.dentro_da_janela_24h:
            raise JanelaExpirada()

        # Citar mensagem de outra conversa mandaria para a Meta um context de um
        # telefone diferente — ela recusa a mensagem inteira.
        citada = serializer.validated_data.get('responde_a')
        if citada and citada.conversa_id != conversa.id:
            raise ValidationError({'responde_a': 'A mensagem citada é de outra conversa.'})

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
        # Quem responde leu o que o cliente escreveu. Vale só para ele: o aviso do
        # colega é a leitura DELE, e some quando ele abrir a conversa.
        services.marcar_avisos_lidos(conversa, usuario=self.request.user)
        enviar_mensagem_whatsapp.delay(mensagem.id)


class WhatsAppNotificacaoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WhatsAppNotificacaoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # select_related: o serializer lê a fila pela conversa, e sem isto seriam
        # duas centenas de consultas por listagem.
        return (
            WhatsAppNotificacao.objects
            .filter(usuario_notificado=self.request.user)
            .select_related('conversa')
        )

    def list(self, request, *args, **kwargs):
        """
        Só as mais recentes, e por padrão só as NÃO lidas.

        Cada mensagem recebida gera uma notificação por membro da fila, então em
        alguns meses isto viraria uma lista de milhares de linhas — puxada a cada
        15s por todo mundo logado, já que o aviso de mensagem nova vive no topo da
        tela. Quem consome quer exatamente as pendentes: são elas que viram badge
        por fila, bipe e popup.

        `?lido=` aceita 'false' (padrão), 'true' ou 'todos'.
        """
        qs = self.filter_queryset(self.get_queryset())
        lido = (request.query_params.get('lido') or 'false').lower()
        if lido in ('false', '0'):
            qs = qs.filter(lido=False)
        elif lido in ('true', '1'):
            qs = qs.filter(lido=True)
        return Response(self.get_serializer(qs[:200], many=True).data)

    @action(detail=False, methods=['post'])
    def marcar_como_lido(self, request):
        ids = request.data.get('notificacao_ids', [])
        WhatsAppNotificacao.objects.filter(id__in=ids, usuario_notificado=request.user).update(lido=True)
        return Response({'status': 'notificacoes marcadas como lidas'})

    @action(detail=False, methods=['post'], url_path='marcar-conversa-lida')
    def marcar_conversa_lida(self, request):
        """
        Zera os avisos de uma conversa — abrir o atendimento é ler o aviso.

        Por conversa, e não por lista de ids, porque a tela chama isto no clique
        da conversa: nesse instante ela pode ainda não ter recebido a primeira
        volta do polling, e não teria ids para mandar. Sem isso o sino ficava
        vermelho para sempre e o bipe voltava a tocar a cada recarga.
        """
        conversa_id = request.data.get('conversa_id')
        if not conversa_id:
            return Response({'detail': 'Informe a conversa.'}, status=status.HTTP_400_BAD_REQUEST)
        # Baixa pessoal: quem abriu leu. Os colegas continuam com o aviso até alguém
        # assumir, responder ou encerrar (ver services.marcar_avisos_lidos).
        atualizadas = WhatsAppNotificacao.objects.filter(
            usuario_notificado=request.user, conversa_id=conversa_id, lido=False,
        ).update(lido=True)
        return Response({'marcadas': atualizadas})

    @action(detail=False, methods=['post'], url_path='marcar-fila-lida')
    def marcar_fila_lida(self, request):
        """
        Zera os meus avisos de uma fila inteira — o "marcar tudo como lido" dela.

        Existe porque `lido` é pessoal: um aviso de conversa que outro atendente já
        encerrou não sai abrindo a lista de conversas abertas (a encerrada não está
        lá). Sem esta saída, o badge dessa fila ficaria aceso para sempre.
        """
        fila_id = request.data.get('fila_id')
        if not fila_id:
            return Response({'detail': 'Informe a fila.'}, status=status.HTTP_400_BAD_REQUEST)
        atualizadas = WhatsAppNotificacao.objects.filter(
            usuario_notificado=request.user, conversa__fila_id=fila_id, lido=False,
        ).update(lido=True)
        return Response({'marcadas': atualizadas})

    @action(detail=False, methods=['get'])
    def nao_lidas(self, request):
        count = WhatsAppNotificacao.objects.filter(usuario_notificado=request.user, lido=False).count()
        return Response({'nao_lidas': count})


class DisparoViewSet(viewsets.ModelViewSet):
    """
    Disparo em massa: monta a lista, envia e acompanha.

    Restrito a gestor. Um envio para centenas de pessoas não é operação de
    atendimento — erro aqui não se conserta pedindo desculpa numa conversa, e a
    Meta rebaixa a qualidade do número quando o destinatário bloqueia.
    """

    permission_classes = [IsAuthenticated]
    queryset = Disparo.objects.select_related('numero', 'criado_por')

    def get_serializer_class(self):
        return DisparoDetalheSerializer if self.action == 'retrieve' else DisparoSerializer

    def _exigir_gestor(self):
        if not services.eh_gestor(self.request.user):
            raise PermissionDenied('Só gestor do WhatsApp pode usar o disparo em massa.')

    def get_queryset(self):
        self._exigir_gestor()
        return self.queryset

    def _contatos_dos_telefones(self, telefones):
        """
        Garante um Contato para cada telefone que veio só de conversa.

        Cadastra em vez de gravar o telefone solto no destinatário: assim a
        pessoa passa a existir na agenda e o próximo disparo já a encontra pelo
        nome. O nome sai da conversa mais recente — é o do perfil do WhatsApp,
        o único que temos de quem nunca foi cadastrado.
        """
        encontrados = []
        for bruto in telefones:
            digitos = ''.join(c for c in str(bruto) if c.isdigit())
            if len(digitos) < 10:
                continue
            contato = Contato.objects.filter(telefone=digitos).first()
            if contato is None:
                nome = (Conversa.objects
                        .filter(contato_telefone=digitos)
                        .exclude(contato_nome='')
                        .order_by('-created_at')
                        .values_list('contato_nome', flat=True)
                        .first())
                contato = Contato.objects.create(
                    telefone=digitos,
                    # Sem nome no perfil, o próprio número: `nome` é obrigatório
                    # e deixar em branco daria uma linha ilegível na agenda.
                    nome=nome or digitos,
                    criado_por=self.request.user,
                )
            encontrados.append(contato)
        return encontrados

    def perform_create(self, serializer):
        self._exigir_gestor()
        contatos_ids = serializer.validated_data.pop('contatos_ids', [])
        telefones = serializer.validated_data.pop('telefones', [])
        contatos = list(Contato.objects.filter(id__in=contatos_ids, ativo=True))
        contatos += self._contatos_dos_telefones(telefones)
        # Sem set(): o mesmo telefone pode chegar pelos dois caminhos, e a
        # constraint de (disparo, telefone) já impede a linha repetida.
        if not contatos:
            raise ValidationError({'contatos_ids': 'Nenhum contato válido na seleção.'})

        disparo = serializer.save(criado_por=self.request.user)
        # Telefone e nome são COPIADOS agora, não lidos na hora do envio: a
        # agenda pode mudar no meio de um disparo de horas, e o relatório precisa
        # dizer para onde a mensagem foi de fato.
        DisparoDestinatario.objects.bulk_create([
            DisparoDestinatario(
                disparo=disparo, contato=c, telefone=c.telefone, nome=c.nome,
            )
            for c in contatos
        ], ignore_conflicts=True)  # mesmo telefone repetido na seleção não duplica

    @action(detail=True, methods=['post'])
    def enviar(self, request, pk=None):
        """Põe o disparo na fila do Celery. Também é o 'continuar' de um pausado."""
        self._exigir_gestor()
        disparo = self.get_object()
        if disparo.status in ('CONCLUIDO', 'CANCELADO'):
            return Response(
                {'detail': f'Disparo {disparo.get_status_display().lower()}: não há o que enviar.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not disparo.destinatarios.filter(status='PENDENTE').exists():
            return Response({'detail': 'Nenhum destinatário pendente.'},
                            status=status.HTTP_400_BAD_REQUEST)
        processar_disparo.delay(disparo.id)
        return Response({'detail': 'Envio iniciado.'})

    @action(detail=True, methods=['post'])
    def pausar(self, request, pk=None):
        """
        Interrompe sem descartar: os pendentes continuam pendentes.

        A task relê o status a cada destinatário, então o envio para na próxima
        volta do laço — não é preciso revogar nada no Celery.
        """
        self._exigir_gestor()
        disparo = self.get_object()
        if disparo.status != 'ENVIANDO':
            return Response({'detail': 'Só dá para pausar um disparo em andamento.'},
                            status=status.HTTP_400_BAD_REQUEST)
        disparo.status = 'PAUSADO'
        disparo.detalhe_status = 'Pausado manualmente.'
        disparo.save(update_fields=['status', 'detalhe_status'])
        return Response({'detail': 'Disparo pausado.'})

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        """Encerra de vez. Quem já recebeu, recebeu — não há como desfazer envio."""
        self._exigir_gestor()
        disparo = self.get_object()
        disparo.status = 'CANCELADO'
        disparo.detalhe_status = 'Cancelado manualmente.'
        disparo.save(update_fields=['status', 'detalhe_status'])
        disparo.destinatarios.filter(status='PENDENTE').update(status='CANCELADO')
        return Response({'detail': 'Disparo cancelado.'})


class NumeroNegocioViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Os números da empresa, só para leitura.

    Somente leitura de propósito: cadastrar número exige o `phone_number_id` da
    Meta e casa com fila e textos — errar aqui manda a resposta pelo número do
    outro setor. Isso é cadastro de admin, não de tela.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = NumeroNegocioSerializer
    queryset = NumeroNegocio.objects.filter(ativo=True).order_by('-is_padrao', 'nome')
