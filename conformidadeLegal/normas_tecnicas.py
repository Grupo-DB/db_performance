"""
Normas técnicas (ABNT NBR) citadas nos documentos que a IA lê.

Uma licença ou norma costuma mandar seguir NBRs ("conforme ABNT NBR 10004",
"ensaio pela NBR 9547"). Elas são guardadas na leitura (ExtracaoIA.normas_citadas)
para a equipe escolher quais viram palavra-chave das Novidades legais — aí o
monitor do DOU acusa qualquer ato que cite a NBR, de qualquer órgão (Inmetro,
ANM, MTE...).

Duas fontes, juntadas por número: o que a IA listou (com trecho e página) e o
que uma expressão regular acha no texto do PDF. A regex garante as citações
explícitas mesmo quando a IA deixa passar alguma; a IA cobre PDF escaneado,
em que o pypdf não tira texto.
"""
import io
import re

# "ABNT NBR 10004", "NBR 10.004/2004", "NBR-9547", "ABNT NBR ISO 14001:2015", "NBR ISO/IEC 17025", "NBR 15575-1".
# O número pode ter ponto de milhar; a parte ("-1") e o ano ficam de fora da chave.
RE_NBR = re.compile(
    r'\b(?:ABNT\s*)?NBR\s*[-–]?\s*'
    r'(?P<prefixo>(?:ISO|IEC)(?:\s*/\s*(?:ISO|IEC))?\s*)?'
    # Texto tirado de PDF às vezes separa o milhar com espaço ("10 .004").
    r'(?P<numero>\d{1,3}(?:\s?\.\s?\d{3})+|\d{3,6})'
    r'(?P<parte>-\d{1,2})?'
    r'(?:\s*[:/]\s*(?P<ano>(?:19|20)\d{2})\b)?',
    re.IGNORECASE,
)


def canonico(texto: str) -> dict | None:
    """Primeiro código de NBR no texto, padronizado: {'codigo', 'numero', 'prefixo', 'ano'}; None se não houver."""
    m = RE_NBR.search(texto or '')
    if not m:
        return None
    prefixo = re.sub(r'\s+', '', (m.group('prefixo') or '').upper())
    numero = re.sub(r'[\s.]', '', m.group('numero'))
    codigo = 'ABNT NBR ' + (f'{prefixo} ' if prefixo else '') + numero + (m.group('parte') or '')
    return {'codigo': codigo, 'numero': numero, 'prefixo': prefixo, 'ano': m.group('ano') or ''}


def chave(item: dict) -> str:
    """Igualdade entre citações: mesma família e número (a parte "-1" e o ano não separam)."""
    return f"{item.get('prefixo', '')}|{item['numero']}"


def rotulo_monitor(item: dict) -> str:
    """Nome da palavra-chave: o código sem a parte, que vale para todas as partes da norma."""
    return 'ABNT NBR ' + (f"{item['prefixo']} " if item.get('prefixo') else '') + item['numero']


def termos_monitor(item: dict) -> str:
    """
    Expressão do monitor (texto já sem acento e minúsculo). Aceita "nbr 10004",
    "nbr10004", "nbr-10.004", "abnt nbr 10004-2"; com ISO, também "iso 14001" sozinho
    (é como o DOU costuma citar). A borda de palavra vem do monitor.
    """
    n = item['numero']
    num = f'{n[:-3]}\\.?{n[-3:]}' if len(n) > 3 else n
    if item.get('prefixo'):
        familia = item['prefixo'].lower().replace('/', '[ /]*')
        return f're:(nbr[ -]?)?{familia}[ -]?{num}'
    return f're:nbr[ -]?{num}'


def textos_do_pdf(conteudo_pdf: bytes, paginas: list[int] | None = None) -> list[tuple[int, str]]:
    """(página, texto) de cada página — numeração do original. PDF escaneado volta texto vazio."""
    try:
        from pypdf import PdfReader
        leitor = PdfReader(io.BytesIO(conteudo_pdf))
        numeros = paginas or list(range(1, len(leitor.pages) + 1))
        return [(p, leitor.pages[p - 1].extract_text() or '') for p in numeros if 1 <= p <= len(leitor.pages)]
    except Exception:  # noqa: BLE001 — sem texto, fica só o que a IA achar
        return []


def do_texto(paginas_texto: list[tuple[int, str]]) -> list[dict]:
    """Todas as NBRs citadas no texto, uma por número, com a primeira página e um trecho em volta."""
    achadas: dict[str, dict] = {}
    for pagina, texto in paginas_texto:
        corrido = re.sub(r'\s+', ' ', texto)
        for m in RE_NBR.finditer(corrido):
            item = canonico(m.group(0))
            if not item or chave(item) in achadas:
                continue
            ini, fim = max(0, m.start() - 90), min(len(corrido), m.end() + 90)
            item.update(titulo='', pagina=pagina, origem='texto',
                        trecho=('…' if ini else '') + corrido[ini:fim].strip() + ('…' if fim < len(corrido) else ''))
            achadas[chave(item)] = item
    return list(achadas.values())


def da_ia(itens: list[dict]) -> list[dict]:
    """Normaliza o que a IA listou; descarta o que não tem código de NBR reconhecível."""
    saida: dict[str, dict] = {}
    for bruto in itens or []:
        item = canonico(bruto.get('codigo', ''))
        if not item or chave(item) in saida:
            continue
        item.update(titulo=(bruto.get('titulo') or '').strip()[:300], trecho=(bruto.get('trecho') or '').strip()[:600],
                    pagina=bruto.get('pagina') if isinstance(bruto.get('pagina'), int) and bruto['pagina'] > 0 else None,
                    origem='ia')
        saida[chave(item)] = item
    return list(saida.values())


def juntar(ia_itens: list[dict], texto_itens: list[dict]) -> list[dict]:
    """IA primeiro (tem título); a regex completa página/trecho e acrescenta o que a IA deixou passar."""
    por_chave = {chave(i): dict(i) for i in ia_itens}
    for t in texto_itens:
        atual = por_chave.get(chave(t))
        if atual is None:
            por_chave[chave(t)] = dict(t)
        else:
            atual['pagina'] = atual.get('pagina') or t.get('pagina')
            atual['trecho'] = atual.get('trecho') or t.get('trecho')
            atual['ano'] = atual.get('ano') or t.get('ano')
            atual['origem'] = 'ia+texto'
    return sorted(por_chave.values(), key=lambda i: (i.get('prefixo') or '', int(i['numero'])))
