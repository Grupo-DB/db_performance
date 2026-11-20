import copy
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.contrib.auth.models import User
from django.db import DatabaseError, transaction
from django.core.cache import cache
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from . import erp_agro, regras
from .models import Contato, Cotacao, MetaAgro, Produtor, VendedorAgro
from .serializers import (ContatoSerializer, CotacaoSerializer, MetaAgroSerializer, ProdutorSerializer,
                          VendedorAgroSerializer)

logger = logging.getLogger(__name__)

GRUPOS_GESTOR = {'Admin', 'Master', 'agroGestor'}
GRUPOS_INTERNO = {'agroInterno'}


# ── Papéis ──────────────────────────────────────────────────────────────────

def _grupos(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if not hasattr(user, '_grupos_agro'):
        user._grupos_agro = set(user.groups.values_list('name', flat=True))
    return user._grupos_agro


def eh_gestor(user) -> bool:
    return bool(user and (user.is_superuser or _grupos(user) & GRUPOS_GESTOR))


def eh_interno(user) -> bool:
    return eh_gestor(user) or bool(_grupos(user) & GRUPOS_INTERNO)


def vendedor_de(user) -> VendedorAgro | None:
    if not user or not user.is_authenticated:
        return None
    return VendedorAgro.objects.filter(user=user, ativo=True).first()


def ve_tudo(user) -> bool:
    return eh_interno(user)


class TemAcesso(BasePermission):
    message = 'Seu usuário não está no Comercial Agro. Peça ao gestor para cadastrar.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (eh_interno(u) or vendedor_de(u)))


class EhGestor(BasePermission):
    message = 'Só o gestor comercial faz isso.'

    def has_permission(self, request, view):
        return eh_gestor(request.user)


class EhInterno(BasePermission):
    message = 'Só o vendedor interno lança no SGA.'

    def has_permission(self, request, view):
        return eh_interno(request.user)


def _erro_sga(exc):
    logger.exception('Comercial Agro: falha ao ler o SGA: %s', exc)
    return Response({'detail': 'Não consegui ler o SGA (Minerion) agora. Tente de novo em instantes.'},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE)


def _repcods_de(request) -> list[int]:
    """REPCOD que a tela mostra: os do vendedor logado, ou os de ?vendedor= (gestor/interno), ou todos."""
    u = request.user
    vid = request.query_params.get('vendedor')
    if ve_tudo(u):
        if vid:
            v = VendedorAgro.objects.filter(pk=vid).first()
            return list(v.repcods) if v else []
        return sorted({int(r) for v in VendedorAgro.objects.filter(ativo=True) for r in v.repcods})
    v = vendedor_de(u)
    return list(v.repcods) if v else []


def _vendedor_filtro(request):
    """Vendedor das listas: o logado; gestor/interno veem todos ou o de ?vendedor=."""
    u = request.user
    if ve_tudo(u):
        vid = request.query_params.get('vendedor')
        return VendedorAgro.objects.filter(pk=vid).first() if vid else None
    return vendedor_de(u) or VendedorAgro(pk=-1)


# ── Quem sou eu ─────────────────────────────────────────────────────────────

class EuView(APIView):
    permission_classes = [TemAcesso]

    def get(self, request):
        v = vendedor_de(request.user)
        return Response({
            'vendedor': VendedorAgroSerializer(v).data if v else None,
            'gestor': eh_gestor(request.user),
            'interno': eh_interno(request.user),
            'culturas': regras.CULTURAS,
            'prazos': regras.PRAZOS,
            'taxa_mensal': regras.TAXA_MENSAL,
            'aprovar_todas': regras.APROVAR_TODAS,
            'vendedores': [{'id': x.id, 'nome': x.nome, 'carteira': x.carteira}
                           for x in VendedorAgro.objects.filter(ativo=True).select_related('user')]
            if ve_tudo(request.user) else [],
        })


# ── Início do vendedor ──────────────────────────────────────────────────────

class InicioView(APIView):
    permission_classes = [TemAcesso]

    def get(self, request):
        hoje = timezone.localdate()
        vend = _vendedor_filtro(request)
        cot = Cotacao.objects.all()
        cont = Contato.objects.filter(proximo_feito_em__isnull=True)
        if vend is not None:
            cot, cont = cot.filter(vendedor=vend), cont.filter(vendedor=vend)
        aguardando = cot.filter(status='AGUARDANDO').order_by('criado_em')
        passos = cont.select_related('produtor').order_by('proximo_data', 'id')[:12]
        meta = None
        if vend is not None and vend.pk and vend.pk > 0:
            m = MetaAgro.objects.filter(vendedor=vend, ano=hoje.year).first()
            meta = float(m.toneladas) if m else None
        elif vend is None:
            total = sum(float(m.toneladas) for m in MetaAgro.objects.filter(ano=hoje.year, vendedor__ativo=True))
            meta = total or None
        dados = {
            'ano': hoje.year,
            'meta_t': meta,
            'contrapropostas': cot.filter(status='CONTRAPROPOSTA').count(),
            'aguardando': aguardando.count(),
            'aguardando_desde': aguardando[0].criado_em if aguardando.exists() else None,
            'aprovadas': cot.filter(status='APROVADA').count(),
            'passos': [{'id': c.id, 'produtor': c.produtor_id, 'nome': c.produtor.nome, 'passo': c.proximo_passo,
                        'data': c.proximo_data, 'atrasado': c.proximo_data < hoje} for c in passos],
            'vendas': None,
        }
        try:
            dados['vendas'] = erp_agro.vendas(_repcods_de(request), hoje.year, hoje)
            dados['vendas'].pop('a_carregar', None)
            dados['vendas'].pop('sem_compra', None)
        except Exception as exc:  # o início abre mesmo com o SGA fora
            logger.warning('Comercial Agro: início sem vendas do SGA: %s', exc)
        return Response(dados)


# ── Clientes (SGA + prospects do app) ───────────────────────────────────────

class ClientesView(APIView):
    permission_classes = [TemAcesso]

    def get(self, request):
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response({'sga': [], 'app': []})
        app = Produtor.objects.filter(
            Q(nome__icontains=q) | Q(documento__icontains=q) | Q(municipio__icontains=q)).order_by('nome')[:15]
        try:
            sga = erp_agro.buscar(q, _repcods_de(request))
        except Exception as exc:
            return _erro_sga(exc)
        ligados = dict(Produtor.objects.filter(cliente_sga__in=[c['cod'] for c in sga]).values_list('cliente_sga', 'id'))
        try:
            ultimas = erp_agro.ultimas_compras([c['cod'] for c in sga])
        except Exception as exc:
            logger.warning('Comercial Agro: busca sem última compra: %s', exc)
            ultimas = {}
        for c in sga:
            c['produtor'] = ligados.get(c['cod'])
            c['ultima_compra'] = ultimas.get(c['cod'])
        return Response({
            'sga': sga,
            'app': [{'id': p.id, 'nome': p.nome, 'municipio': p.municipio, 'cadastro': p.cadastro,
                     'cliente_sga': p.cliente_sga} for p in app if p.cliente_sga not in ligados],
        })


# ── Produtores ──────────────────────────────────────────────────────────────

class ProdutorViewSet(viewsets.ModelViewSet):
    serializer_class = ProdutorSerializer
    permission_classes = [TemAcesso]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ['get', 'post', 'patch']

    def get_queryset(self):
        qs = Produtor.objects.select_related('vendedor__user')
        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(Q(nome__icontains=q) | Q(municipio__icontains=q))
        return qs

    def perform_create(self, serializer):
        serializer.save(vendedor=vendedor_de(self.request.user), criado_por=self.request.user,
                        origem='PROSPECT', cadastro='PROSPECT')

    def retrieve(self, request, *args, **kwargs):
        p = self.get_object()
        dados = self.get_serializer(p).data
        dados['contatos'] = ContatoSerializer(p.contatos.select_related('vendedor__user')[:20], many=True).data
        dados['cotacoes'] = CotacaoSerializer(p.cotacoes.select_related('vendedor__user', 'produtor')[:20], many=True).data
        dados['historico'] = []
        dados['financeiro'] = None
        dados['sga'] = None
        if p.cliente_sga:
            try:
                dados['historico'] = erp_agro.historico_cliente(p.cliente_sga)
                dados['financeiro'] = erp_agro.financeiro(p.cliente_sga)
                dados['sga'] = erp_agro.cliente(p.cliente_sga)
            except Exception as exc:
                logger.warning('Comercial Agro: ficha sem dados do SGA: %s', exc)
        return Response(dados)

    @action(detail=False, methods=['post'])
    def sga(self, request):
        """Cliente da casa: cria (ou devolve) o produtor ligado ao código do SGA."""
        try:
            cod = int(request.data.get('cliente'))
        except (TypeError, ValueError):
            return Response({'detail': 'Informe o código do cliente.'}, status=400)
        p = Produtor.objects.filter(cliente_sga=cod).first()
        if p is None:
            try:
                c = erp_agro.cliente(cod)
            except Exception as exc:
                return _erro_sga(exc)
            if not c:
                return Response({'detail': f'Cliente {cod} não existe no SGA.'}, status=404)
            cidade = (c['cidade'] or '').rsplit('-', 1)[0].strip().title()
            p = Produtor.objects.create(
                nome=c['nome'] or c['fantasia'], documento=c['documento'], whatsapp=c['celular'], municipio=cidade,
                cliente_sga=cod, cadastro='CADASTRADO', origem='SGA', vendedor=vendedor_de(request.user),
                criado_por=request.user)
        return Response(self.get_serializer(p).data)

    @action(detail=True, methods=['post'])
    def ajuste(self, request, pk=None):
        """Vendedor pede ao interno um ajuste do cadastro no SGA (contato novo, endereço…)."""
        texto = (request.data.get('texto') or '').strip()
        if not texto:
            return Response({'detail': 'Descreva o ajuste.'}, status=400)
        p = self.get_object()
        p.ajuste_cadastro, p.ajuste_pedido_em = texto, timezone.now()
        p.save(update_fields=['ajuste_cadastro', 'ajuste_pedido_em', 'atualizado_em'])
        return Response(self.get_serializer(p).data)

    @action(detail=True, methods=['post'])
    def car(self, request, pk=None):
        """Liga (ou desliga, com codigo vazio) o imóvel do CAR ao produtor."""
        p = self.get_object()
        p.car_codigo = (request.data.get('codigo') or '').strip()[:60]
        p.save(update_fields=['car_codigo', 'atualizado_em'])
        return Response(self.get_serializer(p).data)

    @action(detail=True, methods=['post'], permission_classes=[EhInterno])
    def ajuste_feito(self, request, pk=None):
        p = self.get_object()
        p.ajuste_cadastro, p.ajuste_pedido_em = '', None
        p.save(update_fields=['ajuste_cadastro', 'ajuste_pedido_em', 'atualizado_em'])
        return Response(self.get_serializer(p).data)

    @action(detail=True, methods=['post'], permission_classes=[EhInterno])
    def cadastrado(self, request, pk=None):
        """Interno informa o código do cliente que acabou de cadastrar no SGA; o app confere."""
        p = self.get_object()
        try:
            cod = int(request.data.get('cliente_sga'))
        except (TypeError, ValueError):
            return Response({'detail': 'Informe o código do cliente no SGA.'}, status=400)
        outro = Produtor.objects.filter(cliente_sga=cod).exclude(pk=p.pk).first()
        if outro:
            return Response({'detail': f'O código {cod} já está ligado a {outro.nome}.'}, status=400)
        try:
            c = erp_agro.cliente(cod)
        except Exception as exc:
            return _erro_sga(exc)
        if not c:
            return Response({'detail': f'Cliente {cod} não existe no SGA. Confira o código.'}, status=400)
        p.cliente_sga, p.cadastro = cod, 'CADASTRADO'
        p.cadastrado_por, p.cadastrado_em = request.user, timezone.now()
        p.save()
        return Response({**self.get_serializer(p).data, 'nome_sga': c['nome']})


# ── Contatos ────────────────────────────────────────────────────────────────

class ContatoViewSet(viewsets.ModelViewSet):
    serializer_class = ContatoSerializer
    permission_classes = [TemAcesso]
    http_method_names = ['get', 'post', 'patch']

    def get_queryset(self):
        qs = Contato.objects.select_related('produtor', 'vendedor__user')
        vend = _vendedor_filtro(self.request)
        if vend is not None:
            qs = qs.filter(vendedor=vend)
        prod = self.request.query_params.get('produtor')
        if prod:
            qs = qs.filter(produtor_id=prod)
        if self.request.query_params.get('pendentes'):
            qs = qs.filter(proximo_feito_em__isnull=True).order_by('proximo_data')
        return qs[:200] if self.action == 'list' else qs

    def perform_create(self, serializer):
        c = serializer.save(vendedor=vendedor_de(self.request.user), autor=self.request.user)
        # Visita com GPS e produtor ainda sem imóvel: tenta ligar ao CAR (best-effort, ~0,5 s).
        if c.tipo == 'VISITA' and c.latitude is not None and not c.produtor.car_codigo:
            try:
                from . import geo
                im = geo.car_no_ponto(float(c.latitude), float(c.longitude))
                if im:
                    c.produtor.car_codigo = im['codigo']
                    c.produtor.save(update_fields=['car_codigo', 'atualizado_em'])
            except Exception as exc:
                logger.info('Comercial Agro: contato sem CAR: %s', exc)

    @action(detail=True, methods=['post'])
    def feito(self, request, pk=None):
        c = self.get_object()
        c.proximo_feito_em = None if request.data.get('desfazer') else timezone.now()
        c.save(update_fields=['proximo_feito_em'])
        return Response(self.get_serializer(c).data)


# ── Produtos ────────────────────────────────────────────────────────────────

class ProdutosView(APIView):
    permission_classes = [TemAcesso]

    def get(self, request):
        cli = request.query_params.get('cliente')
        try:
            return Response(erp_agro.produtos(0, int(cli) if cli else None))
        except Exception as exc:
            return _erro_sga(exc)


# ── Cotações ────────────────────────────────────────────────────────────────

class CotacaoViewSet(viewsets.ModelViewSet):
    serializer_class = CotacaoSerializer
    permission_classes = [TemAcesso]
    http_method_names = ['get', 'post']

    def get_queryset(self):
        qs = Cotacao.objects.select_related('produtor', 'vendedor__user', 'decidido_por', 'lancado_por', 'autor')
        modo = self.request.query_params.get('modo', 'minhas')
        u = self.request.user
        if modo == 'aprovacao' and eh_gestor(u):
            return qs.filter(status='AGUARDANDO').order_by('criado_em')
        if modo == 'fila' and eh_interno(u):
            return qs.filter(status='APROVADA').order_by('aprovada_em')
        vend = _vendedor_filtro(self.request)
        if vend is not None:
            qs = qs.filter(vendedor=vend)
        st = self.request.query_params.get('status')
        if st:
            qs = qs.filter(status__in=st.split(','))
        return qs[:300] if self.action == 'list' else qs

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        produtor = ser.validated_data['produtor']
        prod = ser.validated_data['produto_cod']
        try:
            itens = {p['cod']: p for p in erp_agro.produtos(0, produtor.cliente_sga)}
        except Exception as exc:
            return _erro_sga(exc)
        if prod not in itens:
            return Response({'detail': 'Produto sem preço padrão no SGA.'}, status=400)
        padrao = itens[prod]['preco_padrao']
        pendencia = ''
        if produtor.cliente_sga:
            try:
                fin = erp_agro.financeiro(produtor.cliente_sga) or {}
                if fin.get('bloqueado'):
                    pendencia = 'Cliente bloqueado para venda no SGA.'
                elif fin.get('vencido'):
                    valor = f"{fin['vencido']:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
                    pendencia = f"Título vencido há {fin.get('maior_atraso') or 0} dias · R$ {valor}"
            except Exception as exc:
                logger.warning('Comercial Agro: cotação sem financeiro: %s', exc)
        else:
            pendencia = 'Prospect sem cadastro no SGA: o pedido só sai após análise de crédito.'
        agora = timezone.now()
        direto = not regras.precisa_aprovacao(ser.validated_data['preco'], ser.validated_data['prazo_dias'], padrao)
        c = ser.save(vendedor=vendedor_de(request.user), autor=request.user, produto_nome=itens[prod]['descricao'],
                     unidade=itens[prod]['unidade'], preco_padrao=padrao, pendencia_credito=pendencia,
                     retirada=regras.primeiro_do_mes(ser.validated_data['retirada']),
                     status='APROVADA' if direto else 'AGUARDANDO', aprovada_direto=direto,
                     aprovada_em=agora if direto else None)
        return Response(self.get_serializer(c).data, status=201)

    def retrieve(self, request, *args, **kwargs):
        c = self.get_object()
        dados = self.get_serializer(c).data
        p = c.produtor
        dados['produtor_ficha'] = ProdutorSerializer(p, context={'request': request}).data
        dados['media_carteira'] = None
        dados['historico'] = []
        dados['financeiro'] = None
        try:
            reps = c.vendedor.repcods if c.vendedor else []
            dados['media_carteira'] = erp_agro.media_preco(reps, c.produto_cod, c.criado_em.year) if reps else None
            if p.cliente_sga:
                dados['historico'] = erp_agro.historico_cliente(p.cliente_sga)
                dados['financeiro'] = erp_agro.financeiro(p.cliente_sga)
        except Exception as exc:
            logger.warning('Comercial Agro: cotação sem contexto do SGA: %s', exc)
        dados['taxa_mensal'] = regras.TAXA_MENSAL
        return Response(dados)

    @action(detail=True, methods=['post'], permission_classes=[EhGestor])
    def decidir(self, request, pk=None):
        c = self.get_object()
        if c.status != 'AGUARDANDO':
            return Response({'detail': 'Esta cotação já foi decidida.'}, status=400)
        acao = request.data.get('acao')
        agora = timezone.now()
        c.decidido_por, c.decidido_em = request.user, agora
        c.recado = (request.data.get('recado') or '').strip()
        if acao == 'aprovar':
            c.status, c.aprovada_em = 'APROVADA', agora
        elif acao == 'recusar':
            if not c.recado:
                return Response({'detail': 'Diga ao vendedor por que recusou.'}, status=400)
            c.status = 'RECUSADA'
        elif acao == 'contrapropor':
            try:
                c.contra_preco = round(float(request.data.get('preco')), 2)
                c.contra_prazo = int(request.data.get('prazo'))
            except (TypeError, ValueError):
                return Response({'detail': 'Informe preço e prazo da contraproposta.'}, status=400)
            if c.contra_prazo not in regras.PRAZOS or c.contra_preco <= 0:
                return Response({'detail': 'Preço ou prazo inválido.'}, status=400)
            cond = request.data.get('condicao') or ''
            if cond not in dict(Cotacao.CONDICAO_CHOICES):
                return Response({'detail': 'Condição inválida.'}, status=400)
            c.contra_condicao = cond
            c.status = 'CONTRAPROPOSTA'
        else:
            return Response({'detail': 'Ação inválida.'}, status=400)
        c.save()
        return Response(self.get_serializer(c).data)

    @action(detail=True, methods=['post'])
    def responder(self, request, pk=None):
        """Vendedor leva a contraproposta ao cliente: aceita → fila do interno; não aceita → encerra."""
        c = self.get_object()
        if c.status != 'CONTRAPROPOSTA':
            return Response({'detail': 'Não há contraproposta aberta.'}, status=400)
        agora = timezone.now()
        c.respondida_em = agora
        if request.data.get('aceitar'):
            c.status, c.aprovada_em = 'APROVADA', agora
        else:
            c.status = 'DESISTIU'
        c.save()
        return Response(self.get_serializer(c).data)

    def _conferir(self, c: Cotacao) -> Response | None:
        try:
            ped = erp_agro.pedido(c.pedido_sga)
        except Exception as exc:
            return _erro_sga(exc)
        if not ped:
            return Response({'detail': f'Pedido {c.pedido_sga} não existe no SGA. Confira o número.'}, status=400)
        itens = [i for i in ped['itens'] if i['produto'] == c.produto_cod]
        lancado = {
            'cliente': ped['cliente'],
            'produto': c.produto_cod if itens else (ped['itens'][0]['produto'] if ped['itens'] else None),
            'volume_t': round(sum(i['toneladas'] for i in itens), 2) if itens else 0,
            'preco': itens[0]['preco'] if itens else None,
            'prazo': ped['prazo'],
        }
        aprovado = {'cliente': c.produtor.cliente_sga, 'produto': c.produto_cod, 'volume_t': float(c.volume_t),
                    'preco': float(c.preco_final), 'prazo': c.prazo_final}
        dif = regras.conferir(aprovado, lancado)
        c.conferencia = {'em': timezone.now().isoformat(timespec='seconds'), 'aprovado': aprovado, 'lancado': lancado,
                         'prazo_texto': ped['prazo_texto'], 'situacao_sga': ped['situacao'], 'diferencas': dif}
        c.divergente = bool(dif)
        return None

    @action(detail=True, methods=['post'], permission_classes=[EhInterno])
    def lancar(self, request, pk=None):
        c = self.get_object()
        if c.status not in ('APROVADA', 'LANCADA'):
            return Response({'detail': 'Só cotação aprovada vai para o SGA.'}, status=400)
        if not c.produtor.cliente_sga:
            return Response({'detail': 'Cadastre o cliente no SGA primeiro (fila de cadastro).'}, status=400)
        try:
            c.pedido_sga = int(request.data.get('pedido'))
        except (TypeError, ValueError):
            return Response({'detail': 'Informe o nº do pedido no SGA.'}, status=400)
        erro = self._conferir(c)
        if erro:
            return erro
        c.status, c.lancado_por, c.lancado_em = 'LANCADA', request.user, timezone.now()
        c.save()
        return Response(self.get_serializer(c).data)

    @action(detail=True, methods=['post'], permission_classes=[EhInterno])
    def conferir(self, request, pk=None):
        """Relê o pedido no SGA (depois de corrigir lá)."""
        c = self.get_object()
        if not c.pedido_sga:
            return Response({'detail': 'Cotação ainda sem pedido no SGA.'}, status=400)
        antes = c.divergente
        erro = self._conferir(c)
        if erro:
            return erro
        if antes and not c.divergente:
            c.corrigido_em = timezone.now()  # conta no painel: lançado diferente e corrigido no SGA
        c.save()
        return Response(self.get_serializer(c).data)


# ── Minhas vendas ───────────────────────────────────────────────────────────

class VendasView(APIView):
    permission_classes = [TemAcesso]

    def get(self, request):
        hoje = timezone.localdate()
        ano = int(request.query_params.get('ano') or hoje.year)
        try:
            dados = erp_agro.vendas(_repcods_de(request), ano, hoje)
        except Exception as exc:
            return _erro_sga(exc)
        vend = _vendedor_filtro(request)
        metas = MetaAgro.objects.filter(ano=ano)
        if vend is not None:
            metas = metas.filter(vendedor=vend)
        else:
            metas = metas.filter(vendedor__ativo=True)
        dados['meta_t'] = float(sum(m.toneladas for m in metas)) or None
        dados['a_carregar_total'] = len(dados['a_carregar'])
        dados['a_carregar'] = dados['a_carregar'][:50]
        return Response(dados)


# ── Fila do interno ─────────────────────────────────────────────────────────

class FilaView(APIView):
    permission_classes = [EhInterno]

    def get(self, request):
        hoje = timezone.localdate()
        inicio = timezone.make_aware(datetime.combine(hoje, time.min))
        cadastros = (Produtor.objects.filter(cadastro='PROSPECT', cotacoes__status__in=Cotacao.ABERTOS)
                     .distinct().select_related('vendedor__user').order_by('criado_em'))
        ajustes = Produtor.objects.exclude(ajuste_cadastro='').select_related('vendedor__user').order_by('ajuste_pedido_em')
        pedidos = Cotacao.objects.filter(status='APROVADA').select_related('produtor', 'vendedor__user').order_by('aprovada_em')
        divergentes = Cotacao.objects.filter(status='LANCADA', divergente=True).select_related('produtor', 'vendedor__user')
        lancadas_hoje = Cotacao.objects.filter(lancado_em__gte=inicio).count()
        ctx = {'request': request}
        return Response({
            'cadastros': ProdutorSerializer(cadastros, many=True, context=ctx).data,
            'ajustes': ProdutorSerializer(ajustes, many=True, context=ctx).data,
            'pedidos': CotacaoSerializer(pedidos, many=True).data,
            'divergentes': CotacaoSerializer(divergentes, many=True).data,
            'lancadas_hoje': lancadas_hoje,
            'tempo_medio_h': _media_horas(Cotacao.objects.filter(lancado_em__gte=inicio - timedelta(days=30),
                                                                 aprovada_em__isnull=False), 'aprovada_em', 'lancado_em'),
        })


def _media_horas(qs, de: str, ate: str) -> float | None:
    difs = [(getattr(c, ate) - getattr(c, de)).total_seconds() / 3600 for c in qs if getattr(c, de) and getattr(c, ate)]
    return round(sum(difs) / len(difs), 1) if difs else None


# ── Painel da semana (gestor) ───────────────────────────────────────────────

class PainelView(APIView):
    permission_classes = [EhGestor]

    def get(self, request):
        hoje = timezone.localdate()
        try:
            ref = date.fromisoformat(request.query_params.get('semana') or hoje.isoformat())
        except ValueError:
            ref = hoje
        seg = ref - timedelta(days=ref.weekday())
        dom = seg + timedelta(days=6)
        tz = timezone.get_current_timezone()
        ini = timezone.make_aware(datetime.combine(seg, time.min), tz)
        fim = timezone.make_aware(datetime.combine(dom + timedelta(days=1), time.min), tz)
        mes_ini = timezone.make_aware(datetime.combine(ref.replace(day=1), time.min), tz)

        contatos = Contato.objects.filter(data_hora__gte=ini, data_hora__lt=fim).select_related('vendedor__user', 'produtor')
        por_vend: dict[str, int] = {}
        for c in contatos:
            nome = c.vendedor.nome if c.vendedor else 'Sem vendedor'
            por_vend[nome] = por_vend.get(nome, 0) + 1
        for v in VendedorAgro.objects.filter(ativo=True).select_related('user'):
            por_vend.setdefault(v.nome, 0)

        passos_vencidos = Contato.objects.filter(proximo_feito_em__isnull=True, proximo_data__lt=hoje).count()
        coletas = contatos.filter(produtor__coleta_oferecida=True).values('produtor').distinct().count()
        prospects = Produtor.objects.filter(origem='PROSPECT', criado_em__gte=ini, criado_em__lt=fim).count()

        cot_mes = Cotacao.objects.filter(criado_em__gte=mes_ini)
        aprovadas = cot_mes.filter(status__in=('APROVADA', 'LANCADA'))
        lancadas = cot_mes.filter(status='LANCADA').count()
        descontos, avista, pesos = 0.0, 0.0, 0.0
        for c in aprovadas:
            d, de = regras.desconto_pct(c.preco_final, c.preco_padrao), regras.desconto_efetivo(c.preco_final, c.prazo_final, c.preco_padrao)
            if d is None:
                continue
            w = float(c.volume_t)
            descontos, avista, pesos = descontos + d * w, avista + (de or 0) * w, pesos + w
        total_mes = cot_mes.count()

        dados = {
            'semana': {'inicio': seg, 'fim': dom},
            'contatos': contatos.count(),
            'passos_vencidos': passos_vencidos,
            'coletas_solo': coletas,
            'prospects_novos': prospects,
            'por_vendedor': sorted(({'nome': n, 'contatos': q} for n, q in por_vend.items()), key=lambda x: -x['contatos']),
            'cotacoes_mes': {
                'mes': ref.replace(day=1),
                'enviadas': total_mes,
                'aprovadas': aprovadas.count(),
                'aprovadas_direto': aprovadas.filter(aprovada_direto=True).count(),
                'contraproposta': cot_mes.filter(contra_preco__isnull=False).count(),
                'recusadas': cot_mes.filter(status='RECUSADA').count(),
                'desistiu': cot_mes.filter(status='DESISTIU').count(),
                'aguardando': cot_mes.filter(status='AGUARDANDO').count(),
                'lancadas': lancadas,
                'pct_lancadas': round(100 * lancadas / total_mes) if total_mes else None,
            },
            'desconto_medio': round(descontos / pesos, 1) if pesos else None,
            'desconto_medio_avista': round(avista / pesos, 1) if pesos else None,
            'resposta_media_h': _media_horas(cot_mes.filter(decidido_em__isnull=False, aprovada_direto=False),
                                             'criado_em', 'decidido_em'),
            'lancamento': {
                'pendentes': Cotacao.objects.filter(status='APROVADA').count()
                + Produtor.objects.filter(cadastro='PROSPECT', cotacoes__status__in=Cotacao.ABERTOS).distinct().count(),
                'tempo_medio_h': _media_horas(cot_mes.filter(lancado_em__isnull=False), 'aprovada_em', 'lancado_em'),
                'divergentes': Cotacao.objects.filter(status='LANCADA', divergente=True).count(),
            },
            'sem_contato': None,
        }
        try:
            dados['sem_contato'] = _sem_contato(hoje)
        except Exception as exc:
            logger.warning('Comercial Agro: painel sem carteira do SGA: %s', exc)
        return Response(dados)


def _sem_contato(hoje: date) -> dict:
    """Clientes da carteira (pedido agro em 24 meses) sem contato no app há 60+ dias."""
    reps = sorted({int(r) for v in VendedorAgro.objects.filter(ativo=True) for r in v.repcods})
    if not reps:
        return {'total': 0, 'clientes': []}
    carteira = erp_agro.pedidos(reps, hoje - timedelta(days=730), hoje + timedelta(days=1))
    ultima, nomes = {}, {}
    for p in carteira:
        nomes[p['cliente']] = p['nome']
        ultima[p['cliente']] = max(ultima.get(p['cliente'], p['data']), p['data'])
    corte = timezone.now() - timedelta(days=regras.SEM_CONTATO_DIAS)
    com_contato = set(Contato.objects.filter(data_hora__gte=corte, produtor__cliente_sga__isnull=False)
                      .values_list('produtor__cliente_sga', flat=True))
    lista = sorted(({'cliente': c, 'nome': nomes[c], 'ultima_compra': ultima[c]}
                    for c in nomes if c not in com_contato), key=lambda x: x['ultima_compra'], reverse=True)
    return {'total': len(lista), 'dias': regras.SEM_CONTATO_DIAS, 'clientes': lista[:100]}


# ── Vendedores e metas (gestor) ─────────────────────────────────────────────

GRUPO_VENDEDOR = 'agroVendedor'


def _nome_base(nome: str) -> str:
    """Nome para casar Comissões × SGA × Colaborador: sem acento, maiúsculo, sem "(REGIÃO)" no fim."""
    import re
    import unicodedata
    n = unicodedata.normalize('NFD', nome or '').encode('ascii', 'ignore').decode().upper()
    n = re.sub(r'\s*\([^)]*\)\s*$', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def _sincronizar_grupo(v: VendedorAgro, ativo: bool | None = None) -> None:
    """O menu e as rotas do front decidem por grupo: vendedor ativo fica em agroVendedor."""
    from django.contrib.auth.models import Group
    g, _ = Group.objects.get_or_create(name=GRUPO_VENDEDOR)
    if v.ativo if ativo is None else ativo:
        v.user.groups.add(g)
    else:
        v.user.groups.remove(g)


class VendedorViewSet(viewsets.ModelViewSet):
    serializer_class = VendedorAgroSerializer
    permission_classes = [EhGestor]
    queryset = VendedorAgro.objects.select_related('user').prefetch_related('metas')
    http_method_names = ['get', 'post', 'patch', 'delete']

    def perform_create(self, serializer):
        _sincronizar_grupo(serializer.save())

    def perform_update(self, serializer):
        antigo = serializer.instance.user
        v = serializer.save()
        if antigo != v.user:
            _sincronizar_grupo(VendedorAgro(user=antigo), ativo=False)
        _sincronizar_grupo(v)

    def perform_destroy(self, instance):
        _sincronizar_grupo(instance, ativo=False)
        instance.delete()

    @action(detail=True, methods=['post'])
    def meta(self, request, pk=None):
        v = self.get_object()
        ser = MetaAgroSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        MetaAgro.objects.update_or_create(vendedor=v, ano=ser.validated_data['ano'],
                                          defaults={'toneladas': ser.validated_data['toneladas']})
        return Response(self.get_serializer(self.get_queryset().get(pk=v.pk)).data)  # metas relidas

    @action(detail=True, methods=['post'], permission_classes=[EhGestor])
    def territorio(self, request, pk=None):
        """Põe/tira municípios do território do vendedor. Um município é de um vendedor só."""
        v = self.get_object()
        try:
            add = {int(i) for i in request.data.get('adicionar') or []}
            rem = {int(i) for i in request.data.get('remover') or []}
        except (TypeError, ValueError):
            return Response({'detail': 'Códigos IBGE inválidos.'}, status=400)
        with transaction.atomic():
            if add:
                for outro in VendedorAgro.objects.exclude(pk=v.pk).select_for_update():
                    resto = [i for i in (outro.municipios or []) if i not in add]
                    if len(resto) != len(outro.municipios or []):
                        outro.municipios = resto
                        outro.save(update_fields=['municipios'])
            v.municipios = sorted((set(v.municipios or []) | add) - rem)
            v.save(update_fields=['municipios'])
        return Response({'id': v.id, 'municipios': v.municipios})

    @action(detail=False, methods=['get'])
    def usuarios(self, request):
        q = (request.query_params.get('q') or '').strip()
        qs = User.objects.filter(is_active=True)
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        return Response([{'id': u.id, 'nome': u.get_full_name() or u.username, 'username': u.username}
                         for u in qs.order_by('first_name', 'username')[:30]])

    @action(detail=False, methods=['get'])
    def comissoes(self, request):
        """Vendedores cadastrados nas Comissões, com o usuário e os REPCOD do SGA sugeridos.

        As Comissões casam vendedor por NOME (Representante.nome ↔ REPNOME do SGA ↔ nome do
        Colaborador, que tem o usuário). Aqui faz o mesmo: Colaborador de mesmo nome → usuário;
        senão, usuário com o e-mail do representante. REPCOD = representantes do SGA com o mesmo
        nome sem o sufixo de região ("RODRIGO CHAVES CRUZ (FRONTEIRA)" → "RODRIGO CHAVES CRUZ").
        """
        from comissoes.models import Representante
        try:
            from avaliacoes.management.models import Colaborador
        except Exception:  # app de RH fora do ar não impede o cadastro
            Colaborador = None
        from pedidosVenda import erp as base
        try:
            sga = [r for r in base.representantes() if r.get('inativo') != 'S']
        except Exception as exc:
            logger.warning('Comercial Agro: representantes do SGA indisponíveis: %s', exc)
            sga = []
        por_nome: dict[str, list[int]] = {}
        for r in sga:
            por_nome.setdefault(_nome_base(r['nome']), []).append(int(r['cod']))
        colab = {}
        if Colaborador is not None:
            for c in Colaborador.objects.filter(user__isnull=False).select_related('user'):
                colab.setdefault(_nome_base(c.nome), c.user)
        ja = set(VendedorAgro.objects.values_list('user_id', flat=True))
        saida = []
        for r in Representante.objects.all().order_by('nome'):
            chave = _nome_base(r.nome)
            u = colab.get(chave)
            if u is None and r.email:
                u = User.objects.filter(email__iexact=r.email.strip(), is_active=True).first()
            saida.append({
                'id': r.id, 'nome': r.nome, 'segmento': r.segmento or '', 'empresa': r.empresa or '',
                'agro': 'AGRO' in (r.segmento or '').upper(),
                'user': u.id if u else None, 'user_nome': (u.get_full_name() or u.username) if u else '',
                'repcods': sorted(por_nome.get(chave, [])), 'ja_cadastrado': bool(u and u.id in ja),
            })
        saida.sort(key=lambda x: (not x['agro'], x['nome']))
        return Response(saida)

    @action(detail=False, methods=['get'])
    def representantes(self, request):
        from pedidosVenda import erp as base
        try:
            return Response([r for r in base.representantes() if r.get('inativo') != 'S'])
        except Exception as exc:
            return _erro_sga(exc)


# ── Dados públicos: mercado (IBGE/PAM), imóvel (CAR) e prospecção ──────────

from . import geo  # noqa: E402
import numpy as np  # noqa: E402

from . import concorrentes  # noqa: E402
from .models import AreaPlantada, BuscaCarMunicipio, CenarioMercado, ImovelCar, PedreiraAnm, UnidadeCalcario  # noqa: E402


def primeiro_mes(d: date, meses: int) -> date:
    """1º dia do mês `meses` antes (negativo) ou depois de d."""
    n = d.year * 12 + d.month - 1 + meses
    return date(n // 12, n % 12 + 1, 1)

CAR_VALIDADE_DIAS = 30
AREA_MINIMA_PADRAO = 50


# 20/11/2026: lavra em nome da DB na ANM (Caçapava do Sul). Não conta como concorrente; editável no cenário.
TITULARES_DB_PADRAO = ['DAGOBERTO BARCELLOS S/A']


def _culturas_todas() -> list[str]:
    """Ordem das culturas na resposta (e nas `partes` da visão Brasil)."""
    return list(geo.CULTURAS_PAM.values()) + [geo.MILHO_2A] + list(geo.PASTAGENS.values())


def _ano_pam() -> int | None:
    return (AreaPlantada.objects.exclude(cultura__in=list(geo.PASTAGENS.values()))
            .order_by('-ano').values_list('ano', flat=True).first())


def _gravar_pam(linhas: list[dict], ano: int, culturas_trocadas) -> None:
    with transaction.atomic():
        AreaPlantada.objects.filter(ano=ano, cultura__in=list(culturas_trocadas)).delete()
        AreaPlantada.objects.bulk_create([AreaPlantada(**l) for l in linhas], batch_size=2000, ignore_conflicts=True)


def importar_pam(com_pastagem: bool = False) -> dict:
    """PAM do Brasil (12 culturas) + milho 2ª safra; com_pastagem soma o Censo 2017 (~2 min).
    Tudo gravado no ano do PAM, que é o que a tela lê."""
    linhas = geo.baixar_pam('last 1')
    ano = max(l['ano'] for l in linhas)
    linhas = [l for l in linhas if l['ano'] == ano]
    try:
        milho2 = geo.baixar_milho_2a('last 1')
    except Exception as exc:
        logger.warning('Comercial Agro: sem milho 2ª safra: %s', exc)
        milho2 = []
    for l in milho2:
        l['ano'] = ano  # a 839 pode sair um ano depois do PAM: vale a última
    linhas = geo.separar_milho(linhas + milho2)
    _gravar_pam(linhas, ano, list(geo.CULTURAS_PAM.values()) + [geo.MILHO_2A])
    res = {'ano': ano, 'linhas': len(linhas), 'pastagem': 0}
    if com_pastagem:
        past = geo.baixar_pastagem()
        for l in past:
            l['ano'] = ano
        _gravar_pam(past, ano, geo.PASTAGENS.values())
        res['pastagem'] = len(past)
    return res


def _pam_garantido() -> int | None:
    """Ano do PAM no banco. Baixa o Brasil inteiro (~15 s) na primeira vez e quando o banco ainda não
    tem a separação do milho safrinha (antes de 20/11/2026). A pastagem só vem pelo `importar_pam`."""
    ano = _ano_pam()
    completo = ano is not None and AreaPlantada.objects.filter(ano=ano, municipio_ibge__lt=4300000, cultura=geo.MILHO_2A).exists()
    if not completo:
        ano = importar_pam()['ano']
    return ano


def importar_pedreiras() -> int:
    linhas = geo.baixar_pedreiras()
    if linhas:
        with transaction.atomic():
            PedreiraAnm.objects.all().delete()
            PedreiraAnm.objects.bulk_create([PedreiraAnm(**l) for l in linhas], ignore_conflicts=True)
    return len(linhas)


def _pedreiras() -> list[dict]:
    """Lavras de calcário agrícola da ANM; baixa na primeira vez (1 s). Falha não derruba a tela."""
    if not PedreiraAnm.objects.exists() and cache.add('comercialAgro:anm_tentou', 1, 3600):
        try:
            importar_pedreiras()
        except Exception as exc:
            logger.warning('Comercial Agro: ANM fora: %s', exc)
    return list(PedreiraAnm.objects.values('titular', 'uf', 'latitude', 'longitude', 'substancia'))


def _concorrencia(ibges, pedreiras: list[dict], titulares_db) -> dict[int, list[int]]:
    """Por município: quantas EMPRESAS (titulares distintos) concorrentes têm lavra a até 50/100/150/200/300 km."""
    try:
        cent = geo.centroides_municipios()
    except Exception as exc:
        logger.warning('Comercial Agro: sem centros dos municípios: %s', exc)
        return {}
    da_db = {t.strip().upper() for t in titulares_db}
    conc = [p for p in pedreiras if p['titular'].strip().upper() not in da_db]
    if not conc:
        return {}
    lats = np.array([float(p['latitude']) for p in conc])
    lngs = np.array([float(p['longitude']) for p in conc])
    nomes = {}
    tit = np.array([nomes.setdefault(p['titular'].strip().upper(), len(nomes)) for p in conc])
    saida = {}
    for i in ibges:
        c = cent.get(int(i))
        if not c:
            continue
        d = geo.distancias_km(c[0], c[1], lats, lngs)
        saida[int(i)] = [int(np.unique(tit[d <= r]).size) for r in geo.BRASIL_RAIOS_KM]
    return saida


def _redistribuir_canal(vendas: dict, desde, ate, reps, ano: int) -> tuple[dict, dict]:
    """Revenda/cooperativa com raio de atuação: tira o volume da cidade dela e espalha pelos municípios
    do raio, na proporção da lavoura. Devolve (vendas ajustadas, toneladas via canal por município)."""
    canais = list(Produtor.objects.filter(tipo__in=['REVENDA', 'COOPERATIVA'], raio_atuacao_km__gt=0, cliente_sga__isnull=False)
                  .values_list('cliente_sga', 'raio_atuacao_km'))
    if not canais:
        return vendas, {}
    try:
        porcli = erp_agro.vendas_por_cliente([c for c, _ in canais], desde, ate, reps)
        cent = geo.centroides_municipios()
    except Exception as exc:
        logger.warning('Comercial Agro: canal sem redistribuir: %s', exc)
        return vendas, {}
    ha = {r['municipio_ibge']: float(r['h']) for r in AreaPlantada.objects.filter(ano=ano)
          .exclude(cultura__in=list(geo.PASTAGENS.values())).values('municipio_ibge').annotate(h=Sum('hectares'))}
    ids = np.array(list(cent.keys()))
    lats = np.array([cent[i][0] for i in ids])
    lngs = np.array([cent[i][1] for i in ids])
    vendas = copy.deepcopy(vendas)
    canal: dict[int, float] = defaultdict(float)
    for cli, raio in canais:
        v = porcli.get(cli)
        c = cent.get(v['ibge']) if v else None
        if not v or v['toneladas'] <= 0 or not c:
            continue
        perto = ids[geo.distancias_km(c[0], c[1], lats, lngs) <= raio]
        pesos = {int(i): ha.get(int(i), 0.0) for i in perto}
        total = sum(pesos.values())
        if total <= 0:
            continue
        t = v['toneladas']
        if v['ibge'] in vendas:
            vendas[v['ibge']]['toneladas'] = max(0.0, vendas[v['ibge']]['toneladas'] - t)
        for i, w in pesos.items():
            if w > 0:
                x = t * w / total
                e = vendas.setdefault(i, {'clientes': 0, 'toneladas': 0.0, 'valor': 0.0})
                e['toneladas'] += x
                canal[i] += x
    return vendas, dict(canal)


def importar_cfem(caminho: str, ano_min: int | None = None) -> dict:
    """CFEM (arquivo baixado pelo navegador) → UnidadeCalcario. Liga o CNPJ ao nome pelos processos do SIGMINE."""
    ano_min = ano_min or timezone.localdate().year - 3
    linhas = concorrentes.limpar(concorrentes.ler_cfem(caminho, ano_min))
    processos = geo.baixar_processos_calcario()
    try:
        titulares = CenarioMercado.atual().titulares_db or TITULARES_DB_PADRAO
    except DatabaseError:
        titulares = TITULARES_DB_PADRAO
    if not PedreiraAnm.objects.exists():
        importar_pedreiras()
    try:
        cent = geo.centroides_municipios()
    except Exception as exc:
        logger.warning('Comercial Agro: CFEM sem centros dos municípios: %s', exc)
        cent = None
    unid = concorrentes.montar_unidades(linhas, processos, titulares,
                                        list(PedreiraAnm.objects.values('titular', 'latitude', 'longitude')), cent)
    with transaction.atomic():
        UnidadeCalcario.objects.all().delete()
        UnidadeCalcario.objects.bulk_create([UnidadeCalcario(**u) for u in unid], batch_size=1000)
    cache.delete('comercialAgro:abastecimento')
    return {'linhas': len(linhas), 'corrigidas': sum(1 for l in linhas if l.get('corrigida')), 'unidades': len(unid),
            'empresas_agro': len({u['cnpj'] for u in unid if u['agro']}), 'ate': unid[0]['ate'] if unid else ''}


def _abastecimento(ano: int) -> tuple[dict, dict]:
    """({ibge: {cnpj: t}}, {cnpj: empresa}) das empresas de calcário agrícola; cache de 1 dia por processo."""
    v = cache.get('comercialAgro:abastecimento')
    if v is not None:
        return v
    unid = list(UnidadeCalcario.objects.filter(agro=True, t_12m__gt=0).values(
        'cnpj', 'nome', 'municipio_ibge', 'municipio', 'uf', 'da_db', 't_12m', 't_12m_anterior', 'ate'))
    if not unid:
        return {}, {}
    try:
        cent = geo.centroides_municipios()
    except Exception as exc:
        logger.warning('Comercial Agro: abastecimento sem centros: %s', exc)
        return {}, {}
    ha = {r['municipio_ibge']: float(r['h']) for r in AreaPlantada.objects.filter(ano=ano)
          .exclude(cultura__in=list(geo.PASTAGENS.values())).values('municipio_ibge').annotate(h=Sum('hectares'))}
    abast = concorrentes.abastecimento(unid, cent, ha)
    empresas: dict[str, dict] = {}
    for u in unid:
        e = empresas.setdefault(u['cnpj'], {'cnpj': u['cnpj'], 'nome': u['nome'], 'db': u['da_db'], 't_12m': 0.0,
                                            't_12m_anterior': 0.0, 'unidades': [], 'ate': u['ate']})
        e['t_12m'] += u['t_12m']
        e['t_12m_anterior'] += u['t_12m_anterior']
        e['unidades'].append(f"{u['municipio']}/{u['uf']}")
    v = (abast, empresas)
    cache.set('comercialAgro:abastecimento', v, 86400)
    return v


def _sem_acento(t: str) -> str:
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', t or '') if unicodedata.category(c) != 'Mn').upper().strip()


def _campo(uf: int) -> dict[int, dict]:
    """O que os vendedores registraram dos produtores da UF: fornecedor atual, concorrente e preço, por município."""
    try:
        nomes = {_sem_acento(n): i for i, n in geo.municipios(uf).items()}
    except Exception:
        return {}
    saida: dict[int, dict] = {}
    qs = (Produtor.objects.exclude(municipio='').filter(Q(fornecedor_atual__gt='') | Q(concorrente_nome__gt=''))
          .values('municipio', 'fornecedor_atual', 'concorrente_nome', 'preco_concorrente'))
    for p in qs:
        i = nomes.get(_sem_acento(p['municipio']))
        if not i:
            continue
        c = saida.setdefault(i, {'produtores': 0, 'fornecedores': defaultdict(int), 'concorrentes': {}})
        c['produtores'] += 1
        if p['fornecedor_atual']:
            c['fornecedores'][p['fornecedor_atual']] += 1
        nome = (p['concorrente_nome'] or '').strip()
        if nome:
            k = _sem_acento(nome)
            x = c['concorrentes'].setdefault(k, {'nome': nome, 'n': 0, 'precos': []})
            x['n'] += 1
            if p['preco_concorrente']:
                x['precos'].append(float(p['preco_concorrente']))
    for c in saida.values():
        c['fornecedores'] = dict(c['fornecedores'])
        c['concorrentes'] = sorted(({'nome': x['nome'], 'n': x['n'],
                                     'preco_medio': round(sum(x['precos']) / len(x['precos']), 2) if x['precos'] else None}
                                    for x in c['concorrentes'].values()), key=lambda x: -x['n'])
    return saida


def _uf_param(request) -> int | None:
    """?uf=43 ou ?uf=RS → 43; ?uf=BR → None (Brasil por estado). Sem nada = RS."""
    v = (request.query_params.get('uf') or '43').strip().upper()
    if v == 'BR':
        return None
    if v.isdigit() and int(v) in geo.UFS:
        return int(v)
    return next((cod for cod, (sigla, _) in geo.UFS.items() if sigla == v), geo.UF_IBGE)


class MercadoView(APIView):
    """Potencial de calcário (IBGE/PAM) × vendido nos últimos 12 meses (SGA): por município de uma
    UF (`?uf=43`, padrão) ou, com `?uf=BR`, por estado — cada estado leva os hectares por cultura de
    cada município (`partes`), porque a regra verão × inverno do cenário é feita município a município."""
    permission_classes = [TemAcesso]

    def get(self, request):
        hoje = timezone.localdate()
        try:
            ano = _pam_garantido()
        except Exception as exc:
            logger.exception('Comercial Agro: SIDRA fora: %s', exc)
            return Response({'detail': 'Não consegui baixar a área plantada do IBGE agora.'}, status=503)
        if ano is None:
            return Response({'detail': 'Sem dados do IBGE.'}, status=503)
        uf = _uf_param(request)
        vid = request.query_params.get('vendedor')
        reps = _repcods_de(request) if vid or not ve_tudo(request.user) else None
        desde, ate = hoje - timedelta(days=365), hoje + timedelta(days=1)
        try:
            vendas = erp_agro.vendas_por_municipio(desde, ate, reps)
        except Exception as exc:
            return _erro_sga(exc)
        vendas, canal = _redistribuir_canal(vendas, desde, ate, reps, ano)
        try:
            mensal = erp_agro.vendas_mensais(primeiro_mes(hoje, -24), ate, reps)
        except Exception as exc:
            logger.warning('Comercial Agro: sem vendas por mês: %s', exc)
            mensal = []
        try:
            cen = CenarioMercado.atual()
            titulares = cen.titulares_db or TITULARES_DB_PADRAO
        except DatabaseError:
            titulares = TITULARES_DB_PADRAO
        pedreiras = _pedreiras()
        abast, empresas = _abastecimento(ano)
        culturas = _culturas_todas()
        dentro = (lambda i: i // 100000 == uf) if uf else (lambda i: i // 100000 in geo.UFS)

        mun: dict[int, dict] = {}
        areas = AreaPlantada.objects.filter(ano=ano)
        if uf:
            areas = areas.filter(municipio_ibge__gte=uf * 100000, municipio_ibge__lt=(uf + 1) * 100000)
        for a in areas.values_list('municipio_ibge', 'municipio', 'cultura', 'hectares'):
            m = mun.setdefault(a[0], {'ibge': a[0], 'municipio': a[1], 'hectares': 0.0, 'culturas': {}})
            m['hectares'] += float(a[3])
            m['culturas'][a[2]] = float(a[3])
        if uf:
            nomes = None
            for ibge in vendas:  # vendeu em município sem lavoura no PAM (ex.: cidade de revenda)
                if ibge not in mun and dentro(ibge):
                    if nomes is None:
                        try:
                            nomes = geo.municipios(uf)
                        except Exception:
                            nomes = {}
                    mun[ibge] = {'ibge': ibge, 'municipio': nomes.get(ibge, str(ibge)), 'hectares': 0.0, 'culturas': {}}
            linhas = list(mun.values())
            conc = _concorrencia([m['ibge'] for m in linhas], pedreiras, titulares)
            campo = _campo(uf)
            for m in linhas:
                v = vendas.get(m['ibge'], {})
                m.update(vendido_t=round(v.get('toneladas', 0.0), 1), clientes=v.get('clientes', 0), valor=v.get('valor', 0.0),
                         vendido_canal_t=round(canal.get(m['ibge'], 0.0), 1), conc=conc.get(m['ibge'], [0] * len(geo.BRASIL_RAIOS_KM)),
                         abastecimento={c: round(t, 1) for c, t in abast.get(m['ibge'], {}).items() if t >= 1},
                         campo=campo.get(m['ibge']))
        else:
            estados: dict[int, dict] = {}
            for cod, (sigla, nome) in geo.UFS.items():
                estados[cod] = {'ibge': cod, 'municipio': nome, 'sigla': sigla, 'hectares': 0.0, 'culturas': {},
                                'partes': [], 'partes_conc': [], 'vendido_t': 0.0, 'clientes': 0, 'valor': 0.0,
                                'vendido_canal_t': 0.0, 'municipios': 0}
            conc = _concorrencia(list(mun), pedreiras, titulares)
            zero = [0] * len(geo.BRASIL_RAIOS_KM)
            for m in mun.values():
                e = estados.get(m['ibge'] // 100000)
                if not e:
                    continue
                e['hectares'] += m['hectares']
                e['municipios'] += 1
                for c, h in m['culturas'].items():
                    e['culturas'][c] = e['culturas'].get(c, 0.0) + h
                e['partes'].append([round(m['culturas'].get(c, 0.0)) for c in culturas])
                e['partes_conc'].append(conc.get(m['ibge'], zero))
                ab = e.setdefault('abastecimento', {})
                for cnpj, t in abast.get(m['ibge'], {}).items():
                    ab[cnpj] = ab.get(cnpj, 0.0) + t
            for ibge, v in vendas.items():
                e = estados.get(ibge // 100000)
                if e:
                    e['vendido_t'] += v['toneladas']
                    e['clientes'] += v['clientes']
                    e['valor'] += v['valor']
                    e['vendido_canal_t'] += canal.get(ibge, 0.0)
            linhas = [e for e in estados.values() if e['hectares'] or e['vendido_t']]
            for e in linhas:
                e['vendido_t'], e['valor'] = round(e['vendido_t'], 1), round(e['valor'], 2)
                e['vendido_canal_t'] = round(e['vendido_canal_t'], 1)
                e['abastecimento'] = {c: round(t, 1) for c, t in e.get('abastecimento', {}).items() if t >= 1}
                e['culturas'] = {c: round(h) for c, h in e['culturas'].items()}

        for m in linhas:
            pot = geo.potencial_t(m['hectares'])
            m.update(hectares=round(m['hectares']), potencial_t=pot,
                     participacao=round(100 * m['vendido_t'] / pot, 1) if pot else None,
                     a_ganhar_t=round(max(0.0, pot - m['vendido_t']), 1))
        linhas.sort(key=lambda x: -x['a_ganhar_t'])
        fora = sum(v['toneladas'] for i, v in vendas.items() if not dentro(i))
        pot_total = sum(l['potencial_t'] for l in linhas)
        vend_total = sum(l['vendido_t'] for l in linhas)
        sigla, nome = geo.UFS[uf] if uf else ('BR', 'Brasil')
        return Response({
            'ano_pam': ano, 'dose_t_ha': geo.DOSE_T_HA, 'ciclo_anos': geo.CICLO_ANOS, 'culturas': culturas,
            'uf': uf or 'BR', 'uf_sigla': sigla, 'uf_nome': nome,
            'ufs': [{'codigo': c, 'sigla': s_, 'nome': n} for c, (s_, n) in sorted(geo.UFS.items(), key=lambda x: x[1][1])],
            'totais': {'hectares': round(sum(l['hectares'] for l in linhas)), 'potencial_t': round(pot_total),
                       'vendido_t': round(vend_total), 'vendido_fora_rs_t': round(fora), 'vendido_fora_t': round(fora),
                       'participacao': round(100 * vend_total / pot_total, 1) if pot_total else None,
                       'municipios_com_venda': sum(1 for l in linhas if l['vendido_t'] > 0)},
            'municipios': linhas,
            'raios_km': list(geo.BRASIL_RAIOS_KM),
            'pedreiras': [{'titular': p['titular'], 'uf': p['uf'], 'lat': float(p['latitude']), 'lng': float(p['longitude']),
                           'db': p['titular'].strip().upper() in {t.strip().upper() for t in titulares}} for p in pedreiras],
            'mensal': mensal,
            'empresas': {c: empresas[c] for c in {c for l in linhas for c in (l.get('abastecimento') or {})} if c in empresas},
            'territorio': {str(i): v.id for v in VendedorAgro.objects.filter(ativo=True) for i in (v.municipios or [])},
            'abracal': {'ano': geo.ABRACAL_ANO, 'consumo_t': {str(k): v for k, v in geo.CONSUMO_ABRACAL.items()},
                        'outros_t': geo.ABRACAL_OUTROS_T},
        })


def _cenario_json(c: CenarioMercado) -> dict:
    por = c.atualizado_por
    return {'t_ha': float(c.t_ha), 'dose_t_ha': float(c.dose_t_ha), 'ciclo_anos': c.ciclo_anos, 'culturas': c.culturas,
            'sem_duplo': c.sem_duplo, 'crescimento_pct': float(c.crescimento_pct),
            'por_uf': c.por_uf or {}, 'calibrar': c.calibrar, 'conc_raio_km': c.conc_raio_km,
            'conc_reducao_pct': float(c.conc_reducao_pct), 'conc_piso_pct': float(c.conc_piso_pct),
            'titulares_db': c.titulares_db or TITULARES_DB_PADRAO,
            'capacidade_mes_t': float(c.capacidade_mes_t) if c.capacidade_mes_t is not None else None,
            'atualizado_em': c.atualizado_em, 'atualizado_por': (por.get_full_name() or por.username) if por else None}


class CenarioMercadoView(APIView):
    """Cenário oficial do potencial da DB: todos leem; só o gestor salva."""

    def get_permissions(self):
        return [EhGestor()] if self.request.method == 'PUT' else [TemAcesso()]

    def get(self, request):
        try:
            return Response(_cenario_json(CenarioMercado.atual()))
        except DatabaseError as exc:  # migration 0004 ainda não aplicada: a tela segue com o padrão
            logger.warning('Comercial Agro: cenário do mercado sem tabela (migration 0004?): %s', exc)
            return Response({**_cenario_json(CenarioMercado()), 'pendente': True})

    def put(self, request):
        d = request.data
        erros = {}

        def numero(campo, minimo, maximo):
            try:
                v = float(d.get(campo))
            except (TypeError, ValueError):
                erros[campo] = 'Informe um número.'
                return None
            if not minimo <= v <= maximo:
                erros[campo] = f'Entre {minimo:g} e {maximo:g}.'
            return v

        t_ha, dose = numero('t_ha', 0, 20), numero('dose_t_ha', 0, 20)
        ciclo, cresc = numero('ciclo_anos', 1, 10), numero('crescimento_pct', 0, 200)
        culturas = d.get('culturas') or []
        validas = set(_culturas_todas())
        if not isinstance(culturas, list) or any(c not in validas for c in culturas):
            erros['culturas'] = 'Cultura desconhecida.'
        reducao = numero('conc_reducao_pct', 0, 100) if 'conc_reducao_pct' in d else 10.0
        piso = numero('conc_piso_pct', 0, 100) if 'conc_piso_pct' in d else 40.0
        raio = d.get('conc_raio_km', 100)
        if raio not in geo.BRASIL_RAIOS_KM:
            erros['conc_raio_km'] = f'Use {", ".join(str(r) for r in geo.BRASIL_RAIOS_KM)} km.'
        capacidade = d.get('capacidade_mes_t')
        if capacidade not in (None, ''):
            capacidade = numero('capacidade_mes_t', 0, 10_000_000)
        else:
            capacidade = None
        por_uf = {}
        for k, v in (d.get('por_uf') or {}).items():
            if not str(k).isdigit() or int(k) not in geo.UFS or not isinstance(v, dict):
                erros['por_uf'] = f'Estado inválido: {k}.'
                break
            item = {}
            for campo, lim in (('dose', (0, 20)), ('ciclo', (1, 10)), ('consumo_t', (0, 100_000_000))):
                x = v.get(campo)
                if x in (None, ''):
                    continue
                try:
                    x = float(x)
                except (TypeError, ValueError):
                    erros['por_uf'] = f'{geo.UFS[int(k)][0]}: {campo} inválido.'
                    break
                if not lim[0] <= x <= lim[1]:
                    erros['por_uf'] = f'{geo.UFS[int(k)][0]}: {campo} entre {lim[0]:g} e {lim[1]:g}.'
                    break
                item[campo] = int(x) if campo == 'ciclo' else round(x, 2)
            if item:
                por_uf[str(int(k))] = item
        titulares = [str(t).strip()[:120] for t in (d.get('titulares_db') or []) if str(t).strip()]
        if erros:
            return Response(erros, status=400)
        c = CenarioMercado.atual()
        c.t_ha, c.dose_t_ha, c.ciclo_anos, c.crescimento_pct = round(t_ha, 3), round(dose, 2), int(ciclo), round(cresc, 1)
        c.culturas, c.sem_duplo, c.atualizado_por = culturas, bool(d.get('sem_duplo', True)), request.user
        c.por_uf, c.calibrar, c.conc_raio_km = por_uf, bool(d.get('calibrar')), int(raio)
        c.conc_reducao_pct, c.conc_piso_pct, c.titulares_db = round(reducao, 1), round(piso, 1), titulares
        c.capacidade_mes_t = round(capacidade) if capacidade is not None else None
        c.save()
        return Response(_cenario_json(c))


class MercadoClientesView(APIView):
    """Clientes que compraram no município nos últimos 12 meses (o "Clientes que compraram" do mercado)."""
    permission_classes = [TemAcesso]

    def get(self, request, ibge):
        hoje = timezone.localdate()
        vid = request.query_params.get('vendedor')
        reps = _repcods_de(request) if vid or not ve_tudo(request.user) else None
        try:
            linhas = erp_agro.clientes_do_municipio(ibge, hoje - timedelta(days=365), hoje + timedelta(days=1), reps)
        except Exception as exc:
            return _erro_sga(exc)
        ligados = {p['cliente_sga']: p for p in Produtor.objects.filter(cliente_sga__in=[l['cliente'] for l in linhas])
                   .values('cliente_sga', 'id', 'tipo', 'raio_atuacao_km')}
        for l in linhas:
            p = ligados.get(l['cliente'])
            l['produtor'] = p['id'] if p else None
            l['tipo'] = p['tipo'] if p else None
            l['raio_atuacao_km'] = p['raio_atuacao_km'] if p else None
        return Response(linhas)


class MalhaView(APIView):
    permission_classes = [TemAcesso]

    def get(self, request):
        try:
            return Response(geo.malha(_uf_param(request)))
        except Exception as exc:
            logger.exception('Comercial Agro: malha do IBGE fora: %s', exc)
            return Response({'detail': 'Não consegui baixar o mapa dos municípios do IBGE.'}, status=503)


def _guardar_imovel(im: dict) -> ImovelCar:
    campos = {k: im.get(k) for k in ('municipio_ibge', 'municipio', 'area_ha', 'modulos_fiscais', 'status', 'tipo',
                                     'latitude', 'longitude', 'geometria', 'lavoura_ha', 'lavoura_pct', 'lavoura_ano')}
    obj, _ = ImovelCar.objects.update_or_create(codigo=im['codigo'], defaults=campos)
    return obj


def _imovel_json(o: ImovelCar, geometria=True, leve=False) -> dict:
    d = {'codigo': o.codigo, 'municipio_ibge': o.municipio_ibge, 'municipio': o.municipio, 'area_ha': float(o.area_ha),
         'modulos_fiscais': float(o.modulos_fiscais) if o.modulos_fiscais is not None else None,
         'status': o.status, 'latitude': float(o.latitude), 'longitude': float(o.longitude),
         'lavoura_ha': float(o.lavoura_ha) if o.lavoura_ha is not None else None,
         'lavoura_pct': float(o.lavoura_pct) if o.lavoura_pct is not None else None, 'lavoura_ano': o.lavoura_ano}
    if geometria:
        d['geometria'] = geo.simplificar(o.geometria) if leve and o.geometria else o.geometria
    return d


class CarPontoView(APIView):
    """Imóvel do CAR no ponto (check-in da visita), com o % de lavoura do MapBiomas se houver mapa."""
    permission_classes = [TemAcesso]

    def get(self, request):
        try:
            lat, lng = float(request.query_params['lat']), float(request.query_params['lng'])
        except (KeyError, TypeError, ValueError):
            return Response({'detail': 'Informe lat e lng.'}, status=400)
        try:
            im = geo.car_no_ponto(lat, lng)
        except Exception as exc:
            logger.exception('Comercial Agro: CAR fora: %s', exc)
            return Response({'detail': 'Não consegui consultar o CAR agora.'}, status=503)
        if not im:
            return Response({'imovel': None, 'mapa_lavoura': geo.mapa_lavoura() is not None})
        mapa = geo.mapa_lavoura()
        o = _guardar_imovel(geo.com_lavoura(im, mapa))
        ligado = Produtor.objects.filter(car_codigo=o.codigo).values('id', 'nome').first()
        return Response({'imovel': _imovel_json(o), 'produtor': ligado, 'mapa_lavoura': mapa is not None})


class CarCodigoView(APIView):
    permission_classes = [TemAcesso]

    def get(self, request, codigo):
        o = ImovelCar.objects.filter(codigo=codigo).first()
        if o is None:
            try:
                im = geo.car_codigo(codigo)
            except Exception as exc:
                logger.exception('Comercial Agro: CAR fora: %s', exc)
                return Response({'detail': 'Não consegui consultar o CAR agora.'}, status=503)
            if not im:
                return Response({'detail': 'Imóvel não encontrado no CAR.'}, status=404)
            o = _guardar_imovel(geo.com_lavoura(im, geo.mapa_lavoura()))
        return Response({'imovel': _imovel_json(o)})


class ProspeccaoView(APIView):
    """Imóveis do CAR de um município, com lavoura, cruzados com quem já tem contato ou compra."""
    permission_classes = [TemAcesso]

    def get(self, request):
        try:
            ibge = int(request.query_params['municipio'])
            minimo = float(request.query_params.get('min_ha') or AREA_MINIMA_PADRAO)
        except (KeyError, TypeError, ValueError):
            return Response({'detail': 'Escolha o município.'}, status=400)
        minimo = max(5.0, minimo)
        hoje = timezone.localdate()
        busca = BuscaCarMunicipio.objects.filter(municipio_ibge=ibge).first()
        velha = (busca is None or float(busca.area_minima) > minimo or request.query_params.get('atualizar')
                 or busca.buscado_em < timezone.now() - timedelta(days=CAR_VALIDADE_DIAS))
        mapa = geo.mapa_lavoura()
        if velha:
            try:
                imoveis = geo.car_municipio(ibge, minimo)
            except Exception as exc:
                logger.exception('Comercial Agro: CAR fora: %s', exc)
                return Response({'detail': 'Não consegui baixar os imóveis do CAR agora.'}, status=503)
            with transaction.atomic():
                for im in imoveis:
                    _guardar_imovel(geo.com_lavoura(im, mapa))
                BuscaCarMunicipio.objects.update_or_create(municipio_ibge=ibge, defaults={'area_minima': minimo, 'total': len(imoveis)})
        elif mapa:  # mapa importado depois da busca: completa a lavoura que faltou
            for o in ImovelCar.objects.filter(municipio_ibge=ibge, lavoura_ano__isnull=True, area_ha__gte=minimo):
                im = geo.com_lavoura({'area_ha': o.area_ha, 'geometria': o.geometria}, mapa)
                if im.get('lavoura_pct') is not None:
                    o.lavoura_ha, o.lavoura_pct, o.lavoura_ano = im['lavoura_ha'], im['lavoura_pct'], im['lavoura_ano']
                    o.save(update_fields=['lavoura_ha', 'lavoura_pct', 'lavoura_ano'])

        qs = list(ImovelCar.objects.filter(municipio_ibge=ibge, area_ha__gte=minimo).exclude(status='CA'))
        produtores = {p.car_codigo: p for p in Produtor.objects.filter(car_codigo__in=[o.codigo for o in qs])}
        recentes = set(Contato.objects.filter(produtor__in=produtores.values(),
                                              data_hora__gte=timezone.now() - timedelta(days=regras.SEM_CONTATO_DIAS))
                       .values_list('produtor_id', flat=True))
        try:
            ultimas = erp_agro.ultimas_compras([p.cliente_sga for p in produtores.values() if p.cliente_sga])
        except Exception as exc:
            logger.warning('Comercial Agro: prospecção sem compras do SGA: %s', exc)
            ultimas = {}
        corte = hoje - timedelta(days=regras.CLIENTE_ATIVO_DIAS)
        linhas = []
        for o in qs:
            p = produtores.get(o.codigo)
            ultima = ultimas.get(p.cliente_sga) if p and p.cliente_sga else None
            situacao = ('cliente' if ultima and ultima >= corte
                        else 'contato' if p and p.id in recentes
                        else 'ex_cliente' if ultima
                        else 'conhecido' if p else 'livre')
            linhas.append({**_imovel_json(o, leve=True), 'situacao': situacao,
                           'produtor': {'id': p.id, 'nome': p.nome, 'cliente_sga': p.cliente_sga,
                                        'ultima_compra': ultima} if p else None})
        chave = (lambda x: -(x['lavoura_ha'] or 0)) if mapa else (lambda x: -x['area_ha'])
        # Ex-cliente logo depois de "sem contato": é quem já comprou e parou — o mais fácil de recuperar.
        ordem = {'livre': 0, 'ex_cliente': 1, 'conhecido': 2, 'contato': 3, 'cliente': 4}
        linhas.sort(key=lambda x: (ordem[x['situacao']], chave(x)))
        pot = geo.potencial_t(sum(float(a.hectares) for a in AreaPlantada.objects.filter(
            municipio_ibge=ibge, ano=AreaPlantada.objects.order_by('-ano').values_list('ano', flat=True).first() or 0)))
        return Response({
            'municipio_ibge': ibge, 'municipio': qs[0].municipio if qs else '', 'area_minima': minimo,
            'buscado_em': BuscaCarMunicipio.objects.filter(municipio_ibge=ibge).values_list('buscado_em', flat=True).first(),
            'mapa_lavoura': mapa.ano if mapa else None, 'potencial_t': pot,
            'resumo': {s: sum(1 for l in linhas if l['situacao'] == s) for s in ordem},
            'imoveis': linhas,
        })
