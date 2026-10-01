import logging
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from . import erp, fluxo
from .models import FILIAL_CHOICES, FotoProduto, PedidoVenda, PedidoVendaEvento, PedidoVendaNotificacao, VendedorPerfil
from .serializers import (
    FotoProdutoSerializer,
    PedidoVendaListSerializer,
    PedidoVendaNotificacaoSerializer,
    PedidoVendaSerializer,
    VendedorPerfilSerializer,
)

logger = logging.getLogger(__name__)


class TemAcessoVendas(BasePermission):
    """
    Perfil de vendedor ativo ou gestor de vendas.

    O projeto está com ``DEFAULT_PERMISSION_CLASSES`` vazio, então cada view
    precisa declarar a sua permissão — não confie no default.
    """

    message = 'Seu usuário não tem perfil de vendedor. Peça ao gestor de vendas para cadastrar.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return fluxo.eh_gestor(user) or VendedorPerfil.objects.filter(user=user, ativo=True).exists()


class EhGestorVendas(BasePermission):
    message = 'Acesso restrito ao gestor de vendas.'

    def has_permission(self, request, view):
        return fluxo.eh_gestor(request.user)


def _erro_erp(exc):
    logger.exception('Falha ao consultar o ERP: %s', exc)
    return Response({'detail': 'Não consegui consultar o ERP agora. Tente de novo em instantes.'},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE)


def _repcods(user) -> list[int]:
    perfil = fluxo.perfil_de(user)
    return list(perfil.repcods) if perfil else []


