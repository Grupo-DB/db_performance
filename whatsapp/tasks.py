import logging

from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone

from . import graph_api, services
from .models import Conversa, Mensagem, MensagemAnexo, WhatsAppNotificacao

logger = logging.getLogger(__name__)

_TIPO_MEDIA_CAMPO = {
    'image': 'IMAGEM',
    'document': 'DOCUMENTO',
    'audio': 'AUDIO',
    'video': 'VIDEO',
}


@shared_task
def processar_webhook_whatsapp(payload: dict):
    try:
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                for msg in value.get('messages', []):
                    _processar_mensagem_recebida(value, msg)
                for status in value.get('statuses', []):
                    _processar_status(status)
    except Exception:
        logger.exception('Falha ao processar webhook do WhatsApp')


def _processar_mensagem_recebida(value: dict, msg: dict):
    telefone = msg.get('from')
    wa_message_id = msg.get('id')
    if Mensagem.objects.filter(wa_message_id=wa_message_id).exists():
        return  # retry do Meta — idempotente

    contato_nome = ''
    for contato in value.get('contacts', []):
        if contato.get('wa_id') == telefone:
            contato_nome = contato.get('profile', {}).get('name', '')
            break

    conversa = Conversa.objects.filter(contato_telefone=telefone).order_by('-created_at').first()
    if conversa is None:
        conversa = Conversa.objects.create(
            contato_telefone=telefone,
            contato_nome=contato_nome,
            numero_negocio_id=value.get('metadata', {}).get('phone_number_id', ''),
        )
    elif conversa.status == 'ENCERRADA':
        conversa.status = 'ABERTA'
        conversa.estado_menu = 'AGUARDANDO_SETOR'
        conversa.tentativas_menu = 0
    if not conversa.contato_nome and contato_nome:
        conversa.contato_nome = contato_nome

    tipo_msg = msg.get('type', 'text')
    texto = msg.get('text', {}).get('body', '') if tipo_msg == 'text' else ''
    tipo_interno = 'TEXTO' if tipo_msg == 'text' else _TIPO_MEDIA_CAMPO.get(tipo_msg, 'TEXTO')

    agora = timezone.now()
    conversa.ultima_mensagem_em = agora
    conversa.ultima_mensagem_cliente_em = agora
    conversa.save()

    mensagem = Mensagem.objects.create(
        conversa=conversa,
        direcao='ENTRADA',
        tipo=tipo_interno,
        texto=texto,
        wa_message_id=wa_message_id,
        status_entrega='ENTREGUE',
        payload_bruto=msg,
    )

    media_info = msg.get(tipo_msg) if tipo_msg in _TIPO_MEDIA_CAMPO else None
    if media_info and media_info.get('id'):
        baixar_midia_whatsapp.delay(mensagem.id, media_info['id'])

    if conversa.estado_menu == 'EM_ATENDIMENTO' and conversa.fila_id:
        _notificar_nova_mensagem(conversa, texto or f"[{tipo_interno.lower()}]")
    else:
        services.resolver_fila_por_texto(texto, conversa)


def _notificar_nova_mensagem(conversa: Conversa, preview: str):
    if not conversa.fila_id:
        return
    notificacoes = [
        WhatsAppNotificacao(
            conversa=conversa, usuario_notificado=membro,
            tipo='NOVA_MENSAGEM', mensagem=preview[:255],
        )
        for membro in conversa.fila.membros.all()
    ]
    if notificacoes:
        WhatsAppNotificacao.objects.bulk_create(notificacoes)


def _processar_status(status: dict):
    wa_message_id = status.get('id')
    novo_status = {
        'sent': 'ENVIADA', 'delivered': 'ENTREGUE',
        'read': 'LIDA', 'failed': 'FALHOU',
    }.get(status.get('status'))
    if not novo_status:
        return
    Mensagem.objects.filter(wa_message_id=wa_message_id).update(status_entrega=novo_status)


@shared_task
def baixar_midia_whatsapp(mensagem_id: int, wa_media_id: str):
    try:
        url = graph_api.obter_url_midia(wa_media_id)
        conteudo, content_type = graph_api.baixar_midia(url)
        mensagem = Mensagem.objects.get(id=mensagem_id)
        anexo = MensagemAnexo(mensagem=mensagem, wa_media_id=wa_media_id, mime_type=content_type)
        anexo.arquivo.save(f"{wa_media_id}", ContentFile(conteudo), save=True)
    except Exception:
        logger.exception('Falha ao baixar mídia do WhatsApp (media_id=%s)', wa_media_id)


@shared_task
def enviar_mensagem_whatsapp(mensagem_id: int):
    mensagem = Mensagem.objects.select_related('conversa').get(id=mensagem_id)
    try:
        resposta = graph_api.enviar_mensagem_texto(mensagem.conversa.contato_telefone, mensagem.texto)
        wa_id = resposta.get('messages', [{}])[0].get('id')
        mensagem.wa_message_id = wa_id
        mensagem.status_entrega = 'ENVIADA'
        mensagem.save(update_fields=['wa_message_id', 'status_entrega'])
    except Exception as exc:
        logger.exception('Falha ao enviar mensagem do WhatsApp (mensagem_id=%s)', mensagem_id)
        mensagem.status_entrega = 'FALHOU'
        mensagem.erro_detalhe = str(exc)
        mensagem.save(update_fields=['status_entrega', 'erro_detalhe'])
