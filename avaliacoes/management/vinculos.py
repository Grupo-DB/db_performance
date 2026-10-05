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


def q_ativo(prefixo=''):
    """
    Colaborador ativo: Situação marcada como ativa no cadastro E sem demissão passada.

    Vale para os dois caminhos (individual e setor) desde 05/10/2026 — antes o
    individual ficava como estava e o setor olhava só a data de demissão, então
    colaborador inativo sem data de demissão continuava pendente e nos indicadores.
    `prefixo` permite usar a mesma regra através de uma relação ('avaliado__').
    """
    return Q(**{f'{prefixo}situacao': True}) & (
        Q(**{f'{prefixo}data_demissao__isnull': True}) | Q(**{f'{prefixo}data_demissao__gt': timezone.now()})
    )


def avaliados_do_avaliador(avaliador):
    """Todos os avaliados ATIVOS do avaliador: os individuais mais os dos setores dele."""
    pelo_setor = Q(ambiente__avaliadores=avaliador) & ~Q(pk=avaliador.pk)
    return Avaliado.objects.filter(Q(avaliadores=avaliador) | pelo_setor).filter(q_ativo()).distinct()


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
    for avaliador in Avaliador.objects.filter(q_ativo()):
        pendentes = avaliados_pendentes(avaliador, periodo)
        if pendentes.exists():
            resultado.append((avaliador, pendentes))
    return resultado


def avaliados_por_colega(avaliador, periodo):
    """
    Avaliados do avaliador que já saíram da pendência dele porque um colega do
    setor (modo ``qualquer``) avaliou — e que ele próprio ainda não avaliou.

    A Nova Avaliação oferece esses como opcionais: uma segunda avaliação é
    permitida, mas não é cobrada de ninguém. Devolve ``[(avaliado, [nomes de
    quem já avaliou])]``.
    """
    pendentes = avaliados_pendentes(avaliador, periodo).values('pk')
    ja_avaliou = Avaliacao.objects.filter(periodo=periodo, avaliador=avaliador).values('avaliado_id')
    avaliados = list(
        avaliados_do_avaliador(avaliador).exclude(pk__in=pendentes).exclude(pk__in=ja_avaliou).order_by('nome')
    )
    quem = {}
    for avaliado_id, nome in (
        Avaliacao.objects.filter(periodo=periodo, avaliado__in=avaliados)
        .order_by('create_at').values_list('avaliado_id', 'avaliador__nome')
    ):
        quem.setdefault(avaliado_id, []).append(nome)
    return [(a, quem.get(a.pk, [])) for a in avaliados]
