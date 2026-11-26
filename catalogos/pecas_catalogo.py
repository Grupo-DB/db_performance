"""
Catálogo de peças do fabricante em PDF → conjuntos e peças no Manager (26/11/2026).

Primeiro catálogo: "RK 430M DC13" da Randon (342 páginas, edição 15/09/2014). Cada página de peças traz:
- no topo, o modelo ("RK 430M DC13"), o nome do conjunto ("CAPO DO MOTOR - COMPONENTES") e o código do
  conjunto à direita ("2A300 00.0");
- o desenho explodido (imagem; os números do desenho NÃO são texto, então não há como fazer o desenho
  clicável — o chefe da oficina lê o número no desenho e acha a linha na tabela);
- a tabela Fig. | Código | Qtd | Descrição | Nota | Início | Fim. Início/Fim é a faixa de NÚMERO DE SÉRIE
  de fabricação em que a linha vale (a mesma peça aparece repetida, uma linha por faixa). "Nota" às vezes é
  "VER 3A001 13.0" = a peça é um subconjunto com página própria.

As páginas de índice (alfabético e numérico) não têm o cabeçalho "Fig." e são puladas.

⚠️ Dependência de sistema: `pdftotext` e `pdftoppm` (poppler-utils), como na folha ponto do RH
(recrutamento/folha_ponto.py explica por que o pdfminer não serve).
"""
import re
import shutil
import subprocess
from collections import OrderedDict

DPI_DESENHO = 150

_PAGE_XML = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)
_WORD_XML = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')
_COD_CONJUNTO = re.compile(r'^\d[A-Z]\d{3,4}[ .]?\d{2}\.\d$')
_FIG = re.compile(r'^\d{1,3}(\.\d{1,2})?$')
_NUM = re.compile(r'^\d{1,6}$')
_VER = re.compile(r'\bVER\s+(\d[A-Z]\d{3,4})[ .]?(\d{2}\.\d)\b')

COLUNAS = ('fig', 'codigo', 'qtd', 'descricao', 'nota', 'inicio', 'fim')
_ROTULOS = {'Fig.': 'fig', 'Código': 'codigo', 'Qtd': 'qtd', 'Descrição': 'descricao', 'Nota': 'nota',
            'Início': 'inicio', 'Fim': 'fim'}


class PopplerAusente(RuntimeError):
    pass


def tem_poppler() -> bool:
    return bool(shutil.which('pdftotext') and shutil.which('pdftoppm'))


def _exigir_poppler():
    if not tem_poppler():
        raise PopplerAusente('A importação do catálogo precisa do pdftotext/pdftoppm (pacote poppler-utils).')


def corrigir_texto(s: str) -> str:
    """O PDF da Randon perdeu o "Ã" (PRESS?O, TRANSMISS?O, PEGA-M?O); os outros acentos já vinham sem."""
    s = re.sub(r'(?<=[A-Z])\?(?=[A-Z]|\b)', 'Ã', s or '')
    return re.sub(r'\s+', ' ', s).strip()


def normalizar_codigo_conjunto(s: str) -> str:
    """'1A100.00.2' (erro de digitação do catálogo) e '2A300 00.0' viram '1A100 00.2' / '2A300 00.0'."""
    s = (s or '').strip()
    m = re.match(r'^(\d[A-Z]\d{3,4})[ .]?(\d{2}\.\d)$', s)
    return f'{m.group(1)} {m.group(2)}' if m else s


# ---------------------------------------------------------------------------------------------------------
# Leitura das palavras com posição
# ---------------------------------------------------------------------------------------------------------

def ler_paginas_xml(xml: str) -> list[dict]:
    """Saída do `pdftotext -bbox` → [{largura, altura, palavras: [{x, x2, y, y2, t}]}] (y cresce para baixo)."""
    paginas = []
    for larg, alt, corpo in _PAGE_XML.findall(xml):
        ws = []
        for x, y, x2, y2, t in _WORD_XML.findall(corpo):
            t = (t.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                  .replace('&quot;', '"').replace('&apos;', "'").strip())
            if t:
                ws.append({'x': float(x), 'y': float(y), 'x2': float(x2), 'y2': float(y2), 't': t})
        paginas.append({'largura': float(larg), 'altura': float(alt), 'palavras': ws})
    return paginas


