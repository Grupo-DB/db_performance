import base64
from io import BytesIO

import pandas as pd
from sqlalchemy import create_engine, text

from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django_filters.rest_framework import DjangoFilterBackend

from .models import (
    Fabricante, Equipamento, Veiculo, Secao, Item, Pedido, ItemPedido,
    PedidoNotificacao, CatalogoPDF, ItemErpCatalogo,
)
from .serializers import (
    FabricanteSerializer, EquipamentoSerializer,
    VeiculoListSerializer, VeiculoDetailSerializer, VeiculoCreateUpdateSerializer,
    SecaoSerializer, SecaoCreateUpdateSerializer,
    ItemListSerializer, ItemDetailSerializer, ItemCreateUpdateSerializer,
    PedidoListSerializer, PedidoDetailSerializer, PedidoCreateSerializer,
    PedidoUpdateStatusSerializer, PedidoNotificacaoSerializer,
    CatalogoPDFSerializer, ItemErpCatalogoSerializer,
)

# ---------------------------------------------------------------------------
# Configuração ERP
#usar este ip para o env local 45.6.118.50:65530
# ---------------------------------------------------------------------------
_ERP_CONN = (
    'mssql+pyodbc://DBCONSULTA:%21%40%23123qweQWE@172.10.27.51:1433/DB'
    '?driver=ODBC+Driver+17+for+SQL+Server'
)

_CONSULTA_PRODUTOS_SQL = text("""
    SELECT
        GALMCOD,
        GALMNOME,
        ESTQCOD,
        ESTQNOME,
        ESTQREF   REF,
        ESPSIGLA,
        MESTNOME  MARCA,
        COALESCE(QESTQESTOQUE, 0) ESTOQUE,
        COALESCE(QESTQCUSTO,   0) CUSTO,
        CASE WHEN QESTQLOC1 IS NOT NULL THEN QESTQLOC1 ELSE ESTQLOC1 END ALMOXARIFADO,
        CASE WHEN QESTQLOC2 IS NOT NULL THEN QESTQLOC2 ELSE ESTQLOC2 END PRATELEIRA,
        CASE WHEN QESTQLOC3 IS NOT NULL THEN QESTQLOC3 ELSE ESTQLOC3 END COLUNA,
        CASE WHEN QESTQLOC4 IS NOT NULL THEN QESTQLOC4 ELSE ESTQLOC4 END BOX
    FROM ESTOQUE
    JOIN ESPECIE           ON ESPCOD  = ESTQESP
    LEFT JOIN QUANTESTOQUE ON QESTQESTQ = ESTQCOD AND QESTQEMP = 1 AND QESTQFIL = 0
    JOIN GRUPOALMOXARIFADO ON GALMCOD   = ESTQGALM
    LEFT JOIN MARCAESTOQUE ON MESTCOD   = ESTQMEST
    WHERE ESTQGALM IN (
        SELECT G1.GALMCOD
        FROM GRUPOALMOXARIFADO G1
        LEFT JOIN GRUPOALMOXARIFADO G2 ON G2.GALMCOD = G1.GALMGALMPAI
        LEFT JOIN GRUPOALMOXARIFADO G3 ON G3.GALMCOD = G2.GALMGALMPAI
        LEFT JOIN GRUPOALMOXARIFADO G4 ON G4.GALMCOD = G3.GALMGALMPAI
        LEFT JOIN GRUPOALMOXARIFADO G5 ON G5.GALMCOD = G4.GALMGALMPAI
        LEFT JOIN GRUPOALMOXARIFADO G6 ON G6.GALMCOD = G5.GALMGALMPAI
        WHERE G1.GALMBLOQ <> 'S'
    )
    ORDER BY GALMNOME, GALMCOD, ESTQNOME, ESTQCOD
""")

_CONSULTA_IMAGEM_SQL = text("""
    SELECT ESTQFFOTO
    FROM ESTOQUEFOTO
    WHERE ESTQFESTQ = :cod_produto
""")


def _get_erp_engine():
    return create_engine(_ERP_CONN)


def _bmp_bytes_to_base64_png(image_data) -> str | None:
    """Converte dados BMP (bytes ou hex string '0x...') para PNG em base64."""
    try:
        from PIL import Image

        if isinstance(image_data, (bytes, bytearray)):
            raw = bytes(image_data)
        elif isinstance(image_data, str) and image_data.startswith('0x'):
            raw = bytes.fromhex(image_data[2:])
        else:
            return None

        img = Image.open(BytesIO(raw))
        buf = BytesIO()
        img.save(buf, format='PNG')
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception:
        return None


def _df_to_records(df: pd.DataFrame) -> list:
    """Converte DataFrame para list de dicts serializáveis (NaN → None)."""
    return df.where(pd.notna(df), other=None).to_dict(orient='records')


# ---------------------------------------------------------------------------
# Views ERP
# ---------------------------------------------------------------------------

