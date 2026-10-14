"""
Leitura de normas/licenças em PDF pelo Claude, hospedado no Microsoft Foundry.

A IA nunca é a fonte da obrigação: ela lê o documento que a equipe anexou e
devolve sugestões, cada uma com o trecho literal e a página de onde saiu. Quem
aprova confere o trecho na tela de revisão antes de virar requisito.

Configuração (variáveis de ambiente, no .env lido pelo settings.py):
    CONFORMIDADE_IA_FOUNDRY_RESOURCE  nome do recurso (o <nome> de
                                      https://<nome>.services.ai.azure.com)
    CONFORMIDADE_IA_FOUNDRY_KEY       chave do recurso
    CONFORMIDADE_IA_MODELO            nome da implantação do modelo (padrão: claude-opus-5-5)
    CONFORMIDADE_IA_PERFIL_EMPRESA    opcional: atividades/unidades, para a IA
                                      marcar o que parece não se aplicar (o texto
                                      da tela Configurações do monitor tem precedência)
"""
import base64
import io
import json
import logging
import re

from django.conf import settings

from . import normas_tecnicas
from .models import TEMAS

logger = logging.getLogger(__name__)

# Base64 incha ~33% e o pedido inteiro tem teto de 32 MB.
LIMITE_PDF_BYTES = 20 * 1024 * 1024
MODELO_PADRAO = 'claude-opus-5-5'

PERIODICIDADES = [0, 1, 3, 6, 12, 24]

