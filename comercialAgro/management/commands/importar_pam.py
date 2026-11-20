from django.core.management.base import BaseCommand

from comercialAgro.views import importar_pam, importar_pedreiras


class Command(BaseCommand):
    help = ('Baixa do IBGE a área plantada do Brasil (PAM, 12 culturas + milho 2ª safra) e, com --pastagem, a pastagem '
            'plantada do Censo Agro 2017 (~2 min); com --anm, as lavras de calcário agrícola da ANM.')

    def add_arguments(self, parser):
        parser.add_argument('--pastagem', action='store_true', help='também a pastagem (boa e degradada) do Censo 2017')
        parser.add_argument('--anm', action='store_true', help='também as lavras de calcário da ANM (concorrência)')

    def handle(self, *args, **opts):
        r = importar_pam(com_pastagem=opts['pastagem'])
        self.stdout.write(self.style.SUCCESS(f"PAM {r['ano']}: {r['linhas']} linhas; pastagem: {r['pastagem']} linhas."))
        if opts['anm']:
            self.stdout.write(self.style.SUCCESS(f'ANM: {importar_pedreiras()} lavras de calcário agrícola.'))
