"""Chamadas HTTP de baixo nível para a Meta Graph API (WhatsApp Cloud API)."""
import mimetypes

import requests
from django.conf import settings

# Timeout maior no upload/download: são arquivos, não JSON de algumas centenas de bytes.
TIMEOUT_PADRAO = 15
TIMEOUT_MIDIA = 60

# Como a Meta classifica cada arquivo. A categoria decide o campo do payload
# ('image', 'document', ...) e o que ele aceita: só image/video/document têm
# legenda, e só document tem nome de arquivo.
CATEGORIA_IMAGEM = 'image'
CATEGORIA_DOCUMENTO = 'document'
CATEGORIA_AUDIO = 'audio'
CATEGORIA_VIDEO = 'video'

# Categorias que aceitam `caption`. Áudio não aceita — mandar mesmo assim faz a
# Meta rejeitar a mensagem inteira, e não apenas ignorar a legenda.
CATEGORIAS_COM_LEGENDA = {CATEGORIA_IMAGEM, CATEGORIA_DOCUMENTO, CATEGORIA_VIDEO}

# Limites de tamanho da Cloud API, em bytes. Barrar aqui evita gastar o upload
# inteiro para receber 400 da Meta no fim.
LIMITE_BYTES = {
    CATEGORIA_IMAGEM: 5 * 1024 * 1024,
    CATEGORIA_DOCUMENTO: 100 * 1024 * 1024,
    CATEGORIA_AUDIO: 16 * 1024 * 1024,
    CATEGORIA_VIDEO: 16 * 1024 * 1024,
}

# Tradução da categoria da Meta para o `tipo` do nosso modelo Mensagem.
CATEGORIA_PARA_TIPO_INTERNO = {
    CATEGORIA_IMAGEM: 'IMAGEM',
    CATEGORIA_DOCUMENTO: 'DOCUMENTO',
    CATEGORIA_AUDIO: 'AUDIO',
    CATEGORIA_VIDEO: 'VIDEO',
}


class MidiaMuitoGrande(Exception):
    """Arquivo acima do limite que a Cloud API aceita para aquela categoria."""


def detalhe_do_erro(exc: Exception) -> str:
    """
    Motivo legível de uma falha de envio, para gravar em `Mensagem.erro_detalhe`.

    O texto da exceção do requests é só "400 Client Error": a explicação da Meta
    (e o `code` que se procura na documentação) vem no corpo da resposta. Sem
    abrir esse corpo, o atendente vê um "falhou" mudo e não sabe o que corrigir.
    """
    resposta = getattr(exc, 'response', None)
    if resposta is None:
        return str(exc)
    try:
        erro = resposta.json().get('error', {})
    except ValueError:
        return f'{exc} — {resposta.text[:300]}'
    return f"{erro.get('message', str(exc))} (code {erro.get('code')})"


def _base_url():
    return f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}"


def _headers():
    return {'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN}'}


def categoria_da_midia(mime_type: str, nome_arquivo: str = '') -> str:
    """
    Descobre a categoria da Meta a partir do MIME (ou da extensão, se faltar).

    O navegador nem sempre manda `Content-Type` confiável no upload — daí o
    palpite pela extensão antes de cair em 'document', que é o balde geral.
    """
    mime = (mime_type or '').lower().split(';')[0].strip()
    if not mime or mime == 'application/octet-stream':
        mime = (mimetypes.guess_type(nome_arquivo)[0] or '').lower()

    if mime.startswith('image/'):
        return CATEGORIA_IMAGEM
    if mime.startswith('audio/'):
        return CATEGORIA_AUDIO
    if mime.startswith('video/'):
        return CATEGORIA_VIDEO
    return CATEGORIA_DOCUMENTO


def tipo_interno_da_midia(mime_type: str, nome_arquivo: str = '') -> str:
    """Categoria da Meta traduzida para o `Mensagem.tipo` do nosso modelo."""
    return CATEGORIA_PARA_TIPO_INTERNO[categoria_da_midia(mime_type, nome_arquivo)]


# ── Envio ────────────────────────────────────────────────────────────────────

def enviar_mensagem_texto(telefone: str, texto: str) -> dict:
    """Envia mensagem de texto livre. Só é aceita pela Meta dentro da janela de 24h."""
    url = f"{_base_url()}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        'messaging_product': 'whatsapp',
        'to': telefone,
        'type': 'text',
        'text': {'body': texto},
    }
    resp = requests.post(url, json=payload, headers=_headers(), timeout=TIMEOUT_PADRAO)
    resp.raise_for_status()
    return resp.json()


