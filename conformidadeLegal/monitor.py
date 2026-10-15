"""
Monitoramento de diários oficiais (fase 3): acha publicações novas que podem criar
obrigação para a empresa e as deixa para a equipe avaliar.

Fontes:
- Diário Oficial do Estado do RS (DOE-RS), pela API REST pública que o próprio site
  usa (Procergs) — sem login, JSON, texto nascido digital;
- Diário Oficial da União (DOU), Seção 1, pelo INLABS da Imprensa Nacional — cadastro
  gratuito, um ZIP por seção e dia com um XML por ato.
Nenhuma das duas tem contrato de estabilidade: cada coleta grava uma ExecucaoMonitor,
e a tela avisa quando a última falhou.

O filtro é em duas camadas, nesta ordem, e só a segunda custa alguma coisa:
  1. aqui: de quem é (órgão), que tipo de matéria é, e palavras-chave no texto;
  2. tasks.triar_publicacoes: a IA lê o que passou e diz se interessa e por quê.
"""
import html
import io
import xml.etree.ElementTree as ET
import zipfile
import logging
import re
import time
import unicodedata
from datetime import date, timedelta
from html.parser import HTMLParser

import requests
from django.conf import settings
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
# Consultas PADRÃO ao DOE-RS (a migration 0004 grava no banco; a coleta lê de lá).
# A API recusa busca sem filtro e devolve no máximo 100 resultados, por isso a
# consulta é por dia e por órgão/tipo. `todas`: grava tudo do órgão (a FEPAM é o
# órgão licenciador — qualquer ato pode mexer com a licença); senão, só o que tiver
# palavra-chave. A entidade casa por trecho do nome; a sigla ("FEPAM") não acha nada.
CONSULTAS_DOE_RS = [
    {'rotulo': 'FEPAM', 'params': {'entidade': 'Fundação Estadual de Proteção Ambiental'}, 'todas': True},
    {'rotulo': 'SEMA / CONSEMA', 'params': {'entidade': 'Secretaria do Meio Ambiente e Infraestrutura'}, 'todas': False},
    {'rotulo': 'Leis estaduais', 'params': {'tipoMateria': 'Leis'}, 'todas': False},
    {'rotulo': 'Decretos', 'params': {'tipoMateria': 'Decretos'}, 'todas': False},
    # Resoluções de conselhos (CONSEMA, CRH) que não saiam em nome da SEMA.
    {'rotulo': 'Resoluções', 'params': {'tipoMateria': 'Resoluções'}, 'todas': False},
]


def carregar_consultas_doe_rs() -> list[dict]:
    from .models import OrgaoMonitor
    qs = OrgaoMonitor.objects.filter(fonte='DOE_RS')
    if not qs.exists():
        return CONSULTAS_DOE_RS
    return [{'rotulo': o.rotulo, 'params': {o.campo: o.valor}, 'todas': not o.exige_palavra}
            for o in qs if o.ativo and o.campo in ('entidade', 'tipoMateria')]


# Matérias que a FEPAM publica mas não criam obrigação para o regulado: súmulas
# de contrato, convênio e termo de cooperação. Comparado ao título, sem acento.
TITULOS_IGNORADOS = re.compile(r'^sumula (de|do|da) (contrato|convenio|termo|acordo|aditivo)')

# Matéria administrativa que nunca cria obrigação para empresa regulada.
TIPOS_IGNORADOS = {normalizar(t) for t in (
    'Contratos', 'Convênios', 'Recursos Humanos', 'Atos de Pessoal', 'Licitações', 'Extratos',
    'Editais', 'Aviso de Licitação', 'Homologação', 'Diárias', 'Férias',
)}

