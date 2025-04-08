from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO

def gerar_pdf_avaliados(avaliador_nome, nomes_avaliados):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)

    largura, altura = A4
    y = altura - 100

    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, y, f"Avaliações Pendentes - {avaliador_nome}")
    y -= 40

    p.setFont("Helvetica", 12)
    for nome in nomes_avaliados:
        if y < 50:  # Quebra de página
            p.showPage()
            y = altura - 50
        p.drawString(70, y, f"- {nome}")
        y -= 20

    p.save()
    buffer.seek(0)
    return buffer
