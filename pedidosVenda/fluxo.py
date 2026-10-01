"""
Andamento do pedido de venda e os avisos de cada passo.

    RASCUNHO ──enviar──▶ ENVIADO ──assumir──▶ EM_LANCAMENTO ──lançar──▶ LANCADO
        │                  ▲  │                    │
        │ (desconto acima  │  └──────devolver──────┴──▶ DEVOLVIDO ──enviar──▶ ...
        │  do teto)        │aprovar
        └──▶ AGUARDANDO_APROVACAO ──reprovar──▶ DEVOLVIDO

Cada função valida a transição, grava o evento da linha do tempo e dispara os
avisos (sino sempre; WhatsApp quando o perfil tem telefone e o template está
configurado). Erro de regra sobe como `FluxoErro`, que a view devolve como 400.
"""
import logging
from decimal import Decimal
from threading import Thread

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from .models import PedidoVenda, PedidoVendaEvento, PedidoVendaNotificacao, VendedorPerfil

logger = logging.getLogger(__name__)

GRUPOS_GESTAO = ('Admin', 'Master', 'vendasGestao')
# Diferença de arredondamento aceita entre o preço que o vendedor viu e o do ERP.
TOLERANCIA_PRECO = Decimal('0.005')


class FluxoErro(Exception):
    pass


def eh_gestor(user) -> bool:
    return bool(user and user.is_authenticated and (
        user.is_superuser or user.groups.filter(name__in=GRUPOS_GESTAO).exists()
    ))


def perfil_de(user) -> VendedorPerfil | None:
    return VendedorPerfil.objects.select_related('interno__user').filter(user=user, ativo=True).first()


def _brl(valor) -> str:
    texto = f'{Decimal(valor):,.2f}'
    return 'R$ ' + texto.replace(',', '_').replace('.', ',').replace('_', '.')


def _pct(valor) -> str:
    return f'{Decimal(valor):.2f}'.replace('.', ',') + '%'


def _nome(user) -> str:
    return (user.get_full_name() or user.username) if user else '—'


def _evento(pedido, user, tipo, texto=''):
    PedidoVendaEvento.objects.create(pedido=pedido, usuario=user, tipo=tipo, texto=texto)


def _link(pedido) -> str:
    base = getattr(settings, 'FRONTEND_URL', 'https://managerdb.com.br').rstrip('/')
    return f'{base}/vendas/pedido/{pedido.pk}'


# ── Avisos ──────────────────────────────────────────────────────────────────

def _notificar(pedido, usuarios, tipo, mensagem, whatsapp=True):
    usuarios = [u for u in {u.pk: u for u in usuarios if u}.values()]
    PedidoVendaNotificacao.objects.bulk_create([
        PedidoVendaNotificacao(pedido=pedido, usuario_notificado=u, tipo=tipo, mensagem=mensagem)
        for u in usuarios
    ])
    if not whatsapp:
        return
    telefones = list(
        VendedorPerfil.objects
        .filter(user__in=usuarios, ativo=True, avisar_whatsapp=True)
        .exclude(telefone_whatsapp='')
        .values_list('telefone_whatsapp', flat=True)
    )
    if telefones:
        titulo = dict(PedidoVendaNotificacao.TIPO_CHOICES).get(tipo, 'Pedido de venda')
        detalhe = f'{pedido.numero} · {mensagem}'
        transaction.on_commit(lambda: Thread(
            target=_enviar_whatsapp, args=(telefones, titulo, detalhe, _link(pedido)), daemon=True,
        ).start())


