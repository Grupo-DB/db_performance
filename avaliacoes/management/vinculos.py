"""Quem cada avaliador avalia, e o que ainda está pendente no período.

Dois caminhos, somados:

- individual: ``Avaliador.avaliados`` (o vínculo pessoa a pessoa de sempre);
- por setor: ``Ambiente.avaliadores`` — o avaliador avalia todo colaborador
  avaliado daquele setor. Na tela "Setores" é o modelo ``Ambiente`` (os nomes
  estão trocados no banco: "Fábrica Argamassa" é Ambiente).

Pendência no período:

- vínculo individual, ou setor em modo ``todos``: pendente enquanto ESTE
  avaliador não avaliou;
- setor em modo ``qualquer``: sai da lista de todos assim que um dos
  avaliadores do setor avalia.

Quem chega pelos dois caminhos segue o individual, que é o mais exigente.

Tudo que precisa saber "quem o avaliador avalia" (telas, sino, e-mails de
cobrança, dashboard) passa por aqui — não ler ``avaliador.avaliados`` direto,
senão o vínculo por setor some daquele ponto.
"""
from django.db.models import F, Q
from django.utils import timezone

from .models import MODO_AVALIACAO_QUALQUER, Avaliacao, Avaliado, Avaliador


def _q_ativo():
    """Pelo setor só entra quem não foi demitido; o individual foi escolhido a dedo e fica como está."""
    return Q(data_demissao__isnull=True) | Q(data_demissao__gt=timezone.now())


def avaliados_do_avaliador(avaliador):
    """Todos os avaliados do avaliador: os individuais mais os dos setores dele."""
    pelo_setor = Q(ambiente__avaliadores=avaliador) & _q_ativo() & ~Q(pk=avaliador.pk)
    return Avaliado.objects.filter(Q(avaliadores=avaliador) | pelo_setor).distinct()


def avaliados_pendentes(avaliador, periodo):
    """Avaliados do avaliador ainda sem avaliação no período, pela regra do vínculo."""
    pendentes = avaliados_do_avaliador(avaliador).exclude(
        pk__in=Avaliacao.objects.filter(periodo=periodo, avaliador=avaliador).values('avaliado_id')
    )

    # Setor em modo "qualquer": a avaliação de um colega do mesmo setor encerra
    # para todos. F('avaliador') garante que quem avaliou é avaliador DAQUELE setor.
    feitos_no_setor = set(
        Avaliacao.objects.filter(
            periodo=periodo,
            avaliado__in=pendentes,
            avaliado__ambiente__modo_avaliacao=MODO_AVALIACAO_QUALQUER,
            avaliado__ambiente__avaliadores=F('avaliador'),
        ).values_list('avaliado_id', flat=True)
    )
    if not feitos_no_setor:
        return pendentes
    individuais = set(avaliador.avaliados.values_list('pk', flat=True))
    return pendentes.exclude(pk__in=feitos_no_setor - individuais)


def avaliadores_com_pendencias(periodo):
    """[(avaliador, queryset de pendentes)] só de quem tem algo pendente no período."""
    resultado = []
    for avaliador in Avaliador.objects.all():
        pendentes = avaliados_pendentes(avaliador, periodo)
        if pendentes.exists():
            resultado.append((avaliador, pendentes))
    return resultado
