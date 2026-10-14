import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def classificar_formulario_desligamento(self, formulario_id: int):
    """IA classifica as respostas abertas de um formulário de desligamento (ver desligamento.py).
    Falha da IA (o Foundry às vezes devolve 408) tenta de novo em 1 minuto, até 3 vezes."""
    from .views import aplicar_classificacao
    from .models import FormularioDesligamento
    f = FormularioDesligamento.objects.filter(pk=formulario_id).first()
    if f and not f.classificacao_revisada and not aplicar_classificacao(f):
        raise self.retry(countdown=60)
