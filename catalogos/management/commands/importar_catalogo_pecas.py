"""Importa o catálogo de peças do fabricante (PDF oficial) para a tela "Peças da Oficina" (26/11/2026).

    python manage.py importar_catalogo_pecas "/caminho/RK430 - catalago.pdf" --fabricante Randon
    python manage.py importar_catalogo_pecas novo.pdf --catalogo 1      # regrava o catálogo 1 (nova edição)

Precisa do poppler-utils (pdftotext/pdftoppm) no servidor.
"""
from django.core.management.base import BaseCommand, CommandError

from catalogos import pecas_catalogo as pc
from catalogos import pecas_oficina as po
from catalogos.models import CatalogoPecas


class Command(BaseCommand):
    help = 'Importa um catálogo de peças do fabricante em PDF (conjuntos, peças e desenhos).'

    def add_arguments(self, parser):
        parser.add_argument('pdf')
        parser.add_argument('--nome', default='', help='Nome do catálogo (padrão: o modelo escrito nas páginas)')
        parser.add_argument('--fabricante', default='')
        parser.add_argument('--edicao', default='')
        parser.add_argument('--catalogo', type=int, help='Id de um catálogo já importado, para regravar')
        parser.add_argument('--sem-desenhos', action='store_true')

    def handle(self, *args, **o):
        if not pc.tem_poppler():
            raise CommandError('Instale o poppler-utils (pdftotext e pdftoppm): sudo apt install poppler-utils')
        catalogo = None
        if o['catalogo']:
            catalogo = CatalogoPecas.objects.filter(pk=o['catalogo']).first()
            if catalogo is None:
                raise CommandError(f'Catálogo {o["catalogo"]} não existe.')
        cat = po.importar(o['pdf'], nome=o['nome'], fabricante=o['fabricante'], edicao=o['edicao'],
                          catalogo=catalogo, desenhos=not o['sem_desenhos'])
        n_conj = cat.conjuntos.count()
        n_pecas = sum(c.pecas.count() for c in cat.conjuntos.all())
        sem = cat.conjuntos.filter(desenho='').count()
        self.stdout.write(self.style.SUCCESS(
            f'Catálogo {cat.id} "{cat.nome}": {cat.paginas} páginas, {n_conj} conjuntos, {n_pecas} peças'
            + (f', {sem} conjuntos sem desenho' if sem else '') + '.'))
