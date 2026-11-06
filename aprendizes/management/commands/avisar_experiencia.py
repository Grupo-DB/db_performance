"""Manda por e-mail os vencimentos do período de experiência (30º e 90º dia).

Uma vez por dia; idempotente (ver aprendizes/avisos.py).

    manage.py avisar_experiencia            # envia
    manage.py avisar_experiencia --dry-run  # só lista
    manage.py avisar_experiencia --data 2026-12-01

Cron na VM (o Celery beat do projeto está desligado):

    0 7 * * * cd /caminho/db_performance && ./venv/bin/python manage.py avisar_experiencia >> /var/log/avisos_experiencia.log 2>&1
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from aprendizes.avisos import avisar, etapas_a_avisar


class Command(BaseCommand):
    help = 'Envia por e-mail os vencimentos do período de experiência (30 e 90 dias).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Lista sem enviar nem gravar.')
        parser.add_argument('--data', default=None, help='Data de referência AAAA-MM-DD (padrão: hoje).')

    def handle(self, *args, **op):
        hoje = None
        if op['data']:
            try:
                hoje = datetime.strptime(op['data'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('--data precisa estar no formato AAAA-MM-DD.')

        pendentes = etapas_a_avisar(hoje)
        if not pendentes:
            self.stdout.write(self.style.SUCCESS('Nenhum vencimento de experiência a avisar hoje.'))
            return

        prefixo = '[simulação] ' if op['dry_run'] else ''
        for p in pendentes:
            e = p['etapa']
            self.stdout.write(
                f'{prefixo}{e.vencimento:%d/%m/%Y} {e.acompanhamento.nome} — {e.get_tipo_display()} '
                f'({p["dias"]} dia(s), degrau {p["marco"]})'
            )

        emails = avisar(pendentes, simular=op['dry_run'])
        if not emails:
            self.stdout.write(self.style.WARNING(
                'SEM DESTINATÁRIO: ninguém ativo no grupo RHGestor com e-mail e EMAILS_AVISO_EXPERIENCIA vazio. '
                'Nada foi registrado; o aviso sai quando houver destinatário.'
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f'{prefixo}{len(pendentes)} vencimento(s) em 1 e-mail → {", ".join(emails)}'
        ))
