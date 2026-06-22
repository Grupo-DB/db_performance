import base64
import os
import threading
from email.mime.image import MIMEImage
from io import BytesIO

import django_filters
import pandas as pd
from sqlalchemy import create_engine, text

from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django_filters.rest_framework import DjangoFilterBackend

from .models import (
    Fabricante, Equipamento, Veiculo, Secao, Item, Pedido, ItemPedido, AnexoPedido,
    PedidoNotificacao, CatalogoPDF, ItemErpCatalogo, EquipamentoCatalogo,
)
from .serializers import (
    FabricanteSerializer, EquipamentoSerializer,
    VeiculoListSerializer, VeiculoDetailSerializer, VeiculoCreateUpdateSerializer,
    SecaoSerializer, SecaoCreateUpdateSerializer,
    ItemListSerializer, ItemDetailSerializer, ItemCreateUpdateSerializer,
    PedidoListSerializer, PedidoDetailSerializer, PedidoCreateSerializer,
    PedidoUpdateStatusSerializer, PedidoNotificacaoSerializer,
    AnexoPedidoSerializer, CatalogoPDFSerializer, ItemErpCatalogoSerializer,
    EquipamentoCatalogoSerializer,
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

    # Enriquecer com mapeamento por equipamento/marca (em lote, sem N+1)
    marcas = {str(r['MARCA']) for r in records if r.get('MARCA')}
    mapeamentos_eq = {
        m.marca_erp: m
        for m in EquipamentoCatalogo.objects.filter(marca_erp__in=marcas).select_related('equipamento', 'catalogo')
    }

    for record in records:
        marca = str(record.get('MARCA') or '')
        mapa = mapeamentos_eq.get(marca)
        if mapa and mapa.catalogo:
            record['equipamento_nome'] = mapa.equipamento.nome if mapa.equipamento else marca
            record['catalogo_id'] = mapa.catalogo.id
            record['catalogo_titulo'] = mapa.catalogo.titulo
            record['catalogo_arquivo'] = (
                request.build_absolute_uri(mapa.catalogo.arquivo.url)
                if mapa.catalogo.arquivo else None
            )
        else:
            record['equipamento_nome'] = marca
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


_EMAIL_COMPRAS = ['suprimentos@grupodb.com.br']
_EMAIL_CC      = ['jiangoersch@grupodb.com.br']


def _enviar_email_novo_pedido(pedido):
    # Cores da identidade visual
    AZUL    = '#004EAE'
    LARANJA = '#FFB100'
    VERDE   = '#00B036'
    CIANO   = '#00CFDD'

    itens = list(pedido.itens_pedido.all())
    solicitante = pedido.usuario.get_full_name() or pedido.usuario.username
    data_criacao = pedido.created_at.strftime('%d/%m/%Y %H:%M')

    linhas_txt = '\n'.join(
        f"  - {i.nome_produto or i.cod_erp} | Qtd: {i.quantidade} | "
        f"R$ {float(i.preco_unitario):.2f} un. | Subtotal: R$ {float(i.subtotal):.2f}"
        for i in itens
    )

    linhas_html = ''.join(
        f"<tr style=\"background:{'#f7fbff' if idx % 2 == 0 else '#fff'}\">"
        f"<td style='padding:9px 14px;border-bottom:1px solid #e8eef5;color:#444;font-size:13px'>{i.cod_erp or '-'}</td>"
        f"<td style='padding:9px 14px;border-bottom:1px solid #e8eef5;color:#222;font-size:13px'>{i.nome_produto or '-'}</td>"
        f"<td style='padding:9px 14px;border-bottom:1px solid #e8eef5;text-align:center;color:#444;font-size:13px'>{i.quantidade}</td>"
        f"<td style='padding:9px 14px;border-bottom:1px solid #e8eef5;text-align:right;color:#444;font-size:13px'>R$ {float(i.preco_unitario):.2f}</td>"
        f"<td style='padding:9px 14px;border-bottom:1px solid #e8eef5;text-align:right;font-weight:700;color:{AZUL};font-size:13px'>R$ {float(i.subtotal):.2f}</td>"
        f"</tr>"
        for idx, i in enumerate(itens)
    )

    corpo_txt = (
        f"Novo pedido de compra criado no sistema ManagerDB.\n\n"
        f"Número:       {pedido.numero_referencia}\n"
        f"Solicitante:  {solicitante}\n"
        f"Data:         {data_criacao}\n"
        f"Total:        R$ {float(pedido.total):.2f}\n"
        f"Observações:  {pedido.observacoes or '—'}\n\n"
        f"Itens:\n{linhas_txt}\n"
    )

    corpo_html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef2f7;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#eef2f7;padding:32px 16px">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%">

  <!-- ===== HEADER ===== -->
  <!-- Barra de topo colorida -->
  <tr>
    <td style="padding:0;line-height:0;font-size:0;border-radius:12px 12px 0 0;overflow:hidden">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td width="33%" style="background:{AZUL};height:6px">&nbsp;</td>
        <td width="33%" style="background:{LARANJA};height:6px">&nbsp;</td>
        <td width="34%" style="background:{VERDE};height:6px">&nbsp;</td>
      </tr></table>
    </td>
  </tr>
  <!-- Logo em fundo branco -->
  <tr>
    <td style="background:#ffffff;padding:20px 32px;border-left:1px solid #e8eef5;border-right:1px solid #e8eef5">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td style="vertical-align:middle">
            <img src="cid:logo_db" alt="Grupo Dagoberto Barcellos" height="72" style="display:block;border:0">
          </td>
          <td align="right" style="vertical-align:middle">
            <p style="margin:0;color:{AZUL};font-size:11px;letter-spacing:1px;text-transform:uppercase;font-weight:700">Sistema ManagerDB</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- Faixa separadora azul -->
  <tr>
    <td style="padding:0;line-height:0;font-size:0">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="background:{AZUL};height:4px">&nbsp;</td>
      </tr></table>
    </td>
  </tr>

  <!-- ===== TÍTULO ===== -->
  <tr>
    <td style="background:#fff;padding:28px 32px 20px">
      <h1 style="margin:0 0 6px;font-size:22px;font-weight:700;color:{AZUL}">Novo Pedido de Compra</h1>
      <p style="margin:0;font-size:14px;color:#888">Referência: <strong style="color:{CIANO}">{pedido.numero_referencia}</strong></p>
    </td>
  </tr>

  <!-- ===== DADOS DO PEDIDO ===== -->
  <tr>
    <td style="background:#fff;padding:0 32px 24px">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="background:#f0f7ff;border-radius:8px;border-left:4px solid {CIANO}">
        <tr>
          <td style="padding:18px 20px">
            <table width="100%" cellpadding="5" cellspacing="0" border="0" style="font-size:14px">
              <tr>
                <td style="color:#888;width:130px;white-space:nowrap">Solicitante</td>
                <td style="color:#111;font-weight:700">{solicitante}</td>
              </tr>
              <tr>
                <td style="color:#888">Data / Hora</td>
                <td style="color:#333">{data_criacao}</td>
              </tr>
              <tr>
                <td style="color:#888;vertical-align:top">Observações</td>
                <td style="color:#333">{pedido.observacoes or '—'}</td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- ===== TABELA DE ITENS ===== -->
  <tr>
    <td style="background:#fff;padding:0 32px 28px">
      <p style="margin:0 0 14px;font-size:13px;font-weight:700;color:{AZUL};text-transform:uppercase;letter-spacing:0.8px">
        Itens do Pedido
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;border-radius:8px;overflow:hidden">
        <thead>
          <tr style="background:{AZUL}">
            <th style="padding:11px 14px;text-align:left;color:#fff;font-size:12px;font-weight:600;letter-spacing:0.3px">Código</th>
            <th style="padding:11px 14px;text-align:left;color:#fff;font-size:12px;font-weight:600;letter-spacing:0.3px">Produto</th>
            <th style="padding:11px 14px;text-align:center;color:#fff;font-size:12px;font-weight:600;letter-spacing:0.3px">Qtd</th>
            <th style="padding:11px 14px;text-align:right;color:#fff;font-size:12px;font-weight:600;letter-spacing:0.3px">Unitário</th>
            <th style="padding:11px 14px;text-align:right;color:{LARANJA};font-size:12px;font-weight:600;letter-spacing:0.3px">Subtotal</th>
          </tr>
        </thead>
        <tbody>{linhas_html}</tbody>
        <tfoot>
          <tr style="background:{AZUL}">
            <td colspan="4" style="padding:12px 14px;text-align:right;color:#fff;font-size:14px;font-weight:700">
              Total do Pedido
            </td>
            <td style="padding:12px 14px;text-align:right;color:{LARANJA};font-size:18px;font-weight:700">
              R$ {float(pedido.total):.2f}
            </td>
          </tr>
        </tfoot>
      </table>
    </td>
  </tr>

  <!-- ===== FOOTER ===== -->
  <tr>
    <td style="background:{AZUL};border-radius:0 0 12px 12px;padding:16px 32px;text-align:center">
      <p style="margin:0;color:rgba(255,255,255,0.5);font-size:11px;letter-spacing:0.3px">
        Email automático gerado pelo sistema ManagerDB &mdash; Grupo Dagoberto Barcellos
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    msg = EmailMultiAlternatives(
        subject=f'[Novo Pedido] {pedido.numero_referencia} — {solicitante}',
        body=corpo_txt,
        to=_EMAIL_COMPRAS,
        cc=_EMAIL_CC,
    )
    msg.mixed_subtype = 'related'
    msg.attach_alternative(corpo_html, 'text/html')

    logo_path = os.path.join(settings.MEDIA_ROOT, 'logoNovoDb.png')
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as f:
            logo = MIMEImage(f.read())
        logo.add_header('Content-ID', '<logo_db>')
        logo.add_header('Content-Disposition', 'inline', filename='logoNovoDb.png')
        msg.attach(logo)

    msg.send(fail_silently=True)


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

class PedidoFilter(django_filters.FilterSet):
    usuario = django_filters.NumberFilter(field_name='usuario__id')

    class Meta:
        model = Pedido
        fields = ['status', 'usuario']


class PedidoViewSet(viewsets.ModelViewSet):
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = PedidoFilter
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

    def perform_create(self, serializer):
        super().perform_create(serializer)
        pedido = serializer.instance
        threading.Thread(
            target=_enviar_email_novo_pedido,
            args=(pedido,),
            daemon=True,
        ).start()

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


class EquipamentoCatalogoViewSet(viewsets.ModelViewSet):
    queryset = EquipamentoCatalogo.objects.select_related('equipamento', 'catalogo').all()
    serializer_class = EquipamentoCatalogoSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['equipamento']
    search_fields = ['marca_erp']
    ordering_fields = ['marca_erp', 'created_at']
    ordering = ['marca_erp']


class AnexoPedidoViewSet(viewsets.ModelViewSet):
    serializer_class = AnexoPedidoSerializer
    http_method_names = ['get', 'post', 'delete']

    def get_queryset(self):
        return AnexoPedido.objects.filter(pedido_id=self.kwargs['pedido_pk'])

    def perform_create(self, serializer):
        serializer.save(pedido_id=self.kwargs['pedido_pk'])


@api_view(['GET'])
def serve_catalogo_pdf_inline(request, pk):
    catalogo = get_object_or_404(CatalogoPDF, pk=pk)
    if not catalogo.arquivo:
        raise Http404
    response = FileResponse(catalogo.arquivo.open('rb'), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{catalogo.titulo}.pdf"'
    return response