def upload_midia(conteudo: bytes, nome_arquivo: str, mime_type: str) -> str:
    """
    Sobe o arquivo para a Meta e devolve o `media_id`.

    Enviar mídia é em duas etapas: primeiro o arquivo sobe para o servidor da
    Meta, depois a mensagem referencia o id devolvido. Não existe caminho de
    mandar o arquivo direto no payload da mensagem.

    O id vale 30 dias e é específico do número de origem.
    """
    categoria = categoria_da_midia(mime_type, nome_arquivo)
    limite = LIMITE_BYTES[categoria]
    if len(conteudo) > limite:
        raise MidiaMuitoGrande(
            f'{nome_arquivo}: {len(conteudo) / 1048576:.1f} MB excede o limite de '
            f'{limite // 1048576} MB que o WhatsApp aceita para {categoria}.'
        )

    mime_efetivo = (mime_type or '').split(';')[0].strip() or \
        (mimetypes.guess_type(nome_arquivo)[0] or 'application/octet-stream')

    url = f"{_base_url()}/{settings.WHATSAPP_PHONE_NUMBER_ID}/media"
    resp = requests.post(
        url,
        headers=_headers(),
        # 'type' vai no corpo e o arquivo em multipart; a Meta recusa JSON aqui.
        data={'messaging_product': 'whatsapp', 'type': mime_efetivo},
        files={'file': (nome_arquivo, conteudo, mime_efetivo)},
        timeout=TIMEOUT_MIDIA,
    )
    resp.raise_for_status()
    return resp.json()['id']


def enviar_midia(
    telefone: str,
    media_id: str,
    categoria: str,
    legenda: str = '',
    nome_arquivo: str = '',
) -> dict:
    """Envia mídia já hospedada na Meta (`media_id` vindo de `upload_midia`)."""
    corpo: dict = {'id': media_id}
    if legenda and categoria in CATEGORIAS_COM_LEGENDA:
        corpo['caption'] = legenda
    if categoria == CATEGORIA_DOCUMENTO and nome_arquivo:
        # Sem isto o destinatário recebe o documento nomeado com o id interno.
        corpo['filename'] = nome_arquivo

    url = f"{_base_url()}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        'messaging_product': 'whatsapp',
        'to': telefone,
        'type': categoria,
        categoria: corpo,
    }
    resp = requests.post(url, json=payload, headers=_headers(), timeout=TIMEOUT_MIDIA)
    resp.raise_for_status()
    return resp.json()


def enviar_template(
    telefone: str,
    nome_template: str,
    idioma: str = 'pt_BR',
    componentes: list | None = None,
) -> dict:
    """
    Envia um template aprovado pela Meta.

    É o único jeito de falar com o cliente FORA da janela de 24h. O template
    precisa estar aprovado no WhatsApp Manager; `componentes` preenche as
    variáveis ({{1}}, {{2}}...) declaradas nele.

    Enviar template NÃO reabre a janela de 24h — só uma resposta do cliente reabre.
    """
    template: dict = {'name': nome_template, 'language': {'code': idioma}}
    if componentes:
        template['components'] = componentes

    url = f"{_base_url()}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        'messaging_product': 'whatsapp',
        'to': telefone,
        'type': 'template',
        'template': template,
    }
    resp = requests.post(url, json=payload, headers=_headers(), timeout=TIMEOUT_PADRAO)
    resp.raise_for_status()
    return resp.json()


def listar_templates() -> list[dict]:
    """
    Templates cadastrados na conta, para a tela oferecer só o que existe.

    Consulta a WABA (não o número), então depende de
    `WHATSAPP_BUSINESS_ACCOUNT_ID`. Sem essa variável devolve lista vazia em vez
    de estourar: a tela mostra "nenhum template" em vez de erro 500.
    """
    waba_id = getattr(settings, 'WHATSAPP_BUSINESS_ACCOUNT_ID', None)
    if not waba_id:
        return []
    url = f"{_base_url()}/{waba_id}/message_templates"
    resp = requests.get(
        url, headers=_headers(),
        params={'limit': 100, 'fields': 'name,status,language,category,components'},
        timeout=TIMEOUT_PADRAO,
    )
    resp.raise_for_status()
    return resp.json().get('data', [])


# ── Recebimento ──────────────────────────────────────────────────────────────

def obter_url_midia(wa_media_id: str) -> str:
    url = f"{_base_url()}/{wa_media_id}"
    resp = requests.get(url, headers=_headers(), timeout=TIMEOUT_PADRAO)
    resp.raise_for_status()
    return resp.json()['url']


def baixar_midia(media_url: str) -> tuple[bytes, str]:
    resp = requests.get(media_url, headers=_headers(), timeout=TIMEOUT_MIDIA)
    resp.raise_for_status()
    return resp.content, resp.headers.get('Content-Type', '')