# Palavras-chave PADRÃO — as mesmas que a migration 0004 grava no banco, de onde a
# coleta passa a ler (tela "Configurações do monitor"). Termos comparados ao texto
# sem acento e sem maiúsculas, como palavra inteira; "re:" = expressão regular.
# "cal" sozinho não entra: casaria com "fiscal" e nomes próprios.
PALAVRAS_PADRAO = [
    ('calcário', ['calcario', 'calcarios', 'calcaria']),
    ('cal hidratada', ['cal hidratada', 'cal virgem', 'cal viva']),
    ('argamassa', ['argamassa', 'argamassas']),
    ('corretivo agrícola', ['corretivo agricola', 'corretivos agricolas', 'corretivo de acidez', 'corretivos de acidez']),
    ('mineração', ['mineracao', 'minerario', 'mineraria', 'minerarios', 'minerarias', 'mineradora', 'mineradoras']),
    ('lavra', ['lavra', 'lavras']),
    ('área minerada', ['area minerada', 'areas mineradas']),
    ('britagem', ['britagem', 'brita']),
    ('licenciamento', ['licenciamento']),
    ('licença de operação', ['licenca de operacao', 'licencas de operacao']),
    ('CONSEMA', ['consema']),
    ('diretriz técnica', ['diretriz tecnica', 'diretrizes tecnicas']),
    ('emissões atmosféricas', ['emissao atmosferica', 'emissoes atmosfericas', 'poluentes atmosfericos', 'fontes fixas']),
    ('material particulado', ['material particulado']),
    ('qualidade do ar', ['qualidade do ar']),
    ('efluentes', ['efluente', 'efluentes']),
    ('resíduos sólidos', ['residuos solidos']),
    ('recursos hídricos', ['recursos hidricos', 'outorga']),
    ('PRAD', ['prad', 'recuperacao de area degradada', 'recuperacao de areas degradadas']),
    ('potencial poluidor', ['potencial poluidor']),
    ('taxa ambiental', ['taxa de licenciamento', 'taxas de licenciamento', 'taxa ambiental', 'taxas ambientais']),
    ('Resolução 372', ['372/2018']),
    ('norma regulamentadora', ['norma regulamentadora', 'normas regulamentadoras', r're:nr-? ?\d{1,2}']),
    ('segurança e saúde no trabalho', ['seguranca e saude no trabalho']),
]


def _padrao(termos: list[str]):
    """Termos → uma regex de palavra inteira sobre o texto normalizado (None se nenhum termo é válido)."""
    partes = []
    for t in termos:
        if t.startswith('re:'):
            partes.append(t[3:].strip())
        elif normalizar(t).strip():
            partes.append(re.escape(normalizar(t).strip()))
    partes = [p for p in partes if p]
    return re.compile(r'\b(' + '|'.join(partes) + r')\b') if partes else None


def compilar_palavras(lista) -> list:
    return [(rotulo, padrao) for rotulo, termos in lista if (padrao := _padrao(termos))]


def carregar_palavras() -> list:
    """Palavras ativas do banco; sem nenhuma cadastrada (antes da migration), as padrão."""
    from .models import PalavraChaveMonitor
    qs = PalavraChaveMonitor.objects.all()
    if not qs.exists():
        return compilar_palavras(PALAVRAS_PADRAO)
    return compilar_palavras([(p.rotulo, p.lista_termos()) for p in qs if p.ativo])


def carregar_palavras_globais() -> list:
    """Palavras que valem para ato de qualquer órgão do DOU (as NBRs vigiadas, por exemplo)."""
    from .models import PalavraChaveMonitor
    return compilar_palavras([(p.rotulo, p.lista_termos())
                              for p in PalavraChaveMonitor.objects.filter(ativo=True, qualquer_orgao=True)])


ORIGEM_QUALQUER_ORGAO = 'Citação (qualquer órgão)'


def palavras_encontradas(texto: str, padroes=None) -> list[str]:
    alvo = normalizar(texto)
    padroes = compilar_palavras(PALAVRAS_PADRAO) if padroes is None else padroes
    return [rotulo for rotulo, padrao in padroes if padrao.search(alvo)]