ESQUEMA = {
    'type': 'object',
    'properties': {
        'resumo': {
            'type': 'string',
            'description': 'Uma ou duas frases sobre o documento e o que ele exige da empresa.',
        },
        'itens': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'referencia': {'type': 'string', 'description': 'Artigo, parágrafo, item ou nº da condicionante. Ex.: "Art. 16, § 2º", "Condicionante 7".'},
                    'descricao': {'type': 'string', 'description': 'A obrigação em linguagem de quem executa: o que fazer, com que frequência, para quem entregar.'},
                    'tema': {'type': 'string', 'enum': [t for t, _ in TEMAS]},
                    'periodicidade_meses': {'type': 'integer', 'enum': PERIODICIDADES, 'description': '0 = obrigação única; senão, de quantos em quantos meses verificar.'},
                    'prazo_legal': {'type': 'string', 'description': 'Data fixa AAAA-MM-DD quando o texto der uma data exata; senão string vazia.'},
                    'trecho': {'type': 'string', 'description': 'Cópia LITERAL do trecho do documento que cria a obrigação, sem parafrasear.'},
                    'pagina': {'type': 'integer', 'description': 'Página do PDF onde está o trecho (1 = primeira).'},
                    'observacao': {'type': 'string', 'description': 'Dúvida de aplicabilidade ou ressalva; string vazia se não houver.'},
                },
                'required': ['referencia', 'descricao', 'tema', 'periodicidade_meses', 'prazo_legal', 'trecho', 'pagina', 'observacao'],
                'additionalProperties': False,
            },
        },
        'normas_tecnicas': {
            'type': 'array',
            'description': 'Normas técnicas ABNT NBR (inclusive NBR ISO/IEC) citadas no documento.',
            'items': {
                'type': 'object',
                'properties': {
                    'codigo': {'type': 'string', 'description': 'Código como aparece. Ex.: "ABNT NBR 10004:2004", "NBR ISO 14001".'},
                    'titulo': {'type': 'string', 'description': 'Título da norma se o documento trouxer; senão string vazia.'},
                    'trecho': {'type': 'string', 'description': 'Cópia LITERAL da frase que cita a norma.'},
                    'pagina': {'type': 'integer', 'description': 'Página do PDF onde está a citação (1 = primeira).'},
                },
                'required': ['codigo', 'titulo', 'trecho', 'pagina'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['resumo', 'itens', 'normas_tecnicas'],
    'additionalProperties': False,
}

SISTEMA = """Você é analista de conformidade legal (meio ambiente, SST e mineração) de uma empresa brasileira.
Vai receber um documento legal — lei, norma, licença ambiental, outorga ou TAC — e deve listar as
obrigações concretas que ele impõe a quem é regulado.

Regras:
- Use somente o documento recebido. Não acrescente obrigações de outras normas, mesmo que você as conheça.
- Uma obrigação por item. Junte num item só o que é a mesma ação; separe ações diferentes.
- "trecho" é cópia literal do documento (pode encurtar com "..." no meio), nunca paráfrase. Se não
  conseguir citar, não inclua o item.
- Ignore definições, considerandos, competências de órgãos públicos e sanções: só o que o regulado
  precisa fazer, manter, monitorar, entregar ou evitar.
- Periodicidade: use a do texto (semestral = 6, anual = 12...). Obrigação contínua sem frequência
  definida (ex.: "manter", "evitar") → 12, para ser verificada anualmente. Ação que se cumpre uma vez → 0.
- Escreva a descrição em português claro, começando por um verbo no infinitivo.
- Em "normas_tecnicas", liste cada norma ABNT NBR (inclusive NBR ISO/IEC) que o documento cita
  expressamente, uma vez cada, com a frase onde aparece. Só as citadas no texto; não deduza outras."""


class PaginasInvalidas(ValueError):
    """Texto de páginas que não dá para usar; a mensagem vai direto para a tela."""


def contar_paginas(conteudo_pdf: bytes) -> int:
    from pypdf import PdfReader
    return len(PdfReader(io.BytesIO(conteudo_pdf)).pages)


def interpretar_paginas(texto: str, total: int) -> list[int]:
    """'20-21, 24-35' → [20, 21, 24, ..., 35] (numeração do PDF, 1 = primeira).

    Vazio devolve lista vazia, que quer dizer "o documento inteiro". Aceita vírgula
    ou ponto e vírgula entre os pedaços e hífen ou travessão nos intervalos.
    """
    texto = (texto or '').strip()
    if not texto:
        return []
    paginas = set()
    for pedaco in re.split(r'[,;]', texto):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        m = re.fullmatch(r'(\d+)\s*(?:[-–—]\s*(\d+))?', pedaco)
        if not m:
            raise PaginasInvalidas(f'"{pedaco}" não é uma página nem um intervalo. Use, por exemplo: 20-21, 24-35.')
        inicio = int(m.group(1))
        fim = int(m.group(2) or inicio)
        if inicio > fim:
            raise PaginasInvalidas(f'Intervalo invertido: "{pedaco}".')
        if inicio < 1 or fim > total:
            raise PaginasInvalidas(f'"{pedaco}" está fora do documento, que tem {total} página(s).')
        paginas.update(range(inicio, fim + 1))
    return sorted(paginas)


def descrever_paginas(paginas: list[int]) -> str:
    """[20, 21, 24, 25, 26] → '20-21, 24-26' — a forma guardada e mostrada na tela."""
    partes, i = [], 0
    while i < len(paginas):
        j = i
        while j + 1 < len(paginas) and paginas[j + 1] == paginas[j] + 1:
            j += 1
        partes.append(str(paginas[i]) if i == j else f'{paginas[i]}-{paginas[j]}')
        i = j + 1
    return ', '.join(partes)


def recortar_pdf(conteudo_pdf: bytes, paginas: list[int]) -> bytes:
    """Um PDF só com as páginas pedidas, na ordem do original."""
    from pypdf import PdfReader, PdfWriter
    leitor = PdfReader(io.BytesIO(conteudo_pdf))
    escritor = PdfWriter()
    for n in paginas:
        escritor.add_page(leitor.pages[n - 1])
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


class IANaoConfigurada(Exception):
    pass


class FalhaExtracao(Exception):
    pass


def perfil_empresa() -> str:
    """O da tela (Configurações do monitor), se preenchido; senão o do servidor (.env)."""
    from .models import ConfiguracaoMonitor
    cfg = ConfiguracaoMonitor.objects.filter(pk=1).only('perfil_empresa').first()
    return ((cfg.perfil_empresa if cfg else '') or getattr(settings, 'CONFORMIDADE_IA_PERFIL_EMPRESA', '')).strip()


def configurada() -> bool:
    return bool(getattr(settings, 'CONFORMIDADE_IA_FOUNDRY_RESOURCE', '')
                and getattr(settings, 'CONFORMIDADE_IA_FOUNDRY_KEY', ''))


def modelo() -> str:
    return getattr(settings, 'CONFORMIDADE_IA_MODELO', '') or MODELO_PADRAO


def _cliente():
    if not configurada():
        raise IANaoConfigurada('IA não configurada: defina CONFORMIDADE_IA_FOUNDRY_RESOURCE e CONFORMIDADE_IA_FOUNDRY_KEY.')
    # Importado aqui: o SDK só é exigido onde a IA é usada (o resto do projeto sobe sem ele).
    from anthropic import AnthropicFoundry
    return AnthropicFoundry(
        resource=settings.CONFORMIDADE_IA_FOUNDRY_RESOURCE,
        api_key=settings.CONFORMIDADE_IA_FOUNDRY_KEY,
        timeout=600,
    )


def _instrucao(norma, ja_cadastrados: list[str], paginas: list[int] | None = None) -> str:
    partes = [f'Documento: {norma.identificacao} — {norma.ementa}.']
    if paginas:
        partes.append(
            f'Este arquivo é um RECORTE: contém só as páginas {descrever_paginas(paginas)} do documento '
            f'original, nessa ordem. Em "pagina", informe a posição da página NESTE arquivo '
            f'(1 a {len(paginas)}), não o número impresso no rodapé — e não cite números de página '
            f'em "observacao" nem em "descricao" (a numeração deste arquivo não é a do original). '
            f'Obrigações que dependam de trechos fora do recorte podem ser citadas pelo que aparece aqui.'
        )
    perfil = perfil_empresa()
    if perfil:
        partes.append(f'Perfil da empresa (use só para apontar dúvidas de aplicabilidade em "observacao"): {perfil}')
    if ja_cadastrados:
        lista = '\n'.join(f'- {r}' for r in ja_cadastrados[:80])
        partes.append(f'Já cadastrados para este documento (não repita):\n{lista}')
    partes.append('Liste as obrigações deste documento.')
    return '\n\n'.join(partes)


def extrair(norma, conteudo_pdf: bytes, ja_cadastrados: list[str], paginas: list[int] | None = None) -> dict:
    """Devolve {'resumo', 'itens', 'tokens_entrada', 'tokens_saida'} ou levanta FalhaExtracao.

    `paginas` (numeração do PDF original) restringe a leitura a essas páginas; as
    páginas citadas nas sugestões voltam convertidas para a numeração original.
    """
    if not conteudo_pdf.startswith(b'%PDF'):
        raise FalhaExtracao('O arquivo anexado não é um PDF.')
    if paginas:
        conteudo_pdf = recortar_pdf(conteudo_pdf, paginas)
    if len(conteudo_pdf) > LIMITE_PDF_BYTES:
        raise FalhaExtracao('O PDF passa de 20 MB. Informe só as páginas relevantes (ex.: as condicionantes) no campo de páginas.')

    cliente = _cliente()
    # Stream: documentos longos passam do tempo de uma resposta não-streaming.
    with cliente.messages.stream(
        model=modelo(),
        max_tokens=32000,
        system=SISTEMA,
        output_config={'effort': 'medium', 'format': {'type': 'json_schema', 'schema': ESQUEMA}},
        messages=[{
            'role': 'user',
            'content': [
                {
                    'type': 'document',
                    'source': {'type': 'base64', 'media_type': 'application/pdf',
                               'data': base64.standard_b64encode(conteudo_pdf).decode()},
                    'title': norma.identificacao,
                },
                {'type': 'text', 'text': _instrucao(norma, ja_cadastrados, paginas)},
            ],
        }],
    ) as stream:
        resposta = stream.get_final_message()

    if resposta.stop_reason == 'refusal':
        raise FalhaExtracao('O modelo recusou ler este documento. Tente de novo ou cadastre os requisitos à mão.')
    if resposta.stop_reason == 'max_tokens':
        raise FalhaExtracao('O documento gerou obrigações demais para uma leitura só. Separe em partes menores.')

    texto = next((b.text for b in resposta.content if b.type == 'text'), '')
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        logger.warning('Extração IA: resposta fora do formato (stop_reason=%s)', resposta.stop_reason)
        raise FalhaExtracao('A resposta da IA veio fora do formato esperado. Tente de novo.')

    return {
        'resumo': dados.get('resumo', ''),
        'itens': [_pagina_original(_normalizar(i), paginas)
                  for i in dados.get('itens', []) if (i.get('descricao') or '').strip()],
        'normas_tecnicas': [_pagina_original(n, paginas) for n in normas_tecnicas.da_ia(dados.get('normas_tecnicas', []))],
        'tokens_entrada': resposta.usage.input_tokens,
        'tokens_saida': resposta.usage.output_tokens,
    }


def _normalizar(item: dict) -> dict:
    prazo = (item.get('prazo_legal') or '').strip()
    if len(prazo) != 10 or prazo[4] != '-' or prazo[7] != '-':
        prazo = ''
    return {
        'referencia': (item.get('referencia') or '').strip()[:120],
        'descricao': item['descricao'].strip(),
        'tema': item.get('tema') if item.get('tema') in dict(TEMAS) else 'OUTRO',
        'periodicidade_meses': item.get('periodicidade_meses') if item.get('periodicidade_meses') in PERIODICIDADES else 12,
        'prazo_legal': prazo or None,
        'trecho': (item.get('trecho') or '').strip(),
        'pagina': item.get('pagina') or None,
        'observacao': (item.get('observacao') or '').strip(),
    }


def _pagina_original(item: dict, paginas: list[int] | None) -> dict:
    """Página do recorte → página do documento original; fora do recorte vira None."""
    if paginas and item.get('pagina'):
        p = item['pagina']
        item['pagina'] = paginas[p - 1] if isinstance(p, int) and 1 <= p <= len(paginas) else None
    return item


# ── Triagem de publicações dos diários oficiais (fase 3) ─────────────────
ESQUEMA_TRIAGEM = {
    'type': 'object',
    'properties': {
        'relevancia': {'type': 'string', 'enum': ['ALTA', 'MEDIA', 'BAIXA', 'NENHUMA'],
                       'description': 'ALTA: cria ou muda obrigação da empresa; MEDIA: pode afetar, precisa conferir; '
                                      'BAIXA: tema próximo, sem efeito provável; NENHUMA: não diz respeito à empresa.'},
        'motivo': {'type': 'string', 'description': 'Até 3 frases: o que a publicação faz e por que (não) afeta a empresa.'},
        'tema': {'type': 'string', 'enum': [t for t, _ in TEMAS]},
    },
    'required': ['relevancia', 'motivo', 'tema'],
    'additionalProperties': False,
}

SISTEMA_TRIAGEM = """Você é analista de conformidade legal de uma empresa brasileira e faz a triagem diária
de publicações de diários oficiais. Diga se a publicação cria, altera ou revoga obrigação que se aplica à
empresa descrita, usando só o texto recebido. Atos administrativos internos do órgão (pessoal, contratos,
cooperação entre órgãos, notificações dirigidas a outras empresas) têm relevância NENHUMA ou BAIXA.
Normas gerais de licenciamento, emissões, mineração, resíduos, recursos hídricos ou taxas ambientais que
alcancem a atividade da empresa têm relevância ALTA ou MEDIA. Responda em português."""


def triar_publicacao(pub) -> dict:
    """Relevância de uma publicação para a empresa: {'relevancia', 'motivo', 'tema'}."""
    perfil = perfil_empresa() or 'empresa industrial no RS'
    texto = (pub.texto or '')[:8000]
    pedido = (f'Empresa: {perfil}\n\n'
              f'Publicação ({pub.get_fonte_display()}, {pub.data_publicacao:%d/%m/%Y}):\n'
              f'Órgão: {pub.orgao}\nTipo: {pub.tipo}\nTítulo: {pub.titulo}\n\n{texto}')
    resposta = _cliente().messages.create(
        model=modelo(),
        max_tokens=4000,
        system=SISTEMA_TRIAGEM,
        output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': ESQUEMA_TRIAGEM}},
        messages=[{'role': 'user', 'content': pedido}],
    )
    if resposta.stop_reason == 'refusal':
        raise FalhaExtracao('O modelo recusou analisar esta publicação.')
    texto_resposta = next((b.text for b in resposta.content if b.type == 'text'), '')
    try:
        dados = json.loads(texto_resposta)
    except json.JSONDecodeError:
        raise FalhaExtracao('A resposta da IA veio fora do formato esperado.')
    tema = dados.get('tema') if dados.get('tema') in dict(TEMAS) else 'OUTRO'
    relevancia = dados.get('relevancia') if dados.get('relevancia') in ('ALTA', 'MEDIA', 'BAIXA', 'NENHUMA') else 'MEDIA'
    return {'relevancia': relevancia, 'motivo': (dados.get('motivo') or '').strip(), 'tema': tema}
