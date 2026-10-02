import logging
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from django.http import FileResponse, Http404
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from . import cargas, erp, fluxo
from .models import FILIAL_CHOICES, FolhaCarga, FotoProduto, ItemFolhaCarga, PedidoVenda, PedidoVendaEvento, PedidoVendaNotificacao, VendedorPerfil
from .serializers import (
    FolhaCargaSerializer,
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
    return Response({'detail': 'Não consegui consultar o Minerion/SGA agora. Tente de novo em instantes.'},
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
            p = request.query_params
            return Response(erp.buscar_clientes(p.get('busca', ''), _repcods(request.user), campo=p.get('campo', '')))
        except Exception as exc:
            return _erro_erp(exc)

    @action(detail=False, methods=['get'], url_path=r'clientes/(?P<cod>\d+)')
    def cliente(self, request, cod=None):
        try:
            cli = erp.detalhar_cliente(int(cod), _repcods(request.user))
        except Exception as exc:
            return _erro_erp(exc)
        if cli is None:
            return Response({'detail': 'Cliente não encontrado no Minerion/SGA.'}, status=status.HTTP_404_NOT_FOUND)
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
            'imagem': f.caminho(),
            'miniatura': f.caminho(miniatura=True),
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
        # <img> não manda o token: o arquivo é público (são as embalagens de marketing).
        if self.action == 'arquivo':
            return [AllowAny()]
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

    @action(detail=True, methods=['get'], authentication_classes=[])
    def arquivo(self, request, pk=None):
        foto = FotoProduto.objects.filter(pk=pk).first()
        arquivo = foto and (foto.miniatura if request.query_params.get('t') == 'mini' else foto.imagem)
        if not arquivo:
            raise Http404
        try:
            resposta = FileResponse(arquivo.open('rb'), content_type='image/jpeg')
        except FileNotFoundError:
            raise Http404
        # A URL leva a versão (?v=), então pode ficar em cache por muito tempo.
        resposta['Cache-Control'] = 'public, max-age=2592000, immutable'
        return resposta

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
            'prazo_pagamento', 'forma_cobranca', 'frete', 'paletizado', 'frete_valor_ton', 'observacoes',
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


# ── Painel de cargas (só leitura do SGA) ────────────────────────────────────

# Expedição/portaria e a TV do pátio: veem o painel inteiro sem perfil de vendedor.
GRUPOS_PAINEL_CARGAS = ('cargasPainel',)
CACHE_PAINEL_SEG = 20


def _ve_todas_as_cargas(user) -> bool:
    if fluxo.eh_gestor(user) or user.groups.filter(name__in=GRUPOS_PAINEL_CARGAS).exists():
        return True
    perfil = fluxo.perfil_de(user)
    return bool(perfil and perfil.tipo == 'INTERNO')


class TemAcessoCargas(BasePermission):
    message = 'Seu usuário não tem acesso ao painel de cargas.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return _ve_todas_as_cargas(user) or VendedorPerfil.objects.filter(user=user, ativo=True).exists()


def _data_param(valor, padrao):
    try:
        return date.fromisoformat(valor) if valor else padrao
    except ValueError:
        return padrao


class PainelCargasView(APIView):
    """
    Carregamentos e cargas compostas do SGA + pedidos aguardando carga.

    `?inicio=&fim=` é o período das notas faturadas (padrão: hoje); pendentes e
    aguardando não dependem dele. `?filial=` filtra a unidade. Vendedor externo
    vê só os seus (REPCOD do perfil); `?escopo=meus` força isso para quem vê tudo.
    """
    permission_classes = [TemAcessoCargas]

    def get(self, request):
        p = request.query_params
        hoje = date.today()
        inicio = _data_param(p.get('inicio'), hoje)
        fim = max(_data_param(p.get('fim'), inicio), inicio)
        if (fim - inicio).days > 62:
            return Response({'detail': 'Período máximo de 62 dias.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            filial = int(p['filial']) if p.get('filial') not in (None, '') else None
        except ValueError:
            return Response({'detail': 'Unidade inválida.'}, status=status.HTTP_400_BAD_REQUEST)

        todas = _ve_todas_as_cargas(request.user) and p.get('escopo') != 'meus'
        repcods = None if todas else sorted(_repcods(request.user))
        com_aguardando = p.get('aguardando', '1') != '0'

        # A TV e vários navegadores fazem polling: a mesma consulta serve a todos por 20 s.
        reps = '-'.join(map(str, repcods)) if repcods is not None else 'todos'
        chave = f'pedidosVenda:cargas:{inicio}:{fim}:{filial}:{reps}:{int(com_aguardando)}'
        dados = cache.get(chave)
        if dados is None:
            try:
                dados = cargas.painel(inicio, fim, filial, repcods, com_aguardando)
            except Exception as exc:
                return _erro_erp(exc)
            dados['pre_pedidos'] = self._pre_pedidos(request.user, todas, filial) if com_aguardando else []
            dados['atualizado_em'] = timezone.localtime().isoformat()
            cache.set(chave, dados, CACHE_PAINEL_SEG)
        return Response({**dados, 've_todas': todas})

    @staticmethod
    def _pre_pedidos(user, todas, filial):
        """Pedidos do app que ainda não viraram pedido no SGA — chegam antes ao painel."""
        qs = PedidoVenda.objects.select_related('vendedor').filter(
            status__in=['AGUARDANDO_APROVACAO', 'ENVIADO', 'EM_LANCAMENTO'])
        if not todas:
            qs = qs.filter(vendedor=user)
        if filial is not None:
            qs = qs.filter(filial=filial)
        return [{
            'id': pv.id, 'status': pv.status, 'status_display': pv.get_status_display(),
            'cliente': pv.cliente_nome, 'cidade': pv.cliente_cidade, 'filial': pv.filial,
            'vendedor': pv.vendedor.get_full_name() or pv.vendedor.username,
            'total': float(pv.total), 'data_entrega': pv.data_entrega.isoformat() if pv.data_entrega else None,
            'enviado_em': pv.enviado_em.isoformat() if pv.enviado_em else None,
        } for pv in qs.order_by('enviado_em')[:200]]


# ── Folhas de carga (rascunho antes do SGA) ─────────────────────────────────

class PodeMontarCarga(BasePermission):
    """Quem monta a carga é o vendas interno (e a gestão); a expedição só olha."""
    message = 'Só o vendas interno e a gestão montam cargas.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return _ve_todas_as_cargas(user)
        if fluxo.eh_gestor(user):
            return True
        perfil = fluxo.perfil_de(user)
        return bool(perfil and perfil.tipo == 'INTERNO')


class FolhaCargaViewSet(viewsets.ModelViewSet):
    """
    `?status=MONTANDO` (padrão) | `NO_SGA` | `CANCELADA` | `todas`.

    Ao listar as abertas, confere no SGA quais pedidos já viraram carregamento:
    a folha cujos pedidos estão todos lá fecha sozinha (`NO_SGA`).
    """
    serializer_class = FolhaCargaSerializer
    permission_classes = [PodeMontarCarga]

    def get_queryset(self):
        qs = FolhaCarga.objects.select_related('criado_por').prefetch_related('itens')
        if self.action != 'list':
            return qs
        st = self.request.query_params.get('status', 'MONTANDO')
        if st != 'todas':
            qs = qs.filter(status=st)
        if st != 'MONTANDO':
            qs = qs[:100]
        return qs

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    def update(self, request, *args, **kwargs):
        if self.get_object().status != 'MONTANDO':
            return Response({'detail': 'Folha fechada não muda mais. Reabra antes.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().update(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        folhas = list(self.get_queryset())
        sga = self._conferir_sga([f for f in folhas if f.status == 'MONTANDO'])
        dados = self.get_serializer(folhas, many=True).data
        for d in dados:
            for i in d['itens']:
                i['sga'] = sga.get(i['pedido'])
        return Response(dados)

    def retrieve(self, request, *args, **kwargs):
        folha = self.get_object()
        sga = self._conferir_sga([folha]) if folha.status == 'MONTANDO' else {}
        dados = self.get_serializer(folha).data
        for i in dados['itens']:
            i['sga'] = sga.get(i['pedido'])
        return Response(dados)

    @staticmethod
    def _conferir_sga(folhas) -> dict:
        pedidos = [i.pedido for f in folhas for i in f.itens.all()]
        if not pedidos:
            return {}
        desde = min(f.criado_em for f in folhas).date()
        chave = f"pedidosVenda:folhas:{desde}:{hash(tuple(sorted(pedidos)))}"
        sga = cache.get(chave)
        if sga is None:
            try:
                sga = cargas.situacao_no_sga(pedidos, desde)
            except Exception:
                logger.exception('Folhas de carga: conferência no SGA falhou')
                return {}
            cache.set(chave, sga, CACHE_PAINEL_SEG)
        agora = timezone.now()
        for f in folhas:
            itens = list(f.itens.all())
            if itens and all(i.pedido in sga for i in itens):
                cods = [sga[i.pedido]['carga_cod'] for i in itens if sga[i.pedido]['carga_cod']]
                f.status = 'NO_SGA'
                f.carga_sga = max(set(cods), key=cods.count) if cods else None
                f.fechada_em = agora
                FolhaCarga.objects.filter(pk=f.pk).update(status=f.status, carga_sga=f.carga_sga, fechada_em=agora)
        return sga

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        folha = self.get_object()
        folha.status, folha.fechada_em = 'CANCELADA', timezone.now()
        folha.save(update_fields=['status', 'fechada_em', 'atualizado_em'])
        return Response(self.get_serializer(folha).data)

    @action(detail=True, methods=['post'])
    def reabrir(self, request, pk=None):
        folha = self.get_object()
        if folha.status == 'MONTANDO':
            return Response(self.get_serializer(folha).data)
        conflito = ItemFolhaCarga.objects.filter(
            pedido__in=folha.itens.values('pedido'), folha__status='MONTANDO').select_related('folha').first()
        if conflito:
            return Response({'detail': f'Pedido {conflito.pedido} já está na folha "{conflito.folha.descricao}".'},
                            status=status.HTTP_400_BAD_REQUEST)
        folha.status, folha.fechada_em, folha.carga_sga = 'MONTANDO', None, None
        folha.save(update_fields=['status', 'fechada_em', 'carga_sga', 'atualizado_em'])
        return Response(self.get_serializer(folha).data)
