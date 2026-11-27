"""Importa do SGA os equipamentos que têm ficha de vistoria (tipo pelo prefixo da TAG). Sem --aplicar só mostra."""
from django.core.management.base import BaseCommand

from combustivel import erp
from vistorias import sga


class Command(BaseCommand):
    help = 'Importa do SGA os equipamentos com ficha de vistoria (ver vistorias/sga.py).'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Grava (sem isto, só a prévia).')
        parser.add_argument('--periodicidade', default='MENSAL', choices=['MENSAL', 'BIMESTRAL', 'TRIMESTRAL'])

    def handle(self, *args, aplicar=False, periodicidade='MENSAL', **opts):
        lista = erp.equipamentos()
        r = sga.importar(lista, None, periodicidade) if aplicar else sga.planejar(lista)
        self.stdout.write(f"{'Importados' if aplicar else 'Entrariam'}: {len(r['entrar'])}")
        for l in r['entrar']:
            self.stdout.write(f"  {l['tag']:<14} {l['tipo_descricao']:<22} {l['unidade']}  {l['descricao'][:50]}")
        self.stdout.write(f"Já cadastrados: {len(r['existentes'])}")
        self.stdout.write(f"Sem ficha de vistoria ({len(r['sem_ficha'])}): " + ', '.join(l['tag'] for l in r['sem_ficha']))
        self.stdout.write(f"Ignorados ({len(r['ignorados'])}): " + ', '.join(f"{l['tag']} ({l['motivo']})" for l in r['ignorados']))
        if not aplicar:
            self.stdout.write('Prévia apenas. Rode com --aplicar para gravar.')