def _enviar_whatsapp(telefones, titulo, detalhe, link):
    """
    Avisa por template — o vendedor interno quase nunca está dentro da janela de
    24h do número de Atendimento, então texto livre seria recusado pela Meta.
    Sem template configurado o aviso fica só no sino (previsto, não é erro).
    """
    nome_template = getattr(settings, 'WHATSAPP_TEMPLATE_PEDIDO_VENDA', None)
    if not nome_template:
        logger.info('WHATSAPP_TEMPLATE_PEDIDO_VENDA não configurado; aviso de pedido só no sino.')
        return
    try:
        from whatsapp import graph_api
        from whatsapp.services import _parametro_template
    except Exception:  # pragma: no cover - app do WhatsApp fora do ar não pode travar o pedido
        logger.exception('App whatsapp indisponível para o aviso de pedido de venda')
        return
    idioma = getattr(settings, 'WHATSAPP_TEMPLATE_IDIOMA', 'pt_BR')
    componentes = [{
        'type': 'body',
        'parameters': [
            {'type': 'text', 'text': _parametro_template(titulo)},
            {'type': 'text', 'text': _parametro_template(detalhe)},
            {'type': 'text', 'text': _parametro_template(link)},
        ],
    }]
    for tel in telefones:
        try:
            graph_api.enviar_template(tel, nome_template, idioma, componentes)
        except Exception:
            logger.exception('Falha ao avisar %s por WhatsApp sobre pedido de venda', tel)


def _gestores():
    gestores = list(User.objects.filter(is_active=True, groups__name='vendasGestao').distinct())
    return gestores or list(User.objects.filter(is_active=True, is_superuser=True))


def _internos_destino(pedido):
    if pedido.interno:
        return [pedido.interno]
    # Externo sem interno vinculado: o pedido fica na fila de todos os internos.
    return [p.user for p in VendedorPerfil.objects.select_related('user').filter(tipo='INTERNO', ativo=True)]


# ── Validação ───────────────────────────────────────────────────────────────

def _conferir_precos(pedido):
    """
    Refaz o preço de tabela de cada item pelo ERP: o navegador manda o que mostrou,
    e é sobre o valor do ERP que o desconto é medido. ERP fora do ar não trava o
    envio — o interno ainda confere na digitação —, mas fica registrado.
    """
    from . import erp

    itens = list(pedido.itens.all())
    try:
        vigentes = erp.precos_vigentes(pedido.filial, pedido.cliente_cod, [i.produto_cod for i in itens])
    except Exception:
        logger.exception('ERP indisponível ao conferir preços do %s', pedido.numero)
        return 'Preços não conferidos com o ERP (indisponível no envio).'

    for item in itens:
        tabela = vigentes.get(item.produto_cod)
        if tabela is None:
            raise FluxoErro(f'"{item.descricao}" não tem preço de tabela nesta unidade. Remova o item ou troque a unidade.')
        tabela = Decimal(str(tabela))
        if item.preco_tabela is None or abs(item.preco_tabela - tabela) > TOLERANCIA_PRECO:
            item.preco_tabela = tabela
            item.save()
    return ''


def _validar_para_envio(pedido):
    if not pedido.itens.exists():
        raise FluxoErro('O pedido não tem itens.')
    if not pedido.cliente_cod and not pedido.cliente_novo:
        raise FluxoErro('Escolha o cliente ou preencha o pré-cadastro.')
    if pedido.cliente_novo:
        novo = pedido.cliente_novo
        faltando = [r for c, r in (('documento', 'CNPJ/CPF'), ('nome', 'razão social'), ('cidade', 'cidade'))
                    if not str(novo.get(c) or '').strip()]
        if faltando:
            raise FluxoErro('Pré-cadastro incompleto: ' + ', '.join(faltando) + '.')
    if not pedido.prazo_pagamento.strip():
        raise FluxoErro('Informe o prazo de pagamento.')
    for item in pedido.itens.all():
        if item.quantidade <= 0 or item.preco_unitario <= 0:
            raise FluxoErro(f'"{item.descricao}": quantidade e preço precisam ser maiores que zero.')


# ── Transições ──────────────────────────────────────────────────────────────

