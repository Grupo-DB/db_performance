"""Chamadas HTTP de baixo nível para a Meta Graph API (WhatsApp Cloud API)."""
import requests
from django.conf import settings


def _base_url():
    return f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}"


def _headers():
    return {'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN}'}


def enviar_mensagem_texto(telefone: str, texto: str) -> dict:
    """Envia mensagem de texto livre. Só é aceita pela Meta dentro da janela de 24h."""
    url = f"{_base_url()}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        'messaging_product': 'whatsapp',
        'to': telefone,
        'type': 'text',
        'text': {'body': texto},
    }
    resp = requests.post(url, json=payload, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def obter_url_midia(wa_media_id: str) -> str:
    url = f"{_base_url()}/{wa_media_id}"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()['url']


def baixar_midia(media_url: str) -> tuple[bytes, str]:
    resp = requests.get(media_url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.content, resp.headers.get('Content-Type', '')
