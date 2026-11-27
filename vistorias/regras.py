"""
Regras puras (sem banco) do escopo v2.1 — testáveis com os exemplos das seções 11.1 e 11.2.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from .models import (BIMESTRAL, CRITICA, CRITICO, INSATISFATORIO, LEVE, MEDIA, MENSAL, SATISFATORIO, TRIMESTRAL)

# 3.4: todos os ciclos começam em janeiro.
MESES_DO_CICLO = {
    MENSAL: list(range(1, 13)),
    BIMESTRAL: [1, 3, 5, 7, 9, 11],
    TRIMESTRAL: [1, 4, 7, 10],
}

NOMES_MES = ['', 'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']


def meses_previstos(periodicidade: str, a_partir_de: int = 1) -> list[int]:
    return [m for m in MESES_DO_CICLO.get(periodicidade, []) if m >= a_partir_de]


def limites_do_mes(ano: int, mes: int):
    """(início, fim) do mês como datetimes conscientes do fuso do projeto."""
    tz = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime.combine(date(ano, mes, 1), time.min), tz)
    ultimo = calendar.monthrange(ano, mes)[1]
    fim = timezone.make_aware(datetime.combine(date(ano, mes, ultimo), time.max), tz)
    return inicio, fim


def mes_encerrado(ano: int, mes: int, hoje: date | None = None) -> bool:
    hoje = hoje or timezone.localdate()
    return (ano, mes) < (hoje.year, hoje.month)


def chave_mes(ano: int, mes: int) -> int:
    return ano * 12 + (mes - 1)


def de_chave(chave: int) -> tuple[int, int]:
    return chave // 12, chave % 12 + 1


# ── Resultado da vistoria (seção 7) ────────────────────────────────────────────
PESO = {LEVE: 1, MEDIA: 2, CRITICA: 3}


def resultado(ncs: list[tuple[str, bool]]) -> str:
    """
    ``ncs`` = [(criticidade, conta)] das respostas NC. ``conta`` = False para NC abonada
    (no resultado final) ou cancelada pelo GEO. Sem notas nem pontos: vale a maior criticidade.
    """
    maior = max((PESO[c] for c, conta in ncs if conta), default=0)
    if maior >= PESO[CRITICA]:
        return CRITICO
    if maior >= PESO[MEDIA]:
        return INSATISFATORIO
    return SATISFATORIO


# ── Indicador (seção 11) ───────────────────────────────────────────────────────
S, I, C, NR, D = 'S', 'I', 'C', 'NR', 'D'


@dataclass
class EntradaMes:
    """O que se sabe de um equipamento num mês, já resolvido do banco."""
    elegivel: bool                      # ativo e a partir da 1ª vistoria programada
    item: str | None = None             # None (não previsto) | 'PROGRAMADA' | 'DISPENSADA'
    programada: str | None = None       # resultado da vistoria programada REALIZADA NO MÊS
    programada_validada: bool = True
    ultima_valida: str | None = None    # resultado da última vistoria válida até o fim do mês
    ultima_validada: bool = True
    suspenso: bool = False              # suspenso em qualquer dia do mês


@dataclass
class SaidaMes:
    resultado: str | None               # S/I/C/NR/D ou None (fora do cálculo)
    herdado: bool = False
    considerado: bool = False           # entra no denominador
    satisfatorio: bool = False          # entra no numerador
    suspenso: bool = False
    sem_validacao: bool = False


def classificar_mes(e: EntradaMes) -> SaidaMes:
    if not e.elegivel:
        return SaidaMes(resultado=None)
    if e.item == 'DISPENSADA':
        if e.suspenso:
            # a dispensa não anula suspensão vigente: entra, sem contribuir
            return SaidaMes(resultado=D, considerado=True, suspenso=True)
        return SaidaMes(resultado=D)
    if e.item == 'PROGRAMADA':
        res, herdado, validada = (e.programada, False, e.programada_validada) if e.programada else (NR, False, True)
    else:
        res, herdado, validada = (e.ultima_valida, True, e.ultima_validada) if e.ultima_valida else (NR, True, True)
    return SaidaMes(resultado=res, herdado=herdado, considerado=True,
                    satisfatorio=(res == S and not e.suspenso), suspenso=e.suspenso,
                    sem_validacao=(res in (S, I, C) and not validada))


def _2(v: Decimal) -> Decimal:
    return v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@dataclass
class Indicador:
    satisfatorios: int = 0
    considerados: int = 0
    dispensados: int = 0
    elegiveis: int = 0
    percentual: Decimal | None = None   # None = "Não aplicável"
    detalhes: dict = field(default_factory=dict)


def indicador_mensal(saidas: list[SaidaMes]) -> Indicador:
    ind = Indicador()
    for s in saidas:
        if s.resultado is None:
            continue
        ind.elegiveis += 1
        if s.resultado == D and not s.considerado:
            ind.dispensados += 1
        if s.considerado:
            ind.considerados += 1
            if s.satisfatorio:
                ind.satisfatorios += 1
    if ind.considerados:
        ind.percentual = _2(Decimal(ind.satisfatorios * 100) / Decimal(ind.considerados))
    return ind


def indicador_trimestral(mensais: list[Decimal | None]) -> Decimal | None:
    """Média aritmética dos mensais; mês "Não aplicável" fica fora (11.3)."""
    validos = [m for m in mensais if m is not None]
    if not validos:
        return None
    return _2(sum(validos, Decimal(0)) / Decimal(len(validos)))


def trimestre_do_mes(mes: int) -> int:
    return (mes - 1) // 3 + 1


def meses_do_trimestre(t: int) -> list[int]:
    return [3 * (t - 1) + 1, 3 * (t - 1) + 2, 3 * (t - 1) + 3]


# ── Prazo do fechamento (11.3): até o 5º dia útil do mês seguinte ─────────────
def quinto_dia_util(ano: int, mes: int) -> date:
    """5º dia útil (seg–sex) do mês seguinte a (ano, mes). Feriados não entram."""
    a, m = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    d, uteis = date(a, m, 1), 0
    while True:
        if d.weekday() < 5:
            uteis += 1
            if uteis == 5:
                return d
        d = date.fromordinal(d.toordinal() + 1)
