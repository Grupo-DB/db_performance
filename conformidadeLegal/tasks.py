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
        # Já validado na view; reinterpretado aqui porque a task só recebe o id.
        paginas = ia.interpretar_paginas(extracao.paginas, ia.contar_paginas(conteudo)) if extracao.paginas else None
        resultado = ia.extrair(norma, conteudo, ja, paginas)
    except (ia.FalhaExtracao, ia.IANaoConfigurada, ia.PaginasInvalidas) as e:
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


@shared_task
def monitorar_diarios():
    """
    Coleta diária dos diários oficiais (CELERY_BEAT_SCHEDULE): recupera os dias que
    ficaram para trás desde a última coleta boa e, em seguida, faz a triagem pela IA
    do que entrou. Rodar mais de uma vez no dia é seguro (pega a 2ª edição).
    """
    from django.conf import settings
    from . import monitor
    hoje = timezone.localdate()
    for dia in monitor.dias_a_coletar('DOE_RS', hoje):
        monitor.coletar_doe_rs(dia)
    # DOU só com a conta do INLABS configurada (sem ela não há o que registrar como falha).
    if getattr(settings, 'CONFORMIDADE_INLABS_EMAIL', '') and getattr(settings, 'CONFORMIDADE_INLABS_SENHA', ''):
        for dia in monitor.dias_a_coletar('DOU', hoje):
            monitor.coletar_dou(dia)
    triar_publicacoes()


@shared_task
def triar_publicacoes(limite: int = 40):
    """IA dá relevância e motivo ao que ainda não foi analisado. Sem IA configurada, a
    publicação fica sem relevância e a equipe avalia do mesmo jeito."""
    from .models import PublicacaoMonitorada
    if not ia.configurada():
        return
    pendentes = PublicacaoMonitorada.objects.filter(status='NOVA', analisada_em__isnull=True).order_by('id')[:limite]
    for pub in pendentes:
        try:
            r = ia.triar_publicacao(pub)
        except Exception:  # noqa: BLE001 — uma publicação ruim não pode travar as outras
            logger.exception('Triagem IA da publicação %s falhou', pub.id)
            continue
        pub.relevancia, pub.analise, pub.tema_sugerido = r['relevancia'], r['motivo'], r['tema']
        pub.analisada_em = timezone.now()
        pub.save(update_fields=['relevancia', 'analise', 'tema_sugerido', 'analisada_em'])
