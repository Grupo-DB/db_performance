import os
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

# Identidade visual ManagerDB (mesma paleta usada nos e-mails)
AZUL = HexColor('#004EAE')
LARANJA = HexColor('#FFB100')
VERDE = HexColor('#00B036')
CIANO = HexColor('#00CFDD')
CINZA_TEXTO = HexColor('#888888')
CINZA_CLARO = HexColor('#F7FBFF')
CINZA_BORDA = HexColor('#E8EEF5')
BRANCO = HexColor('#FFFFFF')
TEXTO_ESCURO = HexColor('#222222')

MARGEM = 2 * cm


def _barra_topo(c, width, height):
    """Barra tricolor no topo da página."""
    terco = width / 3
    altura = 0.2 * cm
    y = height - altura
    c.setFillColor(AZUL)
    c.rect(0, y, terco, altura, fill=1, stroke=0)
    c.setFillColor(LARANJA)
    c.rect(terco, y, terco, altura, fill=1, stroke=0)
    c.setFillColor(VERDE)
    c.rect(2 * terco, y, width - 2 * terco, altura, fill=1, stroke=0)


def _cabecalho(c, width, height, caminho_logo, titulo, subtitulo=None):
    """Desenha barra tricolor, logo, faixa azul e título. Retorna o y onde o conteúdo pode começar."""
    _barra_topo(c, width, height)

    altura_logo = 1.6 * cm
    y_logo = height - 0.2 * cm - 1.1 * cm - altura_logo
    if caminho_logo and os.path.exists(caminho_logo):
        c.drawImage(
            caminho_logo, MARGEM, y_logo,
            height=altura_logo, preserveAspectRatio=True, mask='auto',
        )

    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(AZUL)
    c.drawRightString(width - MARGEM, height - 1.1 * cm, 'SISTEMA MANAGERDB')

    y_faixa = y_logo - 0.3 * cm
    c.setFillColor(AZUL)
    c.rect(0, y_faixa, width, 0.12 * cm, fill=1, stroke=0)

    y = y_faixa - 1 * cm
    c.setFont('Helvetica-Bold', 18)
    c.setFillColor(AZUL)
    c.drawString(MARGEM, y, titulo)

    if subtitulo:
        y -= 0.7 * cm
        c.setFont('Helvetica', 11)
        c.setFillColor(CINZA_TEXTO)
        c.drawString(MARGEM, y, subtitulo)

    return y - 1 * cm


def _rodape(c, width):
    c.setFillColor(AZUL)
    c.rect(0, 0, width, 1 * cm, fill=1, stroke=0)
    c.setFont('Helvetica', 8)
    c.setFillColor(BRANCO)
    c.drawCentredString(
        width / 2, 0.4 * cm,
        'Relatório gerado automaticamente pelo sistema ManagerDB — Grupo Dagoberto Barcellos',
    )


def _caixa_info(c, width, y, linhas):
    """Box de informações com fundo azul claro e borda ciano à esquerda, no estilo do e-mail."""
    altura = 0.9 * cm + len(linhas) * 0.55 * cm
    largura = width - 2 * MARGEM

    c.setFillColor(CINZA_CLARO)
    c.roundRect(MARGEM, y - altura, largura, altura, 4, fill=1, stroke=0)
    c.setFillColor(CIANO)
    c.rect(MARGEM, y - altura, 0.12 * cm, altura, fill=1, stroke=0)

    ty = y - 0.55 * cm
    for rotulo, valor in linhas:
        c.setFont('Helvetica', 10)
        c.setFillColor(CINZA_TEXTO)
        c.drawString(MARGEM + 0.6 * cm, ty, rotulo)
        c.setFont('Helvetica-Bold', 10)
        c.setFillColor(HexColor('#111111'))
        c.drawString(MARGEM + 4.5 * cm, ty, valor)
        ty -= 0.55 * cm

    return y - altura - 0.8 * cm


def _titulo_secao(c, width, y, texto):
    c.setFont('Helvetica-Bold', 10)
    c.setFillColor(AZUL)
    c.drawString(MARGEM, y, texto.upper())
    return y - 0.5 * cm


def _tabela_nomes(c, width, height, y, nomes, caminho_logo, titulo_pagina, subtitulo_pagina, cabecalho_coluna='Colaborador'):
    """Tabela de uma coluna com os nomes, paginando e repetindo cabeçalho/rodapé quando necessário."""
    largura = width - 2 * MARGEM
    altura_linha = 0.75 * cm
    altura_cabecalho = 0.8 * cm
    limite_inferior = 2.2 * cm

    def _cabecalho_tabela(y_atual):
        c.setFillColor(AZUL)
        c.rect(MARGEM, y_atual - altura_cabecalho, largura, altura_cabecalho, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 10)
        c.setFillColor(BRANCO)
        c.drawString(MARGEM + 0.4 * cm, y_atual - altura_cabecalho + 0.25 * cm, cabecalho_coluna)
        return y_atual - altura_cabecalho

    y = _cabecalho_tabela(y)

    for i, nome in enumerate(nomes):
        if y - altura_linha < limite_inferior:
            _rodape(c, width)
            c.showPage()
            y = _cabecalho(c, width, height, caminho_logo, titulo_pagina, subtitulo_pagina)
            y = _cabecalho_tabela(y)

        c.setFillColor(CINZA_CLARO if i % 2 == 0 else BRANCO)
        c.rect(MARGEM, y - altura_linha, largura, altura_linha, fill=1, stroke=0)
        c.setStrokeColor(CINZA_BORDA)
        c.line(MARGEM, y - altura_linha, MARGEM + largura, y - altura_linha)

        c.setFont('Helvetica', 10)
        c.setFillColor(TEXTO_ESCURO)
        c.drawString(MARGEM + 0.4 * cm, y - altura_linha + 0.25 * cm, nome)
        y -= altura_linha

    return y


def gerar_pdf_avaliados(avaliador_nome, nomes_avaliados, caminho_logo, trimestre_atual):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    titulo = 'Relatório de Avaliações Pendentes'
    subtitulo = f'Avaliador: {avaliador_nome}'

    y = _cabecalho(c, width, height, caminho_logo, titulo, subtitulo)
    y = _caixa_info(c, width, y, [
        ('Período', trimestre_atual),
        ('Pendências', f'{len(nomes_avaliados)} colaborador(es) a avaliar'),
    ])
    y = _titulo_secao(c, width, y, 'Colaboradores a Avaliar')
    _tabela_nomes(c, width, height, y, nomes_avaliados, caminho_logo, titulo, subtitulo)

    _rodape(c, width)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
