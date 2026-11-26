"""
IA nas Peças da Oficina (26/11/2026) — o Claude, pelo mesmo recurso do Microsoft Foundry da Conformidade Legal
(variáveis CONFORMIDADE_IA_*; ver conformidadeLegal/ia.py).

Três usos, todos com conferência humana antes de valer:

1. `sugerir_itens_sga`: a peça do fabricante não casou com nenhum item do SGA pelo código. Uma busca por
   palavras escolhe até 25 itens candidatos e a IA aponta os mais prováveis. O comprador confirma e a confirmação
   vira de-para (DeParaPeca), então a IA só é consultada uma vez por peça.
2. `ler_catalogo`: o leitor do layout (pecas_catalogo.py) não achou páginas de peças — outro fabricante ou PDF
   escaneado. A IA lê as páginas como imagem e devolve a mesma estrutura do leitor. O catálogo entra "Em revisão"
   e só vale depois que alguém confere e publica.
3. `identificar`: foto da peça (ou da plaqueta) e/ou descrição livre → códigos lidos, palavras-chave e os
   conjuntos prováveis do catálogo do equipamento. A busca no catálogo continua sendo a do Manager.
"""
import base64
import json
import logging
import re
import subprocess
import tempfile
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)

PAGINAS_POR_PEDIDO = 6
DPI_LEITURA = 110
MAX_PAGINAS_IA = 600


class FalhaIA(Exception):
    pass


def configurada() -> bool:
    try:
        from conformidadeLegal import ia
    except Exception:  # noqa: BLE001 — app ausente: sem IA, o resto funciona
        return False
    return ia.configurada()


def _cliente_e_modelo():
    from conformidadeLegal import ia
    if not ia.configurada():
        raise FalhaIA('A IA não está configurada no servidor.')
    return ia._cliente(), ia.modelo()


def _json(resposta) -> dict:
    if resposta.stop_reason == 'refusal':
        raise FalhaIA('A IA recusou este pedido.')
    if resposta.stop_reason == 'max_tokens':
        raise FalhaIA('A resposta da IA ficou grande demais.')
    texto = next((b.text for b in resposta.content if b.type == 'text'), '')
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        logger.warning('peças IA: resposta fora do formato (stop_reason=%s)', resposta.stop_reason)
        raise FalhaIA('A resposta da IA veio fora do formato esperado.')


def _imagem(dados: bytes, mime: str) -> dict:
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': mime,
                                        'data': base64.standard_b64encode(dados).decode()}}


# ---------------------------------------------------------------------------------------------------------
# 1. Sugestão de item do SGA
# ---------------------------------------------------------------------------------------------------------

