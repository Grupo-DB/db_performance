"""Tarefas Celery do app catalogos."""
from celery import shared_task


@shared_task
def importar_catalogo_pecas(catalogo_id: int):
    """Lê o PDF do catálogo de peças enviado pela tela Peças da Oficina (26/11/2026)."""
    from . import pecas_oficina
    pecas_oficina.executar_importacao(catalogo_id)


@shared_task
def whatsapp_notificacao_pecas(notificacao_id: int):
    """Aviso de Peças da Oficina no WhatsApp de quem pediu para receber (template PECAS_WHATSAPP_TEMPLATE)."""
    import logging
    from . import pecas_oficina
    try:
        pecas_oficina.enviar_whatsapp(notificacao_id)
    except Exception:  # noqa: BLE001 — o sino já avisou; WhatsApp é extra
        logging.getLogger(__name__).exception('peças: WhatsApp da notificação %s falhou', notificacao_id)
