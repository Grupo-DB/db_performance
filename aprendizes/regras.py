"""Prazos do contrato de experiência e a leitura da planilha antiga."""
import re
import unicodedata
from datetime import date, datetime, timedelta

from .models import DIAS_PRIMEIRO_VENCIMENTO, DIAS_PRORROGACAO, Etapa


def vencimentos(admissao: date) -> dict[str, date]:
    """Contrato de 30 + 60 dias contado com o dia da admissão: o 30º dia é admissão + 29."""
    return {
        Etapa.PRIMEIRO_VENCIMENTO: admissao + timedelta(days=DIAS_PRIMEIRO_VENCIMENTO - 1),
        Etapa.PRORROGACAO: admissao + timedelta(days=DIAS_PRORROGACAO - 1),
    }


def chave_nome(nome: str) -> str:
    """Nome sem acento, caixa e espaço sobrando — 'ÉBERTON' e 'EBÉRTON' continuam diferentes."""
    texto = unicodedata.normalize('NFD', str(nome or '')).encode('ascii', 'ignore').decode()
    return ' '.join(texto.upper().split())


def _limpo(v) -> str:
    return chave_nome(v)


# "1º" e "1°" perdem o símbolo na limpeza (NFD + ASCII): os dois viram "1 VENCIMENTO".
TIPOS_PLANILHA = {
    '1 VENCIMENTO': Etapa.PRIMEIRO_VENCIMENTO,
    'PRIMEIRO VENCIMENTO': Etapa.PRIMEIRO_VENCIMENTO,
    'PRORROGACAO': Etapa.PRORROGACAO,
    'EFETIVACAO': Etapa.EFETIVACAO,
    'ENCERRAMENTO': Etapa.ENCERRAMENTO,
}


def tipo_da_planilha(texto) -> str | None:
    return TIPOS_PLANILHA.get(_limpo(texto))


def situacao_da_planilha(texto) -> tuple[str, str]:
    """(situação, pendência). Texto livre que não é situação vai para a pendência."""
    t = _limpo(texto)
    if not t:
        return Etapa.PENDENTE, ''
    if t in ('FEITO', 'CONCLUIDO'):
        return Etapa.CONCLUIDO, ''
    if t.startswith('PENDENTE'):
        resto = t.replace('PENDENTE', '').strip()
        return Etapa.PENDENTE, resto.capitalize()
    if t in ('DEMITIDO', 'DEMITIR', 'DESLIGADO', 'PEDIDO DE DEMISSAO'):
        return Etapa.DESLIGADO, '' if t != 'DEMITIR' else 'Demitir'
    if t == 'DISPENSADO':
        return Etapa.DISPENSADO, ''
    if 'AFASTAMENTO' in t:
        return Etapa.AFASTADO, ''
    return Etapa.PENDENTE, str(texto).strip()  # "COM RITA"


def checklist_do_texto(texto) -> dict[str, bool]:
    """Lê "Feedback ok - Falta brinde", "CAMISETA OK", "Passar feedback", "INFORMADO"."""
    t = _limpo(texto)
    marcas = {}
    for campo, palavra in (('feedback_dado', 'FEEDBACK'), ('brinde_entregue', 'BRINDE'), ('camiseta_entregue', 'CAMISETA')):
        if palavra in t:
            falta = re.search(rf'(FALTA|PASSAR|MANDAR)[^-]*{palavra}', t) or re.search(rf'FALTA {palavra}', t)
            marcas[campo] = not falta and bool(re.search(rf'{palavra}\s*OK', t))
    return marcas


def data_da_planilha(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    texto = str(v or '').strip()
    for formato in ('%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None