def ler_pdf(caminho) -> list[dict]:
    _exigir_poppler()
    xml = subprocess.run(['pdftotext', '-bbox', '-enc', 'UTF-8', str(caminho), '-'],
                         capture_output=True, text=True, encoding='utf-8', check=True).stdout
    return ler_paginas_xml(xml)


def _linhas(palavras: list[dict], tol: float = 3.0) -> list[list[dict]]:
    """Agrupa palavras na mesma altura (tolerância em pontos), cada linha ordenada da esquerda para a direita."""
    linhas: list[list[dict]] = []
    for w in sorted(palavras, key=lambda w: (w['y'], w['x'])):
        if linhas and abs(linhas[-1][0]['y'] - w['y']) <= tol:
            linhas[-1].append(w)
        else:
            linhas.append([w])
    return [sorted(l, key=lambda w: w['x']) for l in linhas]


# ---------------------------------------------------------------------------------------------------------
# Uma página
# ---------------------------------------------------------------------------------------------------------

def ler_pagina(pagina: dict) -> dict | None:
    """Página de peças → {modelo, conjunto, nome, topo_tabela, linhas: [...]}; None se não for página de peças."""
    linhas = _linhas(pagina['palavras'])
    cab = None
    for i, l in enumerate(linhas):
        textos = [w['t'] for w in l]
        if 'Fig.' in textos and 'Código' in textos and 'Qtd' in textos:
            cab = i
            break
    if cab is None:
        return None
    col_x = {}
    for w in linhas[cab]:
        if w['t'] in _ROTULOS:
            col_x[_ROTULOS[w['t']]] = w['x']
    if not {'fig', 'codigo', 'qtd', 'descricao'} <= col_x.keys():
        return None
    y_cab = linhas[cab][0]['y']

    # Cabeçalho do conjunto (acima do desenho)
    topo = [w for w in pagina['palavras'] if w['y'] < 70]
    direita = [w for w in topo if w['x'] > pagina['largura'] * 0.7]
    codigo = normalizar_codigo_conjunto(' '.join(w['t'] for w in sorted(direita, key=lambda w: (round(w['y']), w['x']))))
    if not _COD_CONJUNTO.match(codigo):
        return None
    esquerda = _linhas([w for w in topo if w['x'] <= pagina['largura'] * 0.7])
    modelo = ' '.join(w['t'] for w in esquerda[0]) if esquerda else ''
    nome = ' '.join(' '.join(w['t'] for w in l) for l in esquerda[1:])
    # Logotipo do fabricante à esquerda do modelo (texto "RANDON VEÍCULOS" em alguns PDFs) não entra.
    x_modelo = min((w['x'] for w in esquerda[0]), default=0) if esquerda else 0

    # Fim da tabela = rodapé "Catálogo de Peças ..."
    y_fim = pagina['altura']
    for l in linhas[cab + 1:]:
        if l[0]['t'].startswith('Catálogo') or any(w['t'].startswith('Catálogo') for w in l):
            y_fim = l[0]['y']
            break

    ordem = sorted(col_x.items(), key=lambda kv: kv[1])

    def coluna(w):
        nomecol = ordem[0][0]
        for c, x in ordem:
            if w['x'] + 3 >= x:
                nomecol = c
        return nomecol

    registros = []
    for l in linhas[cab + 1:]:
        if l[0]['y'] >= y_fim:
            break
        cel = {c: [] for c in COLUNAS}
        for w in l:
            cel[coluna(w)].append(w['t'])
        valores = {c: ' '.join(v) for c, v in cel.items()}
        if valores['fig'] and _FIG.match(valores['fig']):
            registros.append(valores)
        elif registros:  # continuação da descrição/nota na linha de baixo
            for c in ('descricao', 'nota'):
                if valores[c]:
                    registros[-1][c] = (registros[-1][c] + ' ' + valores[c]).strip()
    return {
        'modelo': corrigir_texto(modelo),
        'conjunto': codigo,
        'nome': corrigir_texto(nome),
        'x_modelo': x_modelo,
        'y_tabela': y_cab,
        'linhas': registros,
    }


