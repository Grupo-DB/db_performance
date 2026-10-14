"""
Monitoramento de diários oficiais (fase 3): acha publicações novas que podem criar
obrigação para a empresa e as deixa para a equipe avaliar.

Fonte atual: Diário Oficial do Estado do RS (DOE-RS), pela API REST pública que o
próprio site usa (Procergs) — sem login, JSON, texto nascido digital. A API não é
documentada nem garantida: cada coleta grava uma ExecucaoMonitor, e a tela avisa
quando a última falhou. O DOU (INLABS) entra depois, na mesma estrutura.

O filtro é em duas camadas, nesta ordem, e só a segunda custa alguma coisa:
  1. aqui: de quem é (órgão), que tipo de matéria é, e palavras-chave no texto;
  2. tasks.triar_publicacoes: a IA lê o que passou e diz se interessa e por quê.
"""
import html
import io
import logging
import re
import time
import unicodedata
from datetime import date, timedelta
from html.parser import HTMLParser

import requests
from django.db import IntegrityError
from django.utils import timezone

from .models import ExecucaoMonitor, PublicacaoMonitorada

logger = logging.getLogger(__name__)

DOE_RS_API = 'https://secweb.procergs.com.br/doe/rest/public'
DOE_RS_MATERIA = 'https://www.diariooficial.rs.gov.br/materia?id={}'
CABECALHOS = {'User-Agent': 'ManagerDB-ConformidadeLegal/1.0 (monitor de normas; Grupo DB)',
              'Accept': 'application/json'}
