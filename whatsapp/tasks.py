import logging
import mimetypes

from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone

from . import audio, graph_api, services
from .models import Conversa, Mensagem, MensagemAnexo, WhatsAppNotificacao

logger = logging.getLogger(__name__)

_TIPO_MEDIA_CAMPO = {
    'image': 'IMAGEM',
    'document': 'DOCUMENTO',
    'audio': 'AUDIO',
    'video': 'VIDEO',
}

# Tipos que NÃO são mídia para baixar, mas têm bolha própria na tela.
_TIPO_ESTRUTURADO = {
    'contacts': 'CONTATO',
}

# Como descrever, no texto da bolha, o que chegou e não é texto. Sem isto a
# mensagem entrava com tipo TEXTO e corpo vazio — figurinha, localização e
# cartão de contato viravam BOLHA EM BRANCO, sem indício de que algo chegou.
_RESUMO_POR_TIPO = {
    'sticker': '[figurinha]',
    'location': '[localização]',
    'contacts': '[contato]',
    'reaction': '[reação]',
    'button': '[resposta de botão]',
    'interactive': '[resposta de menu]',
    'order': '[pedido]',
    'system': '[aviso do sistema]',
    'unsupported': '[mensagem não suportada]',
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
    if tipo_msg == 'text':
        tipo_interno = 'TEXTO'
    else:
        tipo_interno = (_TIPO_MEDIA_CAMPO.get(tipo_msg)
                        or _TIPO_ESTRUTURADO.get(tipo_msg)
                        or 'TEXTO')
    # Mídia tem prévia própria na bolha e não precisa de texto; o resto precisa,
    # senão a bolha sai vazia. O payload cru fica guardado de todo jeito.
    if not texto and tipo_msg not in _TIPO_MEDIA_CAMPO:
        texto = _RESUMO_POR_TIPO.get(tipo_msg, f'[{tipo_msg}]') if tipo_msg != 'text' else ''

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
        # Cliente respondendo uma mensagem específica: a Meta manda o id da citada
        # em context.id. Guardar o vínculo é o que deixa a central mostrar "em
        # resposta a" — sem isso um "sim" solto não diz a que ele se refere.
        responde_a=_mensagem_citada(msg),
    )

    media_info = msg.get(tipo_msg) if tipo_msg in _TIPO_MEDIA_CAMPO else None
    if media_info and media_info.get('id'):
        baixar_midia_whatsapp.delay(mensagem.id, media_info['id'])

    if conversa.estado_menu == 'EM_ATENDIMENTO' and conversa.fila_id:
        _notificar_nova_mensagem(conversa, texto or f"[{tipo_interno.lower()}]")
    else:
        services.resolver_fila_por_texto(texto, conversa)


def _mensagem_citada(msg: dict):
    """
    A mensagem que o cliente citou, quando ela existe no nosso histórico.

    Devolve None sem drama quando o id não é conhecido: a citada pode ser
    anterior à integração, ou ter sido enviada por outro canal.
    """
    citada_id = (msg.get('context') or {}).get('id')
    if not citada_id:
        return None
    return Mensagem.objects.filter(wa_message_id=citada_id).first()


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


def _motivo_da_falha(status: dict) -> str:
    """
    Texto legível a partir do array `errors` do status.

    Cada erro traz `title` (curto), `error_data.details` (a explicação de verdade)
    e `code`, que é o que se procura na documentação da Meta.
    """
    partes = []
    for erro in status.get('errors') or []:
        titulo = erro.get('title') or erro.get('message') or ''
        detalhes = (erro.get('error_data') or {}).get('details') or ''
        # title e details costumam repetir a mesma frase; só vale juntar se diferem.
        texto = titulo if detalhes.strip() == titulo.strip() else ' — '.join(x for x in (titulo, detalhes) if x)
        codigo = erro.get('code')
        partes.append(f'{texto} (code {codigo})' if codigo else texto)
    return ' | '.join(p for p in partes if p.strip())