@transaction.atomic
def enviar(pedido: PedidoVenda, user, justificativa: str = '') -> PedidoVenda:
    if pedido.vendedor_id != user.pk:
        raise FluxoErro('Só o vendedor do pedido pode enviá-lo.')
    if pedido.status not in PedidoVenda.STATUS_EDITAVEIS:
        raise FluxoErro('Este pedido já foi enviado.')
    _validar_para_envio(pedido)
    aviso_preco = _conferir_precos(pedido)
    pedido.recalcular_totais()

    perfil = perfil_de(user)
    teto = perfil.desconto_maximo if perfil else Decimal('0')
    if justificativa:
        pedido.justificativa_desconto = justificativa.strip()
    if pedido.interno_id is None and perfil and perfil.interno:
        pedido.interno = perfil.interno.user
    reenvio = pedido.status == 'DEVOLVIDO'
    pedido.motivo_devolucao = ''
    pedido.enviado_em = timezone.now()

    acima_do_teto = pedido.maior_desconto > teto + Decimal('0.001')
    if acima_do_teto:
        if not pedido.justificativa_desconto.strip():
            raise FluxoErro(
                f'O desconto de {_pct(pedido.maior_desconto)} passa do seu teto de {_pct(teto)}. '
                'Escreva a justificativa para o gestor aprovar.'
            )
        pedido.status = 'AGUARDANDO_APROVACAO'
        pedido.aprovado_por = None
        pedido.aprovado_em = None
        pedido.save()
        _evento(pedido, user, 'APROVACAO_SOLICITADA',
                f'Desconto de {_pct(pedido.maior_desconto)} (teto {_pct(teto)}). {pedido.justificativa_desconto} {aviso_preco}'.strip())
        _notificar(pedido, _gestores(), 'APROVACAO_SOLICITADA',
                   f'{_nome(user)} pede {_pct(pedido.maior_desconto)} de desconto para {pedido.cliente_nome} ({_brl(pedido.total)}).')
        return pedido

    pedido.status = 'ENVIADO'
    pedido.save()
    _evento(pedido, user, 'ENVIADO', ('Reenviado após devolução. ' if reenvio else '') + aviso_preco)
    _avisar_internos(pedido, user)
    return pedido


def _avisar_internos(pedido, vendedor):
    _notificar(pedido, _internos_destino(pedido), 'NOVO_PEDIDO',
               f'{_nome(vendedor)} enviou pedido para {pedido.cliente_nome} — {_brl(pedido.total)}.')


@transaction.atomic
def aprovar(pedido: PedidoVenda, user, texto: str = '') -> PedidoVenda:
    if not eh_gestor(user):
        raise FluxoErro('Só o gestor de vendas aprova desconto.')
    if pedido.status != 'AGUARDANDO_APROVACAO':
        raise FluxoErro('O pedido não está aguardando aprovação.')
    pedido.status = 'ENVIADO'
    pedido.aprovado_por = user
    pedido.aprovado_em = timezone.now()
    pedido.save()
    _evento(pedido, user, 'APROVADO', texto)
    _notificar(pedido, [pedido.vendedor], 'APROVADO',
               f'Desconto aprovado por {_nome(user)} — pedido de {pedido.cliente_nome} seguiu para lançamento.')
    _avisar_internos(pedido, pedido.vendedor)
    return pedido


@transaction.atomic
def reprovar(pedido: PedidoVenda, user, motivo: str) -> PedidoVenda:
    if not eh_gestor(user):
        raise FluxoErro('Só o gestor de vendas reprova desconto.')
    if pedido.status != 'AGUARDANDO_APROVACAO':
        raise FluxoErro('O pedido não está aguardando aprovação.')
    if not (motivo or '').strip():
        raise FluxoErro('Informe o motivo para o vendedor ajustar o pedido.')
    pedido.status = 'DEVOLVIDO'
    pedido.motivo_devolucao = motivo.strip()
    pedido.save()
    _evento(pedido, user, 'REPROVADO', pedido.motivo_devolucao)
    _notificar(pedido, [pedido.vendedor], 'REPROVADO',
               f'Desconto do pedido de {pedido.cliente_nome} reprovado: {pedido.motivo_devolucao}')
    return pedido


def _pode_lancar(user) -> bool:
    perfil = perfil_de(user)
    return eh_gestor(user) or bool(perfil and perfil.tipo == 'INTERNO')


