"""
Números do desenho explodido por OCR (26/11/2026) — para o desenho ficar clicável.

No PDF do fabricante o desenho é imagem: o "4" apontando para o para-lama não existe como texto. O Tesseract
lê a imagem que a importação já recorta (pecas_catalogo.renderizar_desenho) e devolve cada número com a caixa
onde está. Só ficam os números que existem na coluna Fig. daquele conjunto, o que descarta quase todo ruído
(cotas, traços lidos como "1").

Saída: [{"fig": "4", "x": 0.12, "y": 0.30, "w": 0.02, "h": 0.03}] — x/y/w/h em fração da imagem, para a tela
posicionar por porcentagem em qualquer tamanho de desenho. "fig" é o número inteiro: "01" e "01.1" do catálogo
casam com o "1" do desenho.

⚠️ Dependência de sistema: `tesseract` (apt install tesseract-ocr). Sem ele a importação segue sem marcadores.
"""
import logging
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)

CONFIANCA_MIN = 45


def tem_tesseract() -> bool:
    return shutil.which('tesseract') is not None


def fig_inteira(fig: str) -> str:
    """'01' → '1'; '01.1' → '1'; '13A' → '13'; sem número → ''."""
    m = re.match(r'\s*0*(\d+)', fig or '')
    return (m.group(1) or '0') if m else ''


def ler_tsv(tsv: str, figs: set[str]) -> list[dict]:
    """Interpreta a saída TSV do Tesseract. A linha de nível 1 traz o tamanho da imagem."""
    largura = altura = 0
    achados = []
    vistos = set()
    for i, linha in enumerate(tsv.splitlines()):
        partes = linha.split('\t')
        if i == 0 or len(partes) < 12:
            continue
        try:
            nivel, esq, topo, larg, alt = int(partes[0]), int(partes[6]), int(partes[7]), int(partes[8]), int(partes[9])
            conf = float(partes[10])
        except ValueError:
            continue
        if nivel == 1:
            largura, altura = larg, alt
            continue
        texto = partes[11].strip()
        if nivel != 5 or conf < CONFIANCA_MIN or not re.fullmatch(r'\d{1,3}', texto):
            continue
        fig = fig_inteira(texto)
        if fig not in figs or not largura or not altura:
            continue
        chave = (fig, esq // 8, topo // 8)  # a mesma leitura repetida pelo Tesseract
        if chave in vistos:
            continue
        vistos.add(chave)
        achados.append({'fig': fig, 'x': round(esq / largura, 4), 'y': round(topo / altura, 4),
                        'w': round(larg / largura, 4), 'h': round(alt / altura, 4)})
    return achados


def marcadores(caminho_imagem, figs_do_conjunto) -> list[dict]:
    """Roda o Tesseract na imagem do desenho. Qualquer falha devolve [] (o desenho só não fica clicável)."""
    figs = {fig_inteira(f) for f in figs_do_conjunto} - {''}
    if not figs or not tem_tesseract():
        return []
    try:
        # psm 11 = texto esparso (números soltos pelo desenho); só dígitos.
        r = subprocess.run(
            ['tesseract', str(caminho_imagem), 'stdout', '--psm', '11',
             '-c', 'tessedit_char_whitelist=0123456789', 'tsv'],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        logger.exception('OCR do desenho %s', caminho_imagem)
        return []
    if r.returncode != 0:
        logger.warning('OCR do desenho %s: %s', caminho_imagem, (r.stderr or '')[:300])
        return []
    return ler_tsv(r.stdout, figs)
