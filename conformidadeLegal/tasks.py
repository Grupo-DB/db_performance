import logging

from celery import shared_task
from django.utils import timezone

from . import ia
from .models import ExtracaoIA

logger = logging.getLogger(__name__)


@shared_task
def extrair_requisitos(extracao_id: int):
    """Lê o PDF da norma com a IA e grava as sugestões na ExtracaoIA."""
    extracao = ExtracaoIA.objects.select_related('norma').get(pk=extracao_id)
    norma = extracao.norma
    ja = [f'{r.referencia} — {r.descricao}'.strip(' —')
          for r in norma.requisitos.filter(ativo=True).only('referencia', 'descricao')]
    try:
        with norma.arquivo.open('rb') as f:
            conteudo = f.read()
        resultado = ia.extrair(norma, conteudo, ja)
    except (ia.FalhaExtracao, ia.IANaoConfigurada) as e:
        extracao.status, extracao.erro = 'ERRO', str(e)
    except Exception:  # noqa: BLE001 — qualquer falha precisa sair do "processando"
        logger.exception('Extração IA %s falhou', extracao_id)
        extracao.status, extracao.erro = 'ERRO', 'Falha ao consultar a IA. Tente de novo em alguns minutos.'
    else:
        extracao.status = 'CONCLUIDA'
        extracao.itens = resultado['itens']
        extracao.resumo = resultado['resumo']
        extracao.tokens_entrada = resultado['tokens_entrada']
        extracao.tokens_saida = resultado['tokens_saida']
    extracao.concluido_em = timezone.now()
    extracao.save()
