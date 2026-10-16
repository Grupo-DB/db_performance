"""Importa a planilha "AVALIAÇÃO PERÍODO DE EXPERIÊNCIA" (uma aba por mês).

    python manage.py importar_experiencia /root/pasta/AVALIACAO_PERIODO_DE_EXPERIENCIA.xlsx [--simular]

Reimportar não duplica: a mesma pessoa + etapa é atualizada.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from aprendizes.importacao import importar_linhas, linhas_do_xlsx


class Simulacao(Exception):
    pass


class Command(BaseCommand):
    help = 'Importa a planilha antiga do período de experiência para o Acompanhamento Aprendizes.'

    def add_arguments(self, parser):
        parser.add_argument('arquivo')
        parser.add_argument('--simular', action='store_true', help='Mostra o resultado e desfaz tudo.')

    def handle(self, *args, **opts):
        try:
            linhas = linhas_do_xlsx(opts['arquivo'])
        except FileNotFoundError as e:
            raise CommandError(f'Arquivo não encontrado: {opts["arquivo"]}') from e
        self.stdout.write(f'   linhas lidas: {len(linhas)}')
        try:
            with transaction.atomic():
                r = importar_linhas(linhas)
                self.stdout.write(
                    f'   pessoas novas: {r["pessoas_criadas"]} | etapas novas: {r["etapas_criadas"]} | '
                    f'etapas atualizadas: {r["etapas_atualizadas"]} | ignoradas: {len(r["ignoradas"])}')
                for i in r['ignoradas']:
                    self.stdout.write(f'     ignorada (aba {i["linha"]}): {i["nome"] or "sem nome"} — {i["motivo"]}')
                if opts['simular']:
                    raise Simulacao
        except Simulacao:
            self.stdout.write('   (simulação: nada gravado)')