PAUSA = 0.3          # segundos entre requisições: a API é pública, mas não é nossa
MAX_PAGINAS = 30     # 10 matérias por página; um dia de uma consulta nunca chega perto
DIAS_PARA_TRAS = 7   # se a coleta ficou parada, recupera no máximo uma semana


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento, para casar "calcário" com "CALCARIO"."""
    sem_acento = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', sem_acento.lower())


# ── O que procurar ────────────────────────────────────────────────────────
# Consultas ao DOE-RS. A API recusa busca sem filtro e devolve no máximo 100
# resultados, por isso a consulta é por dia e por órgão/tipo. `todas`: grava tudo
# do órgão (a FEPAM é o órgão licenciador — qualquer ato pode mexer com a licença);
# senão, só o que tiver palavra-chave. A entidade casa por trecho do nome; a
# sigla sozinha ("FEPAM") não acha nada.
CONSULTAS_DOE_RS = [
    {'rotulo': 'FEPAM', 'params': {'entidade': 'Fundação Estadual de Proteção Ambiental'}, 'todas': True},
    {'rotulo': 'SEMA / CONSEMA', 'params': {'entidade': 'Secretaria do Meio Ambiente e Infraestrutura'}, 'todas': False},
    {'rotulo': 'Leis estaduais', 'params': {'tipoMateria': 'Leis'}, 'todas': False},
    {'rotulo': 'Decretos', 'params': {'tipoMateria': 'Decretos'}, 'todas': False},
    # Resoluções de conselhos (CONSEMA, CRH) que não saiam em nome da SEMA.
    {'rotulo': 'Resoluções', 'params': {'tipoMateria': 'Resoluções'}, 'todas': False},
]

# Matérias que a FEPAM publica mas não criam obrigação para o regulado: súmulas
# de contrato, convênio e termo de cooperação. Comparado ao título, sem acento.
TITULOS_IGNORADOS = re.compile(r'^sumula (de|do|da) (contrato|convenio|termo|acordo|aditivo)')

# Matéria administrativa que nunca cria obrigação para empresa regulada.
TIPOS_IGNORADOS = {normalizar(t) for t in (
    'Contratos', 'Convênios', 'Recursos Humanos', 'Atos de Pessoal', 'Licitações', 'Extratos',
    'Editais', 'Aviso de Licitação', 'Homologação', 'Diárias', 'Férias',
)}

# Palavras-chave (procuradas no texto sem acento, como palavra inteira). O rótulo é
# o que aparece na tela. "cal" sozinho não entra: casaria com tudo ("cal." de
# "fiscal", "Cal" de nomes próprios) — o calcário e os produtos de cal entram por
# expressões mais longas.
PALAVRAS_CHAVE = [
    ('calcário', r'calcari[oa]s?'), ('cal hidratada', r'cal (hidratada|virgem|viva)'), ('argamassa', r'argamassas?'),
    ('corretivo agrícola', r'corretivos? (agricola|de acidez)'), ('mineração', r'mineracao|minerari[oa]s?|mineradoras?'),
    ('lavra', r'lavras?'), ('área minerada', r'areas? mineradas?'), ('britagem', r'britagem|brita'),
    ('licenciamento', r'licenciamento'), ('licença de operação', r'licencas? de operacao'),
    ('CONSEMA', r'consema'), ('diretriz técnica', r'diretriz(es)? tecnicas?'),
    ('emissões atmosféricas', r'emiss(ao|oes) atmosferic[ao]s?|poluentes atmosfericos|fontes fixas'),
    ('material particulado', r'material particulado'), ('qualidade do ar', r'qualidade do ar'),
    ('efluentes', r'efluentes?'), ('resíduos sólidos', r'residuos solidos'),
    ('recursos hídricos', r'recursos hidricos|outorga'), ('PRAD', r'prad|recuperacao de areas? degradadas?'),
    ('potencial poluidor', r'potencial poluidor'), ('taxa ambiental', r'taxas? (de licenciamento|ambientais?)'),
    ('Resolução 372', r'372/2018'),
]
_PADROES = [(rotulo, re.compile(r'\b(' + padrao + r')\b')) for rotulo, padrao in PALAVRAS_CHAVE]


def palavras_encontradas(texto: str) -> list[str]:
    alvo = normalizar(texto)
    return [rotulo for rotulo, padrao in _PADROES if padrao.search(alvo)]


# ── HTML do DOE → texto ───────────────────────────────────────────────────
class _Texto(HTMLParser):
    QUEBRA = {'p', 'br', 'div', 'tr', 'li', 'h1', 'h2', 'h3', 'h4', 'table'}

    def __init__(self):
        super().__init__()
        self.partes = []

    def handle_starttag(self, tag, attrs):
        if tag in self.QUEBRA:
            self.partes.append('\n')

    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.partes.append(' ')

    def handle_data(self, data):
        self.partes.append(data)


def texto_de_html(conteudo: str) -> str:
    p = _Texto()
    p.feed(conteudo or '')
    texto = html.unescape(''.join(p.partes)).replace('\xa0', ' ')
    linhas = [re.sub(r'[ \t]+', ' ', l).strip() for l in texto.split('\n')]
    return '\n'.join(l for l in linhas if l)


def titulo_de(texto: str) -> str:
    """Primeira linha com cara de título ("PORTARIA Nº 635/2026"), senão o começo do texto."""
    for linha in texto.split('\n')[:5]:
        if len(linha) >= 6:
            return linha[:300]
    return texto[:300]


# ── Coleta ────────────────────────────────────────────────────────────────
class FalhaFonte(Exception):
    """A fonte não respondeu como esperado (fora do ar ou mudou o formato)."""


def _get(sessao, url, params=None):
    ultimo = None
    for tentativa in range(3):
        try:
            r = sessao.get(url, params=params, headers=CABECALHOS, timeout=30)
            if r.status_code == 200:
                time.sleep(PAUSA)
                return r.json()
            ultimo = f'HTTP {r.status_code}'
        except (requests.RequestException, ValueError) as e:
            ultimo = str(e)[:200]
        time.sleep(2 * (tentativa + 1))
    raise FalhaFonte(f'{url}: {ultimo}')


def _ids_do_dia(sessao, dia: date, params: dict) -> list[dict]:
    itens = []
    for pagina in range(1, MAX_PAGINAS + 1):
        dados = _get(sessao, f'{DOE_RS_API}/materias', {
            'tipoDiario': 'doe', 'dataIni': dia.isoformat(), 'dataFim': dia.isoformat(), 'page': pagina, **params,
        })
        if not isinstance(dados, dict) or 'collection' not in dados:
            raise FalhaFonte(f'Resposta da busca sem "collection": {str(dados)[:200]}')
        lote = [c.get('procergs') or {} for c in dados['collection']]
        itens += [x for x in lote if x.get('id')]
        if len(lote) < int(dados.get('pageSize') or 10):
            break
    return itens


def coletar_doe_rs(dia: date, sessao=None) -> ExecucaoMonitor:
    """Uma passada no DOE-RS de um dia. Idempotente: rodar de novo só acrescenta o que faltou."""
    execucao = ExecucaoMonitor.objects.create(fonte='DOE_RS', data_referencia=dia)
    sessao = sessao or requests.Session()
    ja = set(PublicacaoMonitorada.objects.filter(fonte='DOE_RS', data_publicacao__gte=dia - timedelta(days=3))
             .values_list('id_externo', flat=True))
    vistos = set()
    try:
        for consulta in CONSULTAS_DOE_RS:
            for item in _ids_do_dia(sessao, dia, consulta['params']):
                id_ext = str(item['id'])
                if id_ext in vistos:
                    continue
                vistos.add(id_ext)
                execucao.examinadas += 1
                if id_ext in ja or normalizar(item.get('tipo', '')) in TIPOS_IGNORADOS:
                    continue
                materia = _get(sessao, f'{DOE_RS_API}/materias/{id_ext}')
                if normalizar(materia.get('tipoMateria', '')) in TIPOS_IGNORADOS:
                    continue
                texto = texto_de_html(materia.get('conteudo', ''))
                if TITULOS_IGNORADOS.search(normalizar(titulo_de(texto))):
                    continue
                palavras = palavras_encontradas(texto)
                if not palavras and not consulta['todas']:
                    continue
                try:
                    PublicacaoMonitorada.objects.create(
                        fonte='DOE_RS', id_externo=id_ext,
                        data_publicacao=_data(materia.get('data')) or dia,
                        orgao=(materia.get('orgao') or '')[:255],
                        tipo=(materia.get('tipoMateria') or item.get('tipo') or '')[:120],
                        titulo=titulo_de(texto)[:500], texto=texto[:60000],
                        link=DOE_RS_MATERIA.format(id_ext), pagina=_int(materia.get('pagina')),
                        palavras=palavras,
                    )
                    execucao.novas += 1
                except IntegrityError:
                    pass  # outra coleta gravou no meio do caminho
        execucao.ok = True
    except FalhaFonte as e:
        execucao.erro = str(e)
        logger.warning('Monitor DOE-RS %s falhou: %s', dia, e)
    except Exception as e:  # noqa: BLE001 — formato mudou: registra e segue, a tela avisa
        execucao.erro = f'{type(e).__name__}: {e}'[:2000]
        logger.exception('Monitor DOE-RS %s falhou', dia)
    execucao.concluido_em = timezone.now()
    execucao.save()
    return execucao


def dias_a_coletar(fonte: str, hoje: date) -> list[date]:
    """De depois da última coleta bem-sucedida até hoje (no máximo uma semana). Hoje sempre
    entra: rodar duas vezes no dia pega a 2ª edição e as extraordinárias."""
    ultima = (ExecucaoMonitor.objects.filter(fonte=fonte, ok=True, data_referencia__lt=hoje)
              .order_by('-data_referencia').values_list('data_referencia', flat=True).first())
    inicio = max(ultima + timedelta(days=1), hoje - timedelta(days=DIAS_PARA_TRAS)) if ultima else hoje
    return [inicio + timedelta(days=n) for n in range((hoje - inicio).days + 1)]


def _data(valor):
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def _int(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


# ── Publicação → norma ────────────────────────────────────────────────────
_TIPOS_TITULO = [
    ('INSTRUCAO_NORMATIVA', r'instrucao normativa'), ('RESOLUCAO', r'resolucao'), ('PORTARIA', r'portaria'),
    ('DECRETO', r'decreto'), ('LEI', r'lei( complementar)?'), ('OUTRO', r'diretriz tecnica'),
]


def dados_de_norma(pub: PublicacaoMonitorada) -> dict:
    """Primeiro rascunho da norma a partir da publicação; a equipe revisa na tela."""
    alvo = normalizar(pub.titulo + ' ' + pub.texto[:400])
    tipo = next((t for t, p in _TIPOS_TITULO if re.search(r'\b' + p + r'\b', normalizar(pub.titulo))), 'OUTRO')
    numero, ano = '', None
    m = re.search(r'n[o°º\.]*\s*([\d\.]+)\s*[/,-]\s*(\d{4})', alvo) or re.search(r'n[o°º\.]*\s*([\d\.]+)\s*,? de .{0,25}?(\d{4})', alvo)
    if m:
        numero, ano = m.group(1).strip('.'), int(m.group(2))
    org = normalizar(pub.orgao)
    if 'consema' in alvo:
        orgao = 'CONSEMA'
    elif 'protecao ambiental' in org:
        orgao = 'FEPAM'
    elif 'meio ambiente' in org:
        orgao = 'SEMA'
    elif 'governador' in org:
        orgao = 'RS'
    else:
        orgao = pub.orgao[:120]
    return {
        'tipo': tipo, 'numero': numero[:60], 'ano': ano, 'orgao': orgao, 'esfera': 'ESTADUAL',
        'tema': pub.tema_sugerido or 'AMBIENTAL', 'ementa': pub.titulo or pub.texto[:300],
        'link': pub.link, 'data_publicacao': pub.data_publicacao, 'situacao': 'VIGENTE',
        'observacao': f'Cadastrada a partir do {pub.get_fonte_display()} de {pub.data_publicacao:%d/%m/%Y}'
                      + (f', pág. {pub.pagina}' if pub.pagina else '') + '.',
    }


def pdf_da_publicacao(pub: PublicacaoMonitorada) -> bytes:
    """PDF com o texto publicado — é o que a leitura por IA da norma recebe.

    O DOE-RS não oferece o PDF da matéria (o "pdf-inline" devolve o .docx enviado
    pelo órgão), então o PDF é montado aqui a partir do texto oficial.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    estilos = getSampleStyleSheet()
    saida = io.BytesIO()
    doc = SimpleDocTemplate(saida, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm, title=pub.titulo[:120])
    esc = lambda t: html.escape(t)  # noqa: E731
    corpo = [
        Paragraph(esc(f'{pub.get_fonte_display()} — {pub.data_publicacao:%d/%m/%Y}'
                      + (f' — pág. {pub.pagina}' if pub.pagina else '')), estilos['Normal']),
        Paragraph(esc(pub.orgao), estilos['Normal']),
        Paragraph(esc(pub.link), estilos['Normal']),
        Spacer(1, 6 * mm),
    ]
    corpo += [Paragraph(esc(linha), estilos['BodyText']) for linha in pub.texto.split('\n') if linha.strip()]
    doc.build(corpo)
    return saida.getvalue()