@transaction.atomic
def assumir(pedido: PedidoVenda, user) -> PedidoVenda:
    if not _pode_lancar(user):
        raise FluxoErro('Só o vendedor interno lança pedidos.')
    if pedido.status not in ('ENVIADO', 'EM_LANCAMENTO'):
        raise FluxoErro('O pedido não está na fila de lançamento.')
    if pedido.status == 'EM_LANCAMENTO' and pedido.interno_id not in (None, user.pk):
        raise FluxoErro(f'{_nome(pedido.interno)} já está lançando este pedido.')
    pedido.status = 'EM_LANCAMENTO'
    pedido.interno = user
    pedido.save()
    _evento(pedido, user, 'ASSUMIDO')
    return pedido


@transaction.atomic
def lancar(pedido: PedidoVenda, user, numero_erp) -> tuple[PedidoVenda, str]:
    from . import erp

    if not _pode_lancar(user):
        raise FluxoErro('Só o vendedor interno lança pedidos.')
    if pedido.status not in ('ENVIADO', 'EM_LANCAMENTO'):
        raise FluxoErro('O pedido não está na fila de lançamento.')
    try:
        numero_erp = int(str(numero_erp).strip())
    except (TypeError, ValueError):
        raise FluxoErro('Informe o número do pedido no ERP.')

    aviso = ''
    try:
        no_erp = erp.pedido_erp(numero_erp)
    except Exception:
        logger.exception('ERP indisponível ao conferir o pedido %s', numero_erp)
        no_erp, aviso = None, 'Número não conferido no ERP (indisponível).'
    else:
        if no_erp is None:
            raise FluxoErro(f'O pedido {numero_erp} não existe no ERP. Confira o número.')
        if pedido.cliente_cod and no_erp['cliente'] != pedido.cliente_cod:
            raise FluxoErro(
                f'O pedido {numero_erp} do ERP é de outro cliente (código {no_erp["cliente"]}). Confira o número.'
            )

    pedido.status = 'LANCADO'
    pedido.numero_erp = numero_erp
    pedido.interno = pedido.interno or user
    pedido.lancado_em = timezone.now()
    pedido.save()
    _evento(pedido, user, 'LANCADO', f'Pedido {numero_erp} no ERP. {aviso}'.strip())
    _notificar(pedido, [pedido.vendedor], 'LANCADO',
               f'Pedido de {pedido.cliente_nome} lançado no ERP com o nº {numero_erp}.')
    return pedido, aviso


@transaction.atomic
def devolver(pedido: PedidoVenda, user, motivo: str) -> PedidoVenda:
    if not _pode_lancar(user):
        raise FluxoErro('Só o vendedor interno devolve pedidos.')
    if pedido.status not in ('ENVIADO', 'EM_LANCAMENTO'):
        raise FluxoErro('O pedido não está na fila de lançamento.')
    if not (motivo or '').strip():
        raise FluxoErro('Diga ao vendedor o que precisa ser corrigido.')
    pedido.status = 'DEVOLVIDO'
    pedido.motivo_devolucao = motivo.strip()
    pedido.save()
    _evento(pedido, user, 'DEVOLVIDO', pedido.motivo_devolucao)
    _notificar(pedido, [pedido.vendedor], 'DEVOLVIDO',
               f'{_nome(user)} devolveu o pedido de {pedido.cliente_nome}: {pedido.motivo_devolucao}')
    return pedido


@transaction.atomic
def cancelar(pedido: PedidoVenda, user, motivo: str = '') -> PedidoVenda:
    if pedido.vendedor_id != user.pk and not eh_gestor(user):
        raise FluxoErro('Só o vendedor do pedido pode cancelá-lo.')
    if pedido.status in ('LANCADO', 'CANCELADO'):
        raise FluxoErro('Pedido lançado no ERP é cancelado lá, não aqui.' if pedido.status == 'LANCADO'
                        else 'O pedido já está cancelado.')
    estava_na_fila = pedido.status in ('ENVIADO', 'EM_LANCAMENTO')
    pedido.status = 'CANCELADO'
    pedido.save()
    _evento(pedido, user, 'CANCELADO', motivo)
    if estava_na_fila:
        _notificar(pedido, _internos_destino(pedido), 'CANCELADO',
                   f'{_nome(user)} cancelou o pedido de {pedido.cliente_nome}. Não lançar.')
    return pedido
