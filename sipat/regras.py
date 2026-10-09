"""Quem concorre a cada prêmio.

Fica fora da view para a urna (o sorteio) e a contagem que a tela mostra antes
de sortear usarem exatamente a mesma regra.
"""
from datetime import date, timedelta

from django.db.models import Count, Q

from .models import Participante, Premio, Presenca


def dias_uteis(inicio: date, fim: date) -> list[str]:
    dias, d = [], inicio
    while d <= fim:
        if d.weekday() < 5:
            dias.append(d.isoformat())
        d += timedelta(days=1)
    return dias


def dias_do_evento(evento) -> list[str]:
    return sorted(evento.dias or dias_uteis(evento.data_inicio, evento.data_fim))


def ids_semana_inteira(evento) -> set[int]:
    """Presentes em TODOS os dias do evento, em qualquer turno."""
    dias = dias_do_evento(evento)
    if not dias:
        return set()
    linhas = (
        Presenca.objects
        .filter(participante__evento=evento, data__in=dias)
        .values('participante_id')
        .annotate(n=Count('data', distinct=True))
        .filter(n=len(dias))
    )
    return {l['participante_id'] for l in linhas}


def concorrentes(premio: Premio):
    """Participantes que podem ser sorteados para o prêmio agora."""
    evento = premio.evento
    qs = Participante.objects.filter(evento=evento, ativo=True).exclude(sorteios__evento=evento)

    if premio.regra == Premio.REGRA_SEMANA:
        qs = qs.filter(id__in=ids_semana_inteira(evento))
    elif premio.regra == Premio.REGRA_DIA:
        if not premio.data:
            return qs.none()
        filtro = Q(presencas__data=premio.data)
        if premio.turno:
            filtro &= Q(presencas__turno=premio.turno)
        qs = qs.filter(filtro)
    else:
        qs = qs.filter(presencas__isnull=False)

    return qs.distinct()