@csrf_exempt
@api_view(['GET', 'POST'])
def consultar_produtos(request):
    """
    Retorna a lista de produtos do ERP como JSON.
    Suporta filtro opcional por ?busca= (nome/referência).
    Inclui cod_catalogo e url do catálogo PDF se houver mapeamento cadastrado.
    """
    try:
        engine = _get_erp_engine()
        df = pd.read_sql(_CONSULTA_PRODUTOS_SQL, engine)
    except Exception as exc:
        return Response({'erro': f'Falha na consulta ERP: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

    busca = (request.GET.get('busca') or request.data.get('busca', '')).strip()
    if busca:
        mask = (
            df['ESTQNOME'].str.contains(busca, case=False, na=False) |
            df['REF'].str.contains(busca, case=False, na=False)
        )
        df = df[mask]

    records = _df_to_records(df)

    # Enriquecer com mapeamento catálogo (em lote, sem N+1)
    cod_erp_list = [str(r['ESTQCOD']) for r in records if r.get('ESTQCOD') is not None]
    mapeamentos = {
        m.cod_erp: m
        for m in ItemErpCatalogo.objects.filter(cod_erp__in=cod_erp_list).select_related('catalogo')
    }

    for record in records:
        cod = str(record.get('ESTQCOD', ''))
        mapa = mapeamentos.get(cod)
        if mapa:
            record['cod_catalogo'] = mapa.cod_catalogo
            record['catalogo_id'] = mapa.catalogo_id
            record['catalogo_titulo'] = mapa.catalogo.titulo if mapa.catalogo else None
            record['catalogo_arquivo'] = (
                request.build_absolute_uri(mapa.catalogo.arquivo.url)
                if mapa.catalogo and mapa.catalogo.arquivo
                else None
            )
        else:
            record['cod_catalogo'] = None
            record['catalogo_id'] = None
            record['catalogo_titulo'] = None
            record['catalogo_arquivo'] = None

    return Response(records)


@csrf_exempt
@api_view(['GET', 'POST'])
def consultar_imagem_produto(request):
    """
    Retorna a imagem do produto em base64 PNG.
    Parâmetro: cod_produto (GET query ou POST body).
    """
    cod_produto = request.GET.get('cod_produto') or request.data.get('cod_produto')
    if not cod_produto:
        return Response({'erro': "'cod_produto' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        engine = _get_erp_engine()
        df = pd.read_sql(_CONSULTA_IMAGEM_SQL, engine, params={'cod_produto': cod_produto})
    except Exception as exc:
        return Response({'erro': f'Falha na consulta ERP: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

    if df.empty or df['ESTQFFOTO'].iloc[0] is None:
        return Response({'imagem': None})

    b64 = _bmp_bytes_to_base64_png(df['ESTQFFOTO'].iloc[0])
    if b64 is None:
        return Response({'imagem': None})

    return Response({'imagem': f'data:image/png;base64,{b64}'})


# ---------------------------------------------------------------------------
# ViewSets existentes
# ---------------------------------------------------------------------------

class FabricanteViewSet(viewsets.ModelViewSet):
    queryset = Fabricante.objects.all()
    serializer_class = FabricanteSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nome']
    ordering_fields = ['nome', 'created_at']


class EquipamentoViewSet(viewsets.ModelViewSet):
    queryset = Equipamento.objects.all()
    serializer_class = EquipamentoSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nome']
    ordering_fields = ['nome', 'created_at']
    ordering = ['nome']


class VeiculoViewSet(viewsets.ModelViewSet):
    queryset = Veiculo.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['fabricante', 'equipamento', 'ativo']
    search_fields = ['nome', 'modelo', 'descricao']
    ordering_fields = ['nome', 'modelo', 'created_at']
    ordering = ['nome']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return VeiculoDetailSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return VeiculoCreateUpdateSerializer
        return VeiculoListSerializer


class SecaoViewSet(viewsets.ModelViewSet):
    queryset = Secao.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['veiculo', 'ativo']
    search_fields = ['nome', 'descricao']
    ordering_fields = ['nome', 'created_at']
    ordering = ['nome']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return SecaoCreateUpdateSerializer
        return SecaoSerializer


class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['veiculo', 'secao', 'ativo']
    search_fields = ['nome', 'apelido', 'descricao', 'cod_catalogo', 'cod_minerion', 'referencia']
    ordering_fields = ['nome', 'preco', 'created_at']
    ordering = ['nome']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ItemDetailSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ItemCreateUpdateSerializer
        return ItemListSerializer


# ---------------------------------------------------------------------------
# Notificações helpers
# ---------------------------------------------------------------------------

_STATUS_NOTIFICACAO = {
    'SOLICITADO':    ('CRIACAO',          'Pedido {ref} foi reenviado para análise.'),
    'ACEITO':        ('STATUS_RECEBIDO',  'Pedido {ref} foi aceito pelo setor de compras.'),
    'REJEITADO':     ('STATUS_REJEITADO', 'Pedido {ref} foi rejeitado.'),
    'COTACAO':       ('STATUS_COTACAO',   'Pedido {ref} está em cotação.'),
    'REALIZADO':     ('STATUS_REALIZADO', 'Pedido {ref} foi realizado.'),
    'EM_TRANSPORTE': ('STATUS_REALIZADO', 'Pedido {ref} está em transporte.'),
    'FINALIZADO':    ('STATUS_REALIZADO', 'Pedido {ref} foi finalizado.'),
}


def _notificar_usuario(pedido, tipo, mensagem):
    PedidoNotificacao.objects.create(
        pedido=pedido,
        usuario_notificado=pedido.usuario,
        tipo=tipo,
        mensagem=mensagem,
    )


def _notificar_compras(pedido, tipo, mensagem):
    """Notifica todos os usuários staff (equipe de compras)."""
    staff = User.objects.filter(is_staff=True, is_active=True).exclude(id=pedido.usuario_id)
    notificacoes = [
        PedidoNotificacao(pedido=pedido, usuario_notificado=u, tipo=tipo, mensagem=mensagem)
        for u in staff
    ]
    PedidoNotificacao.objects.bulk_create(notificacoes)


def _processar_notificacoes(pedido, novo_status, motivo=None):
    if novo_status not in _STATUS_NOTIFICACAO:
        return
    tipo, template = _STATUS_NOTIFICACAO[novo_status]
    mensagem = template.format(ref=pedido.numero_referencia)
    if novo_status == 'REJEITADO' and motivo:
        mensagem += f' Motivo: {motivo}'

    # Novo pedido solicitado → avisa compras; demais → avisa solicitante
    if novo_status == 'SOLICITADO':
        _notificar_compras(pedido, tipo, mensagem)
    else:
        _notificar_usuario(pedido, tipo, mensagem)


# ---------------------------------------------------------------------------
# ViewSets de Pedido
# ---------------------------------------------------------------------------

class PedidoViewSet(viewsets.ModelViewSet):
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['status', 'usuario', 'created_at']
    ordering_fields = ['created_at', 'numero_referencia', 'status']
    ordering = ['-created_at']
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return PedidoCreateSerializer
        elif self.action == 'retrieve':
            return PedidoDetailSerializer
        elif self.action == 'update_status':
            return PedidoUpdateStatusSerializer
        return PedidoListSerializer

    def get_queryset(self):
        return Pedido.objects.all()

    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        pedido = self.get_object()
        serializer = PedidoUpdateStatusSerializer(pedido, data=request.data, partial=True)
        if serializer.is_valid():
            novo_status = serializer.validated_data.get('status', pedido.status)
            motivo = serializer.validated_data.get('motivo_rejeicao')
            serializer.save()
            _processar_notificacoes(pedido, novo_status, motivo=motivo)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def assumir(self, request, pk=None):
        pedido = self.get_object()
        pedido.responsavel = request.user
        pedido.save(update_fields=['responsavel'])
        return Response(PedidoDetailSerializer(pedido).data)

    @action(detail=True, methods=['post'])
    def liberar(self, request, pk=None):
        pedido = self.get_object()
        pedido.responsavel = None
        pedido.save(update_fields=['responsavel'])
        return Response(PedidoDetailSerializer(pedido).data)


class PedidoNotificacaoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PedidoNotificacaoSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['lido']
    ordering = ['-created_at']

    def get_queryset(self):
        return PedidoNotificacao.objects.filter(usuario_notificado=self.request.user)

    @action(detail=False, methods=['post'])
    def marcar_como_lido(self, request):
        ids = request.data.get('notificacao_ids', [])
        PedidoNotificacao.objects.filter(
            id__in=ids,
            usuario_notificado=request.user,
        ).update(lido=True)
        return Response({'status': 'notificacoes marcadas como lidas'})

    @action(detail=False, methods=['get'])
    def nao_lidas(self, request):
        count = PedidoNotificacao.objects.filter(
            usuario_notificado=request.user,
            lido=False,
        ).count()
        return Response({'nao_lidas': count})


# ---------------------------------------------------------------------------
# ViewSets de Catálogo
# ---------------------------------------------------------------------------

class CatalogoPDFViewSet(viewsets.ModelViewSet):
    queryset = CatalogoPDF.objects.select_related('veiculo').all()
    serializer_class = CatalogoPDFSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['veiculo']
    search_fields = ['titulo', 'descricao']
    ordering_fields = ['titulo', 'created_at']
    ordering = ['-created_at']


class ItemErpCatalogoViewSet(viewsets.ModelViewSet):
    queryset = ItemErpCatalogo.objects.select_related('catalogo').all()
    serializer_class = ItemErpCatalogoSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['catalogo']
    search_fields = ['cod_erp', 'nome_erp', 'cod_catalogo']
    ordering_fields = ['cod_erp', 'created_at']
    ordering = ['cod_erp']
