from django.core.management.base import BaseCommand

from comercialAgro.views import importar_cfem


class Command(BaseCommand):
    help = ('Importa a CFEM da ANM (CFEM_Arrecadacao.csv, baixado pelo navegador em dadosabertos.anm.gov.br/CFEM, '
            'porque o site barra download automático) para a visão de concorrentes do Mercado.')

    def add_arguments(self, parser):
        parser.add_argument('arquivo')
        parser.add_argument('--desde', type=int, help='primeiro ano (padrão: 3 anos atrás)')

    def handle(self, *args, **opts):
        r = importar_cfem(opts['arquivo'], opts.get('desde'))
        self.stdout.write(self.style.SUCCESS(
            f"{r['linhas']} linhas de calcário ({r['corrigidas']} corrigidas pelo valor pago) → {r['unidades']} unidades, "
            f"{r['empresas_agro']} empresas de calcário agrícola; dados até {r['ate']}."))