def _processar_status(status: dict):
    wa_message_id = status.get('id')
    novo_status = {
        'sent': 'ENVIADA', 'delivered': 'ENTREGUE',
        'read': 'LIDA', 'failed': 'FALHOU',
    }.get(status.get('status'))
    if not novo_status:
        return

    campos = {'status_entrega': novo_status}
    if novo_status == 'FALHOU':
        # Sem isto a mensagem virava um "falhou" mudo na tela: a recusa da Meta é
        # assíncrona, então o envio não levanta exceção nenhuma e o único lugar
        # onde o motivo existe é este payload — que antes era descartado.
        campos['erro_detalhe'] = (
            _motivo_da_falha(status)
            or 'O WhatsApp recusou a mensagem e não informou o motivo.'
        )
        logger.warning('WhatsApp recusou a mensagem %s: %s', wa_message_id, status)

    Mensagem.objects.filter(wa_message_id=wa_message_id).update(**campos)


@shared_task
def baixar_midia_whatsapp(mensagem_id: int, wa_media_id: str):
    try:
        url = graph_api.obter_url_midia(wa_media_id)
        conteudo, content_type = graph_api.baixar_midia(url)
        mensagem = Mensagem.objects.get(id=mensagem_id)
        anexo = MensagemAnexo(mensagem=mensagem, wa_media_id=wa_media_id, mime_type=content_type)
        # Com extensão: o arquivo é servido pelo nginx, que decide o Content-Type
        # pelo nome. Sem ela a foto descia como octet-stream e o navegador não a
        # tratava como imagem (nem no <img> da bolha, nem ao abrir em aba nova).
        anexo.arquivo.save(f'{wa_media_id}{_extensao_da_midia(content_type)}', ContentFile(conteudo), save=True)
    except Exception:
        logger.exception('Falha ao baixar mídia do WhatsApp (media_id=%s)', wa_media_id)


def _extensao_da_midia(content_type: str) -> str:
    """
    Extensão a partir do Content-Type que a Meta devolveu.

    A tabela vem antes do `guess_extension` porque o palpite dele depende da tabela
    de MIME do sistema operacional e varia entre versões do Python — no áudio do
    WhatsApp, por exemplo, ele devolve '.oga' para audio/ogg, extensão que a lista
    padrão do nginx não conhece. Aqui os tipos que sempre aparecem ficam fixos.
    """
    mime = (content_type or '').split(';')[0].strip().lower()
    conhecidas = {
        'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
        'audio/ogg': '.ogg', 'audio/mpeg': '.mp3', 'audio/mp4': '.m4a',
        'video/mp4': '.mp4', 'application/pdf': '.pdf',
    }
    if mime in conhecidas:
        return conhecidas[mime]
    return mimetypes.guess_extension(mime) or ''


def _marcar_enviada(mensagem: Mensagem, resposta: dict):
    mensagem.wa_message_id = resposta.get('messages', [{}])[0].get('id')
    mensagem.status_entrega = 'ENVIADA'
    mensagem.save(update_fields=['wa_message_id', 'status_entrega'])


