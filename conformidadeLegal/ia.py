"""
Leitura de normas/licenças em PDF pelo Claude, hospedado no Microsoft Foundry.

A IA nunca é a fonte da obrigação: ela lê o documento que a equipe anexou e
devolve sugestões, cada uma com o trecho literal e a página de onde saiu. Quem
aprova confere o trecho na tela de revisão antes de virar requisito.

Configuração (variáveis de ambiente, repetidas no settings.py da VM — o
settings não é versionado):
    CONFORMIDADE_IA_FOUNDRY_RESOURCE  nome do recurso (o <nome> de
                                      https://<nome>.services.ai.azure.com)
    CONFORMIDADE_IA_FOUNDRY_KEY       chave do recurso
    CONFORMIDADE_IA_MODELO            nome da implantação do modelo (padrão: claude-opus-5-5)
    CONFORMIDADE_IA_PERFIL_EMPRESA    opcional: atividades/unidades, para a IA
                                      marcar o que parece não se aplicar
"""
import base64
import json
import logging

from django.conf import settings

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
    },
    'required': ['resumo', 'itens'],
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
- Escreva a descrição em português claro, começando por um verbo no infinitivo."""


class IANaoConfigurada(Exception):
    pass


class FalhaExtracao(Exception):
    pass


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


def _instrucao(norma, ja_cadastrados: list[str]) -> str:
    partes = [f'Documento: {norma.identificacao} — {norma.ementa}.']
    perfil = getattr(settings, 'CONFORMIDADE_IA_PERFIL_EMPRESA', '')
    if perfil:
        partes.append(f'Perfil da empresa (use só para apontar dúvidas de aplicabilidade em "observacao"): {perfil}')
    if ja_cadastrados:
        lista = '\n'.join(f'- {r}' for r in ja_cadastrados[:80])
        partes.append(f'Já cadastrados para este documento (não repita):\n{lista}')
    partes.append('Liste as obrigações deste documento.')
    return '\n\n'.join(partes)


def extrair(norma, conteudo_pdf: bytes, ja_cadastrados: list[str]) -> dict:
    """Devolve {'resumo', 'itens', 'tokens_entrada', 'tokens_saida'} ou levanta FalhaExtracao."""
    if len(conteudo_pdf) > LIMITE_PDF_BYTES:
        raise FalhaExtracao('O PDF passa de 20 MB. Separe as páginas relevantes (ex.: só as condicionantes) e anexe de novo.')
    if not conteudo_pdf.startswith(b'%PDF'):
        raise FalhaExtracao('O arquivo anexado não é um PDF.')

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
                {'type': 'text', 'text': _instrucao(norma, ja_cadastrados)},
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
        'itens': [_normalizar(i) for i in dados.get('itens', []) if (i.get('descricao') or '').strip()],
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