class EuView(APIView):
    """Quem é o usuário para o módulo: perfil, papel e unidades disponíveis."""

    def get(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        perfil = fluxo.perfil_de(user)
        gestor = fluxo.eh_gestor(user)
        return Response({
            'perfil': VendedorPerfilSerializer(perfil).data if perfil else None,
            'gestor': gestor,
            'pode_vender': bool(perfil) or gestor,
            'pode_lancar': gestor or bool(perfil and perfil.tipo == 'INTERNO'),
            'filiais': [{'value': v, 'label': l} for v, l in FILIAL_CHOICES],
        })


class VendedorPerfilViewSet(viewsets.ModelViewSet):
    serializer_class = VendedorPerfilSerializer
    permission_classes = [EhGestorVendas]
    queryset = VendedorPerfil.objects.select_related('user', 'interno__user').all()

    @action(detail=False, methods=['get'])
    def usuarios(self, request):
        """Usuários ativos para o gestor escolher ao cadastrar um perfil."""
        com_perfil = set(VendedorPerfil.objects.values_list('user_id', flat=True))
        usuarios = (
            User.objects.filter(is_active=True)
            .prefetch_related('groups')
            .order_by('first_name', 'username')
        )
        return Response([
            {
                'id': u.pk,
                'nome': u.get_full_name() or u.username,
                'username': u.username,
                'email': u.email,
                'tem_perfil': u.pk in com_perfil,
                'vendedor': any(g.name == 'vendedores' for g in u.groups.all()),
            }
            for u in usuarios
        ])

    @action(detail=False, methods=['get'])
    def representantes(self, request):
        try:
            return Response(erp.representantes())
        except Exception as exc:
            return _erro_erp(exc)


class ErpViewSet(viewsets.ViewSet):
    permission_classes = [TemAcessoVendas]

    @action(detail=False, methods=['get'])
    def clientes(self, request):
        try:
            return Response(erp.buscar_clientes(request.query_params.get('busca', ''), _repcods(request.user)))
        except Exception as exc:
            return _erro_erp(exc)

    @action(detail=False, methods=['get'], url_path=r'clientes/(?P<cod>\d+)')
    def cliente(self, request, cod=None):
        try:
            cli = erp.detalhar_cliente(int(cod), _repcods(request.user))
        except Exception as exc:
            return _erro_erp(exc)
        if cli is None:
            return Response({'detail': 'Cliente não encontrado no ERP.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(cli)

    @action(detail=False, methods=['get'])
    def produtos(self, request):
        try:
            filial = int(request.query_params.get('filial', 0))
            cliente = request.query_params.get('cliente')
            cliente = int(cliente) if cliente else None
        except ValueError:
            return Response({'detail': 'Parâmetros inválidos.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            produtos = erp.catalogo(filial, cliente)
        except Exception as exc:
            return _erro_erp(exc)
        mapa = mapa_fotos(request)
        for p in produtos:
            foto = mapa.get(p['cod'])
            p['foto'] = foto['imagem'] if foto else None
            p['miniatura'] = foto['miniatura'] if foto else None
        return Response(produtos)

    @action(detail=False, methods=['get'])
    def vendaveis(self, request):
        """Produtos com preço em qualquer unidade, para o cadastro de fotos."""
        try:
            return Response(erp.vendaveis([v for v, _ in FILIAL_CHOICES]))
        except Exception as exc:
            return _erro_erp(exc)

    @action(detail=False, methods=['get'])
    def prazos(self, request):
        try:
            return Response(erp.prazos_usuais())
        except Exception as exc:
            return _erro_erp(exc)


def mapa_fotos(request) -> dict[int, dict]:
    """Código do produto → urls da foto (uma foto serve vários códigos)."""
    mapa = {}
    for f in FotoProduto.objects.all():
        urls = {
            'id': f.pk,
            'imagem': request.build_absolute_uri(f.imagem.url),
            'miniatura': request.build_absolute_uri(f.miniatura.url),
        }
        for cod in f.codigos:
            mapa[int(cod)] = urls
    return mapa


class FotoProdutoViewSet(viewsets.ModelViewSet):
    """Fotos dos produtos: todos do módulo veem, só o gestor envia e troca."""

    serializer_class = FotoProdutoSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = FotoProduto.objects.select_related('enviado_por').all()

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'mapa'):
            return [TemAcessoVendas()]
        return [EhGestorVendas()]

    def perform_create(self, serializer):
        serializer.save(enviado_por=self.request.user)

    def perform_update(self, serializer):
        serializer.save(enviado_por=self.request.user)

    def perform_destroy(self, instance):
        instance.imagem.delete(save=False)
        instance.miniatura.delete(save=False)
        instance.delete()

    @action(detail=False, methods=['get'])
    def mapa(self, request):
        return Response({str(k): v for k, v in mapa_fotos(request).items()})


class PedidoVendaViewSet(viewsets.ModelViewSet):
    permission_classes = [TemAcessoVendas]

    def get_serializer_class(self):
        return PedidoVendaListSerializer if self.action == 'list' else PedidoVendaSerializer

    def get_queryset(self):
        user = self.request.user
        qs = PedidoVenda.objects.select_related('vendedor', 'interno', 'aprovado_por').annotate(qtd_itens=Count('itens'))
        if self.action != 'list':
            qs = qs.prefetch_related('itens', 'eventos__usuario')

        perfil = fluxo.perfil_de(user)
        gestor = fluxo.eh_gestor(user)
        interno = bool(perfil and perfil.tipo == 'INTERNO')
        if not gestor:
            if interno:
                # Internos se cobrem nas férias: veem toda a fila, menos rascunho alheio.
                qs = qs.filter(Q(vendedor=user) | ~Q(status='RASCUNHO'))
            else:
                qs = qs.filter(vendedor=user)

        p = self.request.query_params
        escopo = p.get('escopo')
        if escopo == 'meus':
            qs = qs.filter(vendedor=user)
        elif escopo == 'fila':
            qs = qs.filter(status__in=['ENVIADO', 'EM_LANCAMENTO'])
        elif escopo == 'aprovacao':
            qs = qs.filter(status='AGUARDANDO_APROVACAO')
        if p.get('status'):
            qs = qs.filter(status__in=[s for s in p['status'].split(',') if s])
        if p.get('busca'):
            b = p['busca'].strip()
            filtro = Q(cliente_nome__icontains=b) | Q(cliente_fantasia__icontains=b) | Q(cliente_documento__icontains=b)
            if b.isdigit():
                filtro |= Q(pk=int(b)) | Q(numero_erp=int(b)) | Q(cliente_cod=int(b))
            qs = qs.filter(filtro)
        if p.get('dias'):
            try:
                qs = qs.filter(criado_em__gte=timezone.now() - timedelta(days=int(p['dias'])))
            except ValueError:
                pass
        return qs.order_by('-atualizado_em')

    def perform_create(self, serializer):
        perfil = fluxo.perfil_de(self.request.user)
        dados = serializer.validated_data
        extras = {'vendedor': self.request.user}
        if perfil:
            if 'filial' not in dados:
                extras['filial'] = perfil.filial_padrao
            if not dados.get('repcod') and perfil.repcods:
                extras['repcod'] = perfil.repcods[0]
            if perfil.interno:
                extras['interno'] = perfil.interno.user
        serializer.save(**extras)

    def update(self, request, *args, **kwargs):
        pedido = self.get_object()
        if pedido.vendedor_id != request.user.pk:
            return Response({'detail': 'Só o vendedor do pedido pode alterá-lo.'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        pedido = self.get_object()
        if pedido.vendedor_id != request.user.pk or pedido.status != 'RASCUNHO':
            return Response({'detail': 'Só rascunho do próprio vendedor pode ser excluído; use Cancelar.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    # ── Andamento ──

    def _transicao(self, request, funcao, *args):
        pedido = self.get_object()
        try:
            resultado = funcao(pedido, request.user, *args)
        except fluxo.FluxoErro as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        aviso = ''
        if isinstance(resultado, tuple):
            resultado, aviso = resultado
        pedido = self.get_queryset().get(pk=resultado.pk)
        dados = PedidoVendaSerializer(pedido, context=self.get_serializer_context()).data
        if aviso:
            dados['aviso'] = aviso
        return Response(dados)

    @action(detail=True, methods=['post'])
    def enviar(self, request, pk=None):
        return self._transicao(request, fluxo.enviar, request.data.get('justificativa', ''))

    @action(detail=True, methods=['post'])
    def aprovar(self, request, pk=None):
        return self._transicao(request, fluxo.aprovar, request.data.get('texto', ''))

    @action(detail=True, methods=['post'])
    def reprovar(self, request, pk=None):
        return self._transicao(request, fluxo.reprovar, request.data.get('motivo', ''))

    @action(detail=True, methods=['post'])
    def assumir(self, request, pk=None):
        return self._transicao(request, fluxo.assumir)

    @action(detail=True, methods=['post'])
    def lancar(self, request, pk=None):
        return self._transicao(request, fluxo.lancar, request.data.get('numero_erp'))

    @action(detail=True, methods=['post'])
    def devolver(self, request, pk=None):
        return self._transicao(request, fluxo.devolver, request.data.get('motivo', ''))

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        return self._transicao(request, fluxo.cancelar, request.data.get('motivo', ''))

    @action(detail=True, methods=['post'])
    def comentar(self, request, pk=None):
        pedido = self.get_object()
        texto = (request.data.get('texto') or '').strip()
        if not texto:
            return Response({'detail': 'Escreva o comentário.'}, status=status.HTTP_400_BAD_REQUEST)
        PedidoVendaEvento.objects.create(pedido=pedido, usuario=request.user, tipo='COMENTARIO', texto=texto)
        pedido = self.get_queryset().get(pk=pedido.pk)
        return Response(PedidoVendaSerializer(pedido, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'])
    def duplicar(self, request, pk=None):
        """Novo rascunho com o mesmo cliente e itens — o "repetir pedido" do vendedor."""
        origem = self.get_object()
        dados = PedidoVendaSerializer(origem).data
        campos = [
            'filial', 'repcod', 'cliente_cod', 'cliente_nome', 'cliente_fantasia', 'cliente_documento',
            'cliente_cidade', 'cliente_novo', 'endereco_entrega_cod', 'endereco_entrega',
            'prazo_pagamento', 'forma_cobranca', 'frete', 'observacoes',
        ]
        novo = {c: dados[c] for c in campos}
        novo['itens'] = [
            {k: i[k] for k in ('produto_cod', 'descricao', 'unidade', 'quantidade', 'preco_tabela', 'preco_unitario', 'observacao')}
            for i in dados['itens']
        ]
        serializer = PedidoVendaSerializer(data=novo, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        pedido = serializer.save(vendedor=request.user, interno=origem.interno)
        pedido = self.get_queryset().get(pk=pedido.pk)
        return Response(PedidoVendaSerializer(pedido, context=self.get_serializer_context()).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def resumo(self, request):
        """Contagens para os contadores das abas e do menu."""
        qs = self.get_queryset()
        user = request.user
        # A anotação de itens do queryset faz JOIN: sem `distinct` cada item contaria um pedido.
        por_status = {
            linha['status']: linha['n']
            for linha in qs.order_by().values('status').annotate(n=Count('id', distinct=True))
        }
        meus = qs.filter(vendedor=user)
        return Response({
            'por_status': por_status,
            'fila': qs.filter(status__in=['ENVIADO', 'EM_LANCAMENTO']).count(),
            'aprovacao': qs.filter(status='AGUARDANDO_APROVACAO').count() if fluxo.eh_gestor(user) else 0,
            'meus_rascunhos': meus.filter(status='RASCUNHO').count(),
            'meus_devolvidos': meus.filter(status='DEVOLVIDO').count(),
        })


class NotificacaoViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = PedidoVendaNotificacaoSerializer

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return PedidoVendaNotificacao.objects.none()
        return PedidoVendaNotificacao.objects.select_related('pedido').filter(usuario_notificado=user)

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        # Não lidas + as 20 lidas mais recentes: o sino não precisa do histórico inteiro.
        nao_lidas = list(qs.filter(lido=False)[:100])
        lidas = list(qs.filter(lido=True)[:20])
        return Response(self.get_serializer(nao_lidas + lidas, many=True).data)

    @action(detail=False, methods=['post'], url_path='marcar_como_lido')
    def marcar_como_lido(self, request):
        ids = request.data.get('notificacao_ids') or []
        filtro = self.get_queryset().filter(lido=False)
        if ids != 'todas':
            filtro = filtro.filter(id__in=ids)
        filtro.update(lido=True)
        return Response({'status': 'ok'})