_ESQUEMA_SUGESTAO = {
    'type': 'object',
    'properties': {
        'sugestoes': {
            'type': 'array',
            'description': 'Até 3 itens da lista, do mais para o menos provável. Vazio se nenhum servir.',
            'items': {
                'type': 'object',
                'properties': {
                    'item_sga': {'type': 'integer', 'description': 'Código do item, exatamente como na lista.'},
                    'confianca': {'type': 'string', 'enum': ['alta', 'media', 'baixa']},
                    'motivo': {'type': 'string', 'description': 'Uma frase curta: o que bate e o que não bate.'},
                },
                'required': ['item_sga', 'confianca', 'motivo'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['sugestoes'],
    'additionalProperties': False,
}

_SISTEMA_SUGESTAO = """Você ajuda o almoxarifado de uma mineradora a achar, no cadastro de itens do ERP, a peça
que o catálogo do fabricante do equipamento descreve. Recebe a peça (código e descrição do fabricante, às vezes o
conjunto onde ela fica) e uma lista de itens do ERP com código e nome.

Regras:
- Escolha só itens da lista. Nunca invente código.
- Um item só serve se for a MESMA peça: tipo (filtro, junta, rolamento...), aplicação e medida compatíveis.
  "FILTRO AR PRIMÁRIO" e "FILTRO DE ÓLEO" são peças diferentes.
- O código do fabricante escrito no nome do item é evidência forte. Medidas diferentes descartam o item.
- Na dúvida, devolva menos itens ou nenhum: uma sugestão errada vira compra errada.
- Escreva "motivo" em português, numa frase."""


def sugerir_itens_sga(peca: dict, candidatos: list[dict]) -> list[dict]:
    """peca: {codigo, descricao, conjunto, equipamento}; candidatos: [{codigo, nome}] → [{item_sga, confianca, motivo}]."""
    if not candidatos:
        return []
    cliente, modelo = _cliente_e_modelo()
    lista = '\n'.join(f'{c["codigo"]} — {c["nome"]}' for c in candidatos)
    pedido = (f'Peça do catálogo do fabricante:\n'
              f'- código: {peca.get("codigo") or "(sem código)"}\n'
              f'- descrição: {peca.get("descricao") or ""}\n'
              f'- conjunto: {peca.get("conjunto") or "(não informado)"}\n'
              f'- equipamento: {peca.get("equipamento") or "(não informado)"}\n\n'
              f'Itens do ERP (código — nome):\n{lista}')
    resposta = cliente.messages.create(
        model=modelo, max_tokens=4000, system=_SISTEMA_SUGESTAO,
        output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': _ESQUEMA_SUGESTAO}},
        messages=[{'role': 'user', 'content': pedido}],
    )
    validos = {int(c['codigo']) for c in candidatos}
    out = []
    for s in _json(resposta).get('sugestoes', []):
        if isinstance(s.get('item_sga'), int) and s['item_sga'] in validos:
            out.append({'item_sga': s['item_sga'], 'confianca': s.get('confianca') or 'baixa',
                        'motivo': (s.get('motivo') or '').strip()[:300]})
    return out[:3]


# ---------------------------------------------------------------------------------------------------------
# 2. Leitura de catálogo com layout desconhecido (ou escaneado)
# ---------------------------------------------------------------------------------------------------------

_ESQUEMA_PAGINAS = {
    'type': 'object',
    'properties': {
        'modelo': {'type': 'string', 'description': 'Modelo do equipamento escrito nas páginas; vazio se não aparecer.'},
        'paginas': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'pagina': {'type': 'integer', 'description': 'Número da imagem, como no rótulo "Página N".'},
                    'tem_pecas': {'type': 'boolean', 'description': 'A página tem uma tabela/lista de peças.'},
                    'conjunto_codigo': {'type': 'string', 'description': 'Código do conjunto/grupo da página como impresso; vazio se não houver.'},
                    'conjunto_nome': {'type': 'string', 'description': 'Título do conjunto/grupo da página.'},
                    'desenho_base': {'type': 'number', 'description': 'Onde termina o desenho, em fração da altura da página (0 = topo, 1 = rodapé). 0 se não houver desenho.'},
                    'pecas': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'fig': {'type': 'string', 'description': 'Número da peça no desenho (posição/item).'},
                                'codigo': {'type': 'string', 'description': 'Código/part number do fabricante, exatamente como impresso.'},
                                'qtd': {'type': 'string'},
                                'descricao': {'type': 'string'},
                                'nota': {'type': 'string', 'description': 'Observação da linha; vazio se não houver.'},
                                'serie_inicio': {'type': 'integer', 'description': 'Série/número de fabricação inicial em que a linha vale; 0 se não houver.'},
                                'serie_fim': {'type': 'integer', 'description': 'Série final; 0 se não houver.'},
                            },
                            'required': ['fig', 'codigo', 'qtd', 'descricao', 'nota', 'serie_inicio', 'serie_fim'],
                            'additionalProperties': False,
                        },
                    },
                },
                'required': ['pagina', 'tem_pecas', 'conjunto_codigo', 'conjunto_nome', 'desenho_base', 'pecas'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['modelo', 'paginas'],
    'additionalProperties': False,
}

_SISTEMA_PAGINAS = """Você transcreve catálogos de peças de equipamentos pesados (caminhões, carregadeiras,
britadores). Cada imagem é uma página. Páginas de peças costumam ter um desenho explodido com números e uma
tabela com posição, código (part number), quantidade e descrição; às vezes faixas de número de série.

Regras:
- Transcreva, não interprete: códigos e números EXATAMENTE como impressos (sem corrigir, sem completar).
- Uma linha da tabela = um item em "pecas". Linha que só continua a descrição da anterior: junte na anterior.
- Páginas sem tabela de peças (capa, índice, instruções): tem_pecas = false e "pecas" vazio.
- Se não conseguir ler um código com segurança, deixe "codigo" vazio em vez de chutar.
- Devolva um item em "paginas" para cada imagem recebida."""


def _renderizar_paginas(caminho_pdf, primeira: int, ultima: int, pasta: Path) -> list[Path]:
    subprocess.run(['pdftoppm', '-f', str(primeira), '-l', str(ultima), '-r', str(DPI_LEITURA), '-jpeg',
                    '-jpegopt', 'quality=80', str(caminho_pdf), str(pasta / 'p')],
                   check=True, capture_output=True, timeout=600)
    return sorted(pasta.glob('p-*.jpg'), key=lambda p: int(re.findall(r'(\d+)\.jpg$', p.name)[0]))


def _ler_lote(cliente, modelo, imagens: list[tuple[int, bytes]]) -> dict:
    conteudo = []
    for n, dados in imagens:
        conteudo.append({'type': 'text', 'text': f'Página {n}'})
        conteudo.append(_imagem(dados, 'image/jpeg'))
    conteudo.append({'type': 'text', 'text': 'Transcreva estas páginas.'})
    with cliente.messages.stream(
        model=modelo, max_tokens=32000, system=_SISTEMA_PAGINAS,
        output_config={'effort': 'medium', 'format': {'type': 'json_schema', 'schema': _ESQUEMA_PAGINAS}},
        messages=[{'role': 'user', 'content': conteudo}],
    ) as stream:
        return _json(stream.get_final_message())


def _faixa(ini, fim) -> list[list[int]]:
    ini = ini if isinstance(ini, int) and ini > 0 else 0
    fim = fim if isinstance(fim, int) and fim > 0 else 0
    if not ini and not fim:
        return []
    return [[ini or fim, fim or 999999]]


def montar_de_paginas(lidas: list[dict], tamanhos: dict[int, tuple[float, float]], modelo: str = '') -> dict:
    """Junta as páginas devolvidas pela IA no formato do leitor (pecas_catalogo.montar_catalogo)."""
    from .pecas_catalogo import _VER, normalizar_codigo_conjunto
    conjuntos: OrderedDict[str, dict] = OrderedDict()
    anterior = None
    for pg in sorted(lidas, key=lambda p: p.get('pagina') or 0):
        n = pg.get('pagina')
        if not isinstance(n, int) or not pg.get('tem_pecas') or not pg.get('pecas'):
            anterior = None
            continue
        largura, altura = tamanhos.get(n, (612.0, 792.0))
        cod = (normalizar_codigo_conjunto((pg.get('conjunto_codigo') or '').strip()) or '')[:30]
        nome = (pg.get('conjunto_nome') or '').strip()
        if not cod:
            # Sem código impresso: continua o conjunto anterior se o título é o mesmo, senão cria pelo nº da página.
            cod = anterior if anterior and conjuntos[anterior]['nome'] == nome else f'P{n:03d}'
        pecas = []
        for p in pg['pecas']:
            desc = (p.get('descricao') or '').strip()
            if not desc and not (p.get('codigo') or '').strip():
                continue
            nota = (p.get('nota') or '').strip()
            ver = _VER.search(nota.upper())
            pecas.append({'fig': (p.get('fig') or '').strip()[:10], 'codigo': (p.get('codigo') or '').strip()[:30],
                          'qtd': (p.get('qtd') or '').strip()[:10], 'descricao': desc[:300] or '-', 'nota': nota[:200],
                          'ver': f'{ver.group(1)} {ver.group(2)}' if ver else '',
                          'faixas': _faixa(p.get('serie_inicio'), p.get('serie_fim'))})
        base = pg.get('desenho_base') or 0
        y_tabela = altura * base if 0.15 <= base <= 0.98 else 0
        cj = conjuntos.get(cod)
        if cj is None:
            cj = conjuntos[cod] = {'nome': (nome or cod)[:200], 'pagina': n, 'paginas': [n], 'y_tabela': y_tabela,
                                   'largura': largura, 'altura': altura, 'pecas': [], '_idx': {}}
        elif n not in cj['paginas']:
            cj['paginas'].append(n)
        for p in pecas:
            # A mesma peça repetida por faixa de série vira uma linha só, como no leitor do layout.
            chave = (p['fig'], p['codigo'], p['qtd'], p['descricao'], p['nota'])
            igual = cj['_idx'].get(chave)
            if igual is None:
                cj['_idx'][chave] = p
                cj['pecas'].append(p)
            else:
                for f in p['faixas']:
                    if f not in igual['faixas']:
                        igual['faixas'].append(f)
        anterior = cod
    for cj in conjuntos.values():
        cj.pop('_idx', None)
    return {'modelo': modelo, 'conjuntos': conjuntos}


def ler_catalogo(caminho_pdf, paginas_pdf: list[dict], progresso=None) -> dict:
    """Lê o PDF inteiro em lotes de imagens. `paginas_pdf` = pecas_catalogo.ler_pdf (para o tamanho da página)."""
    total = len(paginas_pdf)
    if not total:
        raise FalhaIA('O PDF não tem páginas.')
    if total > MAX_PAGINAS_IA:
        raise FalhaIA(f'O PDF tem {total} páginas; a leitura pela IA aceita até {MAX_PAGINAS_IA}.')
    cliente, modelo = _cliente_e_modelo()
    tamanhos = {i + 1: (p.get('largura') or 612.0, p.get('altura') or 792.0) for i, p in enumerate(paginas_pdf)}
    lidas, nome_modelo = [], ''
    for ini in range(1, total + 1, PAGINAS_POR_PEDIDO):
        fim = min(total, ini + PAGINAS_POR_PEDIDO - 1)
        with tempfile.TemporaryDirectory() as tmp:
            arquivos = _renderizar_paginas(caminho_pdf, ini, fim, Path(tmp))
            imagens = [(ini + i, a.read_bytes()) for i, a in enumerate(arquivos)]
        dados = _ler_lote(cliente, modelo, imagens)
        nome_modelo = nome_modelo or (dados.get('modelo') or '').strip()
        lidas.extend(dados.get('paginas', []))
        if progresso:
            progresso(fim, total)
    return montar_de_paginas(lidas, tamanhos, nome_modelo[:120])


# ---------------------------------------------------------------------------------------------------------
# 3. Identificar peça por foto/descrição
# ---------------------------------------------------------------------------------------------------------

_ESQUEMA_IDENTIFICAR = {
    'type': 'object',
    'properties': {
        'descricao': {'type': 'string', 'description': 'O que parece ser a peça, em uma frase.'},
        'codigos_lidos': {'type': 'array', 'items': {'type': 'string'},
                          'description': 'Códigos/part numbers legíveis na foto ou citados no texto, como escritos.'},
        'palavras_chave': {'type': 'array', 'items': {'type': 'string'},
                           'description': 'Até 4 palavras para buscar na descrição das peças do catálogo (ex.: "FILTRO", "COXIM").'},
        'conjuntos': {
            'type': 'array',
            'description': 'Até 5 conjuntos da lista onde a peça provavelmente está, do mais provável para o menos.',
            'items': {
                'type': 'object',
                'properties': {
                    'codigo': {'type': 'string', 'description': 'Código do conjunto exatamente como na lista.'},
                    'motivo': {'type': 'string'},
                },
                'required': ['codigo', 'motivo'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['descricao', 'codigos_lidos', 'palavras_chave', 'conjuntos'],
    'additionalProperties': False,
}

_SISTEMA_IDENTIFICAR = """Você ajuda o mecânico de uma oficina de mineração a achar uma peça no catálogo do
fabricante do equipamento. Recebe uma foto da peça (às vezes da plaqueta ou da embalagem) e/ou uma descrição em
linguagem de oficina, e a lista de conjuntos do catálogo (código — nome).

Regras:
- Copie códigos legíveis exatamente; não complete dígitos que não dá para ler.
- Palavras-chave em maiúsculas, como aparecem em catálogo ("COXIM", "MANGUEIRA", "JUNTA"), sem acento.
- Conjuntos: só códigos da lista. Se não der para saber, devolva a lista vazia.
- Responda em português."""


def identificar(foto: bytes | None, mime: str, texto: str, conjuntos: list[tuple[str, str]], equipamento: str = '') -> dict:
    cliente, modelo = _cliente_e_modelo()
    lista = '\n'.join(f'{c} — {n}' for c, n in conjuntos)
    conteudo = []
    if foto:
        conteudo.append(_imagem(foto, mime))
    conteudo.append({'type': 'text', 'text': (
        f'Equipamento: {equipamento or "(não informado)"}\n'
        f'Descrição do mecânico: {texto or "(só a foto)"}\n\n'
        f'Conjuntos do catálogo:\n{lista}')})
    resposta = cliente.messages.create(
        model=modelo, max_tokens=4000, system=_SISTEMA_IDENTIFICAR,
        output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': _ESQUEMA_IDENTIFICAR}},
        messages=[{'role': 'user', 'content': conteudo}],
    )
    dados = _json(resposta)
    validos = {c for c, _ in conjuntos}
    return {
        'descricao': (dados.get('descricao') or '').strip()[:300],
        'codigos_lidos': [str(c).strip()[:30] for c in dados.get('codigos_lidos', []) if str(c).strip()][:6],
        'palavras_chave': [str(p).strip().upper()[:30] for p in dados.get('palavras_chave', []) if str(p).strip()][:4],
        'conjuntos': [{'codigo': c['codigo'], 'motivo': (c.get('motivo') or '')[:200]}
                      for c in dados.get('conjuntos', []) if c.get('codigo') in validos][:5],
    }
