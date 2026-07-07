from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

from .pdf_utils import _cabecalho, _caixa_info, _rodape, _tabela_nomes, _titulo_secao


def gerar_pdf_rh(dados_relatorio, caminho_logo, trimestre_atual):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    titulo = 'Relatório de Avaliações Pendentes'
    subtitulo = 'Relação de avaliadores com avaliações pendentes no período'

    y = _cabecalho(c, width, height, caminho_logo, titulo, subtitulo)
    y = _caixa_info(c, width, y, [
        ('Período', trimestre_atual),
        ('Avaliadores pendentes', str(len(dados_relatorio))),
    ])

    limite_minimo = 4 * cm

    for item in dados_relatorio:
        if y < limite_minimo:
            _rodape(c, width)
            c.showPage()
            y = _cabecalho(c, width, height, caminho_logo, titulo, subtitulo)

        y = _titulo_secao(c, width, y, f"Avaliador: {item['avaliador']}")
        y = _tabela_nomes(
            c, width, height, y, item['avaliados'], caminho_logo, titulo, subtitulo,
            cabecalho_coluna='Colaborador sem avaliação',
        )
        y -= 0.5 * cm

    _rodape(c, width)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