def termo_valido(termo: str) -> str | None:
    """Erro legível para um termo "re:" que não compila (a tela valida antes de salvar)."""
    if termo.startswith('re:'):
        try:
            re.compile(termo[3:].strip())
        except re.error as e:
            return f'Expressão inválida em "{termo}": {e}'
    return None


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
        consultas, padroes = carregar_consultas_doe_rs(), carregar_palavras()
        for consulta in consultas:
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
                palavras = palavras_encontradas(texto, padroes)
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
                        palavras=palavras, origem=consulta['rotulo'][:120],
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


# ── Diário Oficial da União (INLABS) ──────────────────────────────────────
INLABS = 'https://inlabs.in.gov.br'
# Cabeçalho exigido no download pelo script oficial da Imprensa Nacional
# (github.com/Imprensa-Nacional/inlabs).
INLABS_ORIGEM = {'origem': '736372697074'}
LOGIN_INLABS_TENTATIVAS = 3
LOGIN_INLABS_ESPERA = 20    # segundos; a 2ª tentativa espera 20, a 3ª, 40

_NORMATIVOS = {normalizar(t) for t in (
    'Lei', 'Lei Complementar', 'Decreto', 'Medida Provisória', 'Resolução', 'Resolução Conjunta', 'Portaria',
    'Portaria Conjunta', 'Instrução Normativa', 'Instrução Normativa Conjunta', 'Deliberação',
)}
_LEIS = {normalizar(t) for t in ('Lei', 'Lei Complementar', 'Decreto', 'Medida Provisória')}

# O DOU publica ~400 atos por dia na Seção 1: o filtro é por ÓRGÃO (trecho do
# artCategory, sem acento) e tipo de ato, e só depois por palavra-chave. Medido em
# 06–14/10/2026: 2.276 atos → 3 candidatos (IBAMA, SQA/MMA e Resolução ANM 249).
# O resto do diário (energia/ANP/ANEEL, Previc, Saúde, comércio exterior…) fica de fora.
REGRAS_DOU = [
    # (rótulo, trecho do órgão, exige palavra-chave, grupo de tipos aceitos)
    ('ANM', 'agencia nacional de mineracao', False, 'NORMATIVOS'),
    ('CONAMA', 'conselho nacional do meio ambiente', False, 'NORMATIVOS'),
    ('Meio Ambiente (IBAMA, ANA…)', 'ministerio do meio ambiente', True, 'NORMATIVOS'),
    ('Trabalho e Emprego (NRs)', 'ministerio do trabalho', True, 'NORMATIVOS'),
    ('Leis e decretos federais', 'atos do poder executivo', True, 'LEIS'),
    ('Leis do Congresso', 'atos do poder legislativo', True, 'LEIS'),
]
_GRUPOS_DOU = {'NORMATIVOS': _NORMATIVOS, 'LEIS': _LEIS}


def carregar_regras_dou() -> list[tuple]:
    from .models import OrgaoMonitor
    qs = OrgaoMonitor.objects.filter(fonte='DOU')
    if not qs.exists():
        return REGRAS_DOU
    return [(o.rotulo, normalizar(o.valor), o.exige_palavra, o.tipos_dou or 'NORMATIVOS')
            for o in qs if o.ativo and o.campo == 'categoria']


def _regra_dou(categoria: str, tipo: str, regras=None):
    cat, tp = normalizar(categoria), normalizar(tipo)
    return next((r for r in (REGRAS_DOU if regras is None else regras)
                 if r[1] in cat and tp in _GRUPOS_DOU.get(r[3], _NORMATIVOS)), None)


