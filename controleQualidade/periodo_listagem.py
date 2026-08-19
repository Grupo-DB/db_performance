"""
Recorte por período das listagens do Controle de Qualidade.

As telas de Amostras e de OS Encerradas abrem mostrando só os últimos dias (60 e 90,
respectivamente). Antes o recorte era feito no navegador, depois de baixar a base
inteira — `fechadas/` são ~4,2 MB. Com estes parâmetros o servidor devolve só o
recorte, e "Todas as datas" na tela continua funcionando: é a chamada sem parâmetro.

Uso na view:

    limite = limite_periodo(request)
    qs = Amostra.objects.filter(filtro_periodo(limite))              # campos da amostra
    qs = Analise.objects.filter(filtro_periodo(limite, 'amostra__')) # via FK

Aceita `?dias=90` (relativo a hoje) ou `?desde=2026-05-21` (data exata; tem
precedência). Sem parâmetro — ou com valor inválido — não filtra nada, então nenhum
consumidor antigo do endpoint muda de comportamento.
"""
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone


def limite_periodo(request):
    """Data mínima pedida na query string, ou None quando não há recorte."""
    desde = (request.query_params.get('desde') or '').strip()
    if desde:
        try:
            return date.fromisoformat(desde[:10])
        except ValueError:
            return None

    dias = (request.query_params.get('dias') or '').strip()
    if dias:
        try:
            n = int(dias)
        except ValueError:
            return None
        if n > 0:
            return timezone.localdate() - timedelta(days=n)
    return None


def filtro_periodo(limite, prefixo=''):
    """
    Q() do recorte: entra quem tem data de entrada OU de coleta a partir do limite.

    As duas datas são consideradas porque amostra de OS expressa costuma não ter data
    de entrada e a de plano às vezes não tem data de coleta — é a mesma regra que a
    tela aplicava (ver shared/periodo.ts no frontend).

    Amostra com as DUAS datas em branco entra sempre: sumir da tela por falta de
    cadastro seria perder o registro de vista, justamente o que precisa de correção.

    Sem limite devolve um Q() vazio, que o Django ignora no filter().
    """
    if not limite:
        return Q()

    entrada = f'{prefixo}data_entrada'
    coleta = f'{prefixo}data_coleta'
    return (
        Q(**{f'{entrada}__gte': limite})
        | Q(**{f'{coleta}__gte': limite})
        | (Q(**{f'{entrada}__isnull': True}) & Q(**{f'{coleta}__isnull': True}))
    )
