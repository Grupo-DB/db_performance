"""Lê por OCR os números dos desenhos já importados (26/11/2026) — para catálogos importados antes do Tesseract.

    python manage.py ocr_desenhos_pecas              # todos os catálogos
    python manage.py ocr_desenhos_pecas --catalogo 1
"""
from django.core.management.base import BaseCommand, CommandError

from catalogos import pecas_ocr
from catalogos import pecas_oficina as po
from catalogos.models import ConjuntoPecas


class Command(BaseCommand):
    help = 'Acha os números dos desenhos explodidos por OCR (desenho clicável na tela Peças da Oficina).'

    def add_arguments(self, parser):
        parser.add_argument('--catalogo', type=int)

    def handle(self, *args, **o):
        if not pecas_ocr.tem_tesseract():
            raise CommandError('Instale o Tesseract: sudo apt install tesseract-ocr')
        qs = ConjuntoPecas.objects.exclude(desenho='').prefetch_related('pecas')
        if o['catalogo']:
            qs = qs.filter(catalogo_id=o['catalogo'])
        total = com = 0
        for cj in qs:
            caminho = po.caminho_desenho(cj)
            if caminho is None:
                continue
            cj.marcadores = pecas_ocr.marcadores(caminho, [p.fig for p in cj.pecas.all()])
            cj.save(update_fields=['marcadores'])
            total += 1
            com += bool(cj.marcadores)
        self.stdout.write(self.style.SUCCESS(f'{total} desenhos lidos; {com} com números achados.'))