def _sessao_inlabs(sessao):
    email = getattr(settings, 'CONFORMIDADE_INLABS_EMAIL', '')
    senha = getattr(settings, 'CONFORMIDADE_INLABS_SENHA', '')
    if not email or not senha:
        raise FalhaFonte('INLABS sem credencial: defina CONFORMIDADE_INLABS_EMAIL e CONFORMIDADE_INLABS_SENHA.')
    # O INLABS oscila (manutenção, firewall do site barrando por um tempo): sem o cookie
    # nem sempre é senha errada. Tenta de novo antes de registrar a falha, e só culpa a
    # senha quando o site devolve a tela de acesso.
    for tentativa in range(LOGIN_INLABS_TENTATIVAS):
        if tentativa:
            time.sleep(LOGIN_INLABS_ESPERA * tentativa)
        try:
            r = sessao.post(f'{INLABS}/logar.php', data={'email': email, 'password': senha},
                            headers={'User-Agent': CABECALHOS['User-Agent']}, timeout=60)
        except requests.RequestException as e:
            falha = f'INLABS fora do ar: {e}'[:300]
            continue
        if 'inlabs_session_cookie' in sessao.cookies.get_dict():
            return
        if 'acessar.php' in (getattr(r, 'url', '') or ''):
            falha = 'Login no INLABS recusado — confira o e-mail e a senha da conta.'
        else:
            falha = (f'INLABS não respondeu como esperado ao login (HTTP {getattr(r, "status_code", "?")}) '
                     '— instabilidade do site; a próxima coleta tenta de novo.')
    raise FalhaFonte(f'{falha} ({LOGIN_INLABS_TENTATIVAS} tentativas)')


def _zips_secao1(sessao, dia: date) -> list[str]:
    """Arquivos da Seção 1 do dia (a normal e as extras), como o Ro-DOU: lendo a lista
    da página, e não montando o nome — extra tem nome próprio."""
    r = sessao.get(f'{INLABS}/index.php', params={'p': dia.isoformat()},
                   headers={'User-Agent': CABECALHOS['User-Agent']}, timeout=60)
    if 'acessar.php' in r.url:
        raise FalhaFonte('Sessão do INLABS caiu antes da lista do dia.')
    nomes = re.findall(r'dl=([^"&]+?\.zip)', html.unescape(r.text))
    return sorted({n for n in nomes if re.search(r'-DO1[A-Z]?\.zip$', n)})


def _atos_do_zip(conteudo: bytes):
    with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
        for nome in zf.namelist():
            if not nome.lower().endswith('.xml'):
                continue
            try:
                artigo = ET.fromstring(zf.read(nome).decode('utf-8-sig')).find('article')
            except (ET.ParseError, UnicodeDecodeError):
                continue
            if artigo is not None:
                yield artigo