def _faixa(valores: dict):
    a, b = valores.get('inicio', ''), valores.get('fim', '')
    if _NUM.match(a or '') and _NUM.match(b or ''):
        return [int(a), int(b)]
    return None


def montar_catalogo(paginas: list[dict]) -> dict:
    """Todas as páginas → {modelo, conjuntos: OrderedDict(codigo → {nome, pagina, y_tabela, largura, altura,
    pecas: [{fig, codigo, qtd, descricao, nota, ver, faixas}]})}.

    A mesma peça repetida por faixa de série vira UMA linha com várias faixas (na tabela o RK 430M tem quase
    todas as linhas em dobro: 233–233 e 269–301).
    """
    conjuntos: OrderedDict[str, dict] = OrderedDict()
    modelos: dict[str, int] = {}
    for n, pag in enumerate(paginas, start=1):
        lida = ler_pagina(pag)
        if not lida:
            continue
        modelos[lida['modelo']] = modelos.get(lida['modelo'], 0) + 1
        cj = conjuntos.get(lida['conjunto'])
        if cj is None:
            cj = conjuntos[lida['conjunto']] = {
                'nome': lida['nome'], 'pagina': n, 'paginas': [n], 'y_tabela': lida['y_tabela'],
                'largura': pag['largura'], 'altura': pag['altura'], '_idx': OrderedDict(),
            }
        elif n not in cj['paginas']:
            cj['paginas'].append(n)
        for r in lida['linhas']:
            codigo = r['codigo'].replace(' ', '')
            descricao = corrigir_texto(r['descricao'])
            nota = corrigir_texto(r['nota'])
            chave = (r['fig'], codigo, r['qtd'], descricao, nota)
            peca = cj['_idx'].get(chave)
            if peca is None:
                ver = _VER.search(nota)
                peca = cj['_idx'][chave] = {
                    'fig': r['fig'], 'codigo': codigo, 'qtd': r['qtd'], 'descricao': descricao, 'nota': nota,
                    'ver': f'{ver.group(1)} {ver.group(2)}' if ver else '', 'faixas': [],
                }
            f = _faixa(r)
            if f and f not in peca['faixas']:
                peca['faixas'].append(f)
    for cj in conjuntos.values():
        cj['pecas'] = list(cj.pop('_idx').values())
    modelo = max(modelos, key=modelos.get) if modelos else ''
    return {'modelo': modelo, 'conjuntos': conjuntos}


def vale_para_serie(faixas: list, serie: int | None) -> bool:
    """Sem série informada (ou peça sem faixa) vale; com série, só se cair em alguma faixa."""
    if serie is None or not faixas:
        return True
    return any(a <= serie <= b for a, b in faixas)


def renderizar_desenho(caminho_pdf, pagina: int, largura_pt: float, y_tabela_pt: float, destino) -> None:
    """Recorta o desenho (do topo da página até o cabeçalho da tabela) em JPEG a DPI_DESENHO."""
    _exigir_poppler()
    escala = DPI_DESENHO / 72.0
    y0 = int(66 * escala)  # abaixo do logotipo e do título
    altura = max(int((y_tabela_pt - 4) * escala) - y0, 50)
    base = str(destino)
    if base.lower().endswith('.jpg'):
        base = base[:-4]
    subprocess.run(['pdftoppm', '-f', str(pagina), '-l', str(pagina), '-r', str(DPI_DESENHO), '-jpeg',
                    '-jpegopt', 'quality=82', '-singlefile', '-x', '0', '-y', str(y0),
                    '-W', str(int(largura_pt * escala)), '-H', str(altura), str(caminho_pdf), base],
                   check=True, capture_output=True)
