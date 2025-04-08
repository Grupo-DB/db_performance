from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

def gerar_pdf_rh(dados_relatorio, trimestre):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    p.setFont("Helvetica-Bold", 14)
    p.drawString(2 * cm, height - 2 * cm, f"Relatório de Avaliações Pendentes - {trimestre}")

    y = height - 3.5 * cm
    p.setFont("Helvetica", 12)

    for item in dados_relatorio:
        if y < 4 * cm:
            p.showPage()
            y = height - 3 * cm
            p.setFont("Helvetica", 12)

        p.setFont("Helvetica-Bold", 12)
        p.drawString(2 * cm, y, f"Avaliador: {item['avaliador']}")
        y -= 0.6 * cm

        p.setFont("Helvetica", 11)
        for avaliado in item['avaliados']:
            if y < 3 * cm:
                p.showPage()
                y = height - 3 * cm
                p.setFont("Helvetica", 11)

            p.drawString(3 * cm, y, f"- {avaliado}")
            y -= 0.5 * cm

        y -= 0.5 * cm  # espaço entre grupos

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer
