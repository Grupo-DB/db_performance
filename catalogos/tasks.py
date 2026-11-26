"""Tarefas Celery do app catalogos."""
from celery import shared_task


@shared_task
def importar_catalogo_pecas(catalogo_id: int):
    """Lê o PDF do catálogo de peças enviado pela tela Peças da Oficina (26/11/2026)."""
    from . import pecas_oficina
    pecas_oficina.executar_importacao(catalogo_id)