def _marcar_falha(mensagem: Mensagem, exc: Exception, contexto: str):
    logger.exception('%s (mensagem_id=%s)', contexto, mensagem.id)
    mensagem.status_entrega = 'FALHOU'
    mensagem.erro_detalhe = graph_api.detalhe_do_erro(exc)
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
    mensagem = (
        Mensagem.objects
        .select_related('conversa', 'autor', 'responde_a')
        .prefetch_related('anexos')
        .get(id=mensagem_id)
    )
    telefone = mensagem.conversa.contato_telefone
    anexo = mensagem.anexos.first()
    texto_para_cliente = services.assinar_para_cliente(mensagem.texto, mensagem)
    # Só cita o que a Meta conhece: mensagem nossa que ainda não saiu (ou anterior
    # à integração) não tem wa_message_id, e mandar `context` com id inválido faz
    # a Meta recusar a mensagem inteira em vez de só ignorar a citação.
    citando = (mensagem.responde_a.wa_message_id or '') if mensagem.responde_a_id else ''

    if anexo is None:
        try:
            _marcar_enviada(
                mensagem,
                graph_api.enviar_mensagem_texto(telefone, texto_para_cliente, citando=citando),
            )
        except Exception as exc:
            _marcar_falha(mensagem, exc, 'Falha ao enviar texto do WhatsApp')
        return

    try:
        nome = anexo.nome_original or anexo.arquivo.name.rsplit('/', 1)[-1]
        with anexo.arquivo.open('rb') as arquivo:
            conteudo = arquivo.read()

        categoria = graph_api.categoria_da_midia(anexo.mime_type, nome)
        mime_envio = anexo.mime_type
        if categoria == graph_api.CATEGORIA_AUDIO:
            # O arquivo guardado continua sendo o original — é o que a central
            # toca para o atendente, e o navegador dele lê webm sem problema.
            # A conversão vale só para o que sobe à Meta.
            conteudo, mime_envio, nome = audio.preparar_para_whatsapp(conteudo, anexo.mime_type, nome)

        media_id = graph_api.upload_midia(conteudo, nome, mime_envio)
        anexo.wa_media_id = media_id
        anexo.save(update_fields=['wa_media_id'])

        resposta = graph_api.enviar_midia(
            telefone, media_id, categoria, legenda=texto_para_cliente,
            nome_arquivo=nome, citando=citando,
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


@shared_task
def enviar_contato_whatsapp(mensagem_id: int):
    """
    Envia os cartões de contato já montados na hora do POST.

    Os cartões vêm prontos de `payload_bruto['contacts']`: quem monta é a view,
    porque é lá que estão os ids da agenda. A task só entrega — assim uma
    mudança na agenda depois do envio não reescreve o que o cliente recebeu.
    """
    mensagem = Mensagem.objects.select_related('conversa').get(id=mensagem_id)
    cartoes = (mensagem.payload_bruto or {}).get('contacts') or []
    if not cartoes:
        _marcar_falha(mensagem, ValueError('sem cartões no payload'),
                      'Mensagem de contato sem cartão para enviar')
        return

    citando = mensagem.responde_a.wa_message_id if mensagem.responde_a_id else ''
    try:
        resposta = graph_api.enviar_contatos(
            mensagem.conversa.contato_telefone, cartoes, citando=citando or '',
        )
        _marcar_enviada(mensagem, resposta)
    except Exception as exc:
        _marcar_falha(mensagem, exc, 'Falha ao enviar contato do WhatsApp')


@shared_task
def notificar_andamento_tarefa(tarefa_id: int):
    """
    Avisa o cliente que a tarefa nascida do atendimento dele mudou de andamento.

    Enfileirada pelo signal em `kanban/signals.py`, já depois do commit — a
    decisão de o que mandar (texto livre ou template) fica em `services`, aqui só
    o que depende de I/O e do estado atual do banco.

    A tarefa é relida em vez de receber os dados por parâmetro: entre o commit e a
    execução ela pode ter sido movida de novo, e o que interessa ao cliente é onde
    ela está agora, não o passo intermediário que disparou a fila.
    """
    from kanban.models import KanbanTask

    tarefa = (
        KanbanTask.objects
        .select_related('conversa_whatsapp', 'coluna')
        .filter(pk=tarefa_id)
        .first()
    )
    # Apagada, desvinculada ou com o aviso desligado entre o commit e agora.
    if tarefa is None or tarefa.conversa_whatsapp is None or not tarefa.notificar_whatsapp:
        return

    andamento = 'Concluída' if tarefa.concluido_em else tarefa.coluna.titulo
    services.avisar_andamento_tarefa(tarefa.conversa_whatsapp, tarefa.titulo, andamento)