def coletar_dou(dia: date, sessao=None) -> ExecucaoMonitor:
    """Seção 1 do DOU de um dia pelo INLABS. Idempotente, como a do DOE-RS."""
    execucao = ExecucaoMonitor.objects.create(fonte='DOU', data_referencia=dia)
    sessao = sessao or requests.Session()
    try:
        _sessao_inlabs(sessao)
        ja = set(PublicacaoMonitorada.objects.filter(fonte='DOU', data_publicacao__gte=dia - timedelta(days=3))
                 .values_list('id_externo', flat=True))
        regras, padroes, globais = carregar_regras_dou(), carregar_palavras(), carregar_palavras_globais()
        for arquivo in _zips_secao1(sessao, dia):
            r = sessao.get(f'{INLABS}/index.php', params={'p': dia.isoformat(), 'dl': arquivo},
                           headers={**INLABS_ORIGEM, 'User-Agent': CABECALHOS['User-Agent']}, timeout=300)
            if r.status_code != 200 or r.content[:2] != b'PK':
                raise FalhaFonte(f'{arquivo}: o INLABS não devolveu o ZIP (HTTP {r.status_code}).')
            time.sleep(PAUSA)
            for art in _atos_do_zip(r.content):
                execucao.examinadas += 1
                id_ext = art.get('idMateria') or art.get('id') or ''
                if not id_ext or id_ext in ja:
                    continue
                regra = _regra_dou(art.get('artCategory', ''), art.get('artType', ''), regras)
                # Fora dos órgãos acompanhados, só entra ato normativo que cite uma
                # palavra "de qualquer órgão" (NBR de licença) — o texto é lido só nesse caso.
                if not regra and not (globais and normalizar(art.get('artType', '')) in _NORMATIVOS):
                    continue
                corpo = art.find('body')
                ident = (corpo.findtext('Identifica') or '').strip() if corpo is not None else ''
                ementa = (corpo.findtext('Ementa') or '').strip() if corpo is not None else ''
                texto = texto_de_html(corpo.findtext('Texto') or '') if corpo is not None else ''
                conteudo = '\n'.join((ident, ementa, texto))
                if not regra:
                    palavras = palavras_encontradas(conteudo, globais)
                    if not palavras:
                        continue
                    regra = (ORIGEM_QUALQUER_ORGAO, '', True, 'NORMATIVOS')
                else:
                    palavras = palavras_encontradas(conteudo, padroes)
                if regra[2] and not palavras:
                    continue
                try:
                    PublicacaoMonitorada.objects.create(
                        fonte='DOU', id_externo=id_ext[:64],
                        data_publicacao=_data_br(art.get('pubDate')) or dia,
                        orgao=(art.get('artCategory') or '')[:255], tipo=(art.get('artType') or '')[:120],
                        titulo=(ident or art.get('name') or '')[:500],
                        texto=('\n'.join(t for t in (ementa, texto) if t))[:60000],
                        link=html.unescape(art.get('pdfPage') or '')[:500], pagina=_int(art.get('numberPage')),
                        palavras=palavras, origem=regra[0][:120],
                    )
                    ja.add(id_ext)
                    execucao.novas += 1
                except IntegrityError:
                    pass
        execucao.ok = True
    except FalhaFonte as e:
        execucao.erro = str(e)
        logger.warning('Monitor DOU %s falhou: %s', dia, e)
    except Exception as e:  # noqa: BLE001
        execucao.erro = f'{type(e).__name__}: {e}'[:2000]
        logger.exception('Monitor DOU %s falhou', dia)
    execucao.concluido_em = timezone.now()
    execucao.save()
    return execucao


def _data_br(valor):
    try:
        d, m, a = str(valor).split('/')
        return date(int(a), int(m), int(d))
    except (TypeError, ValueError):
        return None


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
    if pub.fonte == 'DOU':
        siglas = [('agencia nacional de mineracao', 'ANM'), ('conselho nacional do meio ambiente', 'CONAMA'),
                  ('instituto brasileiro do meio ambiente', 'IBAMA'), ('agencia nacional de aguas', 'ANA'),
                  ('ministerio do meio ambiente', 'MMA'), ('ministerio do trabalho', 'MTE')]
        orgao = next((sg for trecho, sg in siglas if trecho in org), '')
        # A sigla do título ("PORTARIA SQA/MMA Nº…") é mais precisa que a do órgão-pai.
        m_sigla = re.search(r'\b(?:portaria|resolucao|instrucao normativa|deliberacao)\s+([a-z]{2,8}(?:/[a-z]{2,8})?)\s+n',
                            normalizar(pub.titulo))
        if m_sigla:
            orgao = m_sigla.group(1).upper()
        dados_esfera = 'FEDERAL'
    elif 'consema' in alvo:
        orgao = 'CONSEMA'
    elif 'protecao ambiental' in org:
        orgao = 'FEPAM'
    elif 'meio ambiente' in org:
        orgao = 'SEMA'
    elif 'governador' in org:
        orgao = 'RS'
    else:
        orgao = pub.orgao[:120]
    if pub.fonte != 'DOU':
        dados_esfera = 'ESTADUAL'
    return {
        'tipo': tipo, 'numero': numero[:60], 'ano': ano, 'orgao': orgao[:120], 'esfera': dados_esfera,
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
