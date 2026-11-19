from django.core.management.base import BaseCommand
from django.db import transaction

from comercialAgro import geo
from comercialAgro.models import AreaPlantada


class Command(BaseCommand):
    help = 'Baixa do IBGE/SIDRA (PAM, tabela 5457) a área plantada por município e cultura no RS.'

    def add_arguments(self, parser):
        parser.add_argument('--periodo', default='last 1', help='"last 1" (padrão), "2024" ou "2023,2024"')

    def handle(self, *args, **opts):
        linhas = geo.baixar_pam(opts['periodo'])
        anos = sorted({l['ano'] for l in linhas})
        with transaction.atomic():
            AreaPlantada.objects.filter(ano__in=anos).delete()
            AreaPlantada.objects.bulk_create([AreaPlantada(**l) for l in linhas], batch_size=1000)
        self.stdout.write(self.style.SUCCESS(f'{len(linhas)} linhas de {anos} ({len({l["municipio_ibge"] for l in linhas})} municípios).'))
