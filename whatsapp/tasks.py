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


def _marcar_enviada(mensagem: Mensagem, resposta: dict):
    mensagem.wa_message_id = resposta.get('messages', [{}])[0].get('id')
    mensagem.status_entrega = 'ENVIADA'
    mensagem.save(update_fields=['wa_message_id', 'status_entrega'])


def _marcar_falha(mensagem: Mensagem, exc: Exception, contexto: str):
    logger.exception('%s (mensagem_id=%s)', contexto, mensagem.id)
    mensagem.status_entrega = 'FALHOU'
    # A mensagem da Meta vem no corpo da resposta, não no texto da exceção do
    # requests ("400 Client Error"). Sem ela o atendente não sabe o que corrigir.
    detalhe = str(exc)
    resposta = getattr(exc, 'response', None)
    if resposta is not None:
        try:
            erro = resposta.json().get('error', {})
            detalhe = f"{erro.get('message', detalhe)} (code {erro.get('code')})"
        except ValueError:
            detalhe = f'{detalhe} — {resposta.text[:300]}'
    mensagem.erro_detalhe = detalhe
    mensagem.save(update_fields=['status_entrega', 'erro_detalhe'])


@shared_task
def enviar_mensagem_whatsapp(mensagem_id: int):
    """
    Entrega ao WhatsApp a mensagem que o atendente escreveu.

    Com anexo o caminho é outro: sobe o arquivo, pega o `media_id` e manda a
    mensagem referenciando esse id. Antes esta task só chamava
    `enviar_mensagem_texto`, então o anexo era gravado no servidor e nunca saía —
    o atendente via o arquivo na tela e o cliente não recebia nada.

    O texto que vai para o cliente não é o mesmo que está gravado: leva o nome do
    atendente na frente (ver `services.assinar_para_cliente`). O cálculo é feito
    uma vez só, antes do envio, porque ele depende de qual foi a última saída da
    conversa — e esta mensagem passa a ser a última assim que sai.
    """
    mensagem = Mensagem.objects.select_related('conversa', 'autor').prefetch_related('anexos').get(id=mensagem_id)
    telefone = mensagem.conversa.contato_telefone
    anexo = mensagem.anexos.first()
    texto_para_cliente = services.assinar_para_cliente(mensagem.texto, mensagem)

    if anexo is None:
        try:
            _marcar_enviada(mensagem, graph_api.enviar_mensagem_texto(telefone, texto_para_cliente))
        except Exception as exc:
            _marcar_falha(mensagem, exc, 'Falha ao enviar texto do WhatsApp')
        return

    try:
        nome = anexo.nome_original or anexo.arquivo.name.rsplit('/', 1)[-1]
        with anexo.arquivo.open('rb') as arquivo:
            conteudo = arquivo.read()

        categoria = graph_api.categoria_da_midia(anexo.mime_type, nome)
        media_id = graph_api.upload_midia(conteudo, nome, anexo.mime_type)
        anexo.wa_media_id = media_id
        anexo.save(update_fields=['wa_media_id'])

        resposta = graph_api.enviar_midia(
            telefone, media_id, categoria, legenda=texto_para_cliente, nome_arquivo=nome,
        )
        _marcar_enviada(mensagem, resposta)
    except Exception as exc:
        _marcar_falha(mensagem, exc, 'Falha ao enviar mídia do WhatsApp')
        return

    # Áudio não aceita legenda na Cloud API. Em vez de descartar o que o atendente
    # escreveu, o texto sai como mensagem própria, logo depois do áudio.
    #
    # A condição olha o texto JÁ assinado: num áudio sem legenda que seria a
    # primeira fala do atendente, o que sobra é só o nome — e ele precisa sair,
    # senão o cliente nunca fica sabendo quem mandou o áudio e a mensagem seguinte
    # já não assina mais (esta aqui passa a ser a última saída da conversa).
    if texto_para_cliente and categoria not in graph_api.CATEGORIAS_COM_LEGENDA:
        try:
            graph_api.enviar_mensagem_texto(telefone, texto_para_cliente)
        except Exception:
            logger.exception(
                'Mídia enviada, mas a legenda avulsa falhou (mensagem_id=%s)', mensagem_id,
            )


@shared_task
def enviar_template_whatsapp(mensagem_id: int, nome_template: str, idioma: str, componentes: list | None):
    """
    Envia um template aprovado — o único caminho fora da janela de 24h.

    Fica em task separada porque o payload é outro e porque a falha aqui é
    diferente: template não aprovado, nome errado ou idioma inexistente devolvem
    erro da Meta que o atendente precisa ler para corrigir.
    """
    mensagem = Mensagem.objects.select_related('conversa').get(id=mensagem_id)
    try:
        resposta = graph_api.enviar_template(
            mensagem.conversa.contato_telefone, nome_template, idioma, componentes,
        )
        _marcar_enviada(mensagem, resposta)
    except Exception as exc:
        _marcar_falha(mensagem, exc, 'Falha ao enviar template do WhatsApp')
