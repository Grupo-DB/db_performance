"""Importa a planilha de uniformes (abas FEMININOS/MASCULINOS × GANHA/COMPRA).

    python manage.py importar_uniformes /root/pasta/UNIFORMES_DE_INVERNO_2026.xlsx --campanha "Inverno/2026" --ano 2026 [--simular]

A campanha é criada (com as peças, preços e regras do Inverno/2026) se não existir.
Reimportar atualiza o pedido da mesma pessoa + modalidade em vez de duplicar.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from uniformes.importacao import importar_linhas, linhas_do_xlsx
from uniformes.models import Campanha
from uniformes.regras import REGRAS_PADRAO, criar_catalogo


class Simulacao(Exception):
    pass


class Command(BaseCommand):
    help = 'Importa a planilha de uniformes para o Controle Uniformes.'

    def add_arguments(self, parser):
        parser.add_argument('arquivo')
        parser.add_argument('--campanha', default='Inverno/2026')
        parser.add_argument('--ano', type=int, default=2026)
        parser.add_argument('--simular', action='store_true', help='Mostra o resultado e desfaz tudo.')

    def handle(self, *args, **opts):
        try:
            linhas = linhas_do_xlsx(opts['arquivo'])
        except FileNotFoundError as e:
            raise CommandError(f'Arquivo não encontrado: {opts["arquivo"]}') from e
        self.stdout.write(f'   linhas lidas: {len(linhas)}')
        try:
            with transaction.atomic():
                campanha, nova = Campanha.objects.get_or_create(
                    nome=opts['campanha'], defaults={'ano': opts['ano'], 'regras': REGRAS_PADRAO})
                if nova or not campanha.pecas.exists():
                    criar_catalogo(campanha)
                self.stdout.write(f'   campanha: {campanha.nome} ({"criada agora" if nova else "já existia"})')
                r = importar_linhas(campanha, linhas)
                self.stdout.write(f'   pedidos novos: {r["criados"]} | atualizados: {r["atualizados"]}')
                if r['pecas_nao_encontradas']:
                    self.stdout.write(f'   peças sem cadastro na campanha: {", ".join(r["pecas_nao_encontradas"])}')
                if opts['simular']:
                    raise Simulacao
        except Simulacao:
            self.stdout.write('   (simulação: nada gravado)')
