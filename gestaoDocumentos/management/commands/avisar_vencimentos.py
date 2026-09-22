"""Avisa por e-mail e pelo sino os documentos perto do vencimento.

Pensado para rodar uma vez por dia. É idempotente: cada degrau de aviso fica
registrado em `AvisoVencimento`, então rodar de novo no mesmo dia não reenvia.

    manage.py avisar_vencimentos            # envia
    manage.py avisar_vencimentos --dry-run  # só lista o que enviaria
    manage.py avisar_vencimentos --data 2026-12-01  # simula outro dia

No servidor, uma linha de cron às 7h basta (o Celery beat deste projeto está
desligado, e o comando não depende dele):

    0 7 * * * cd /caminho/db_performance && ./venv/bin/python manage.py avisar_vencimentos >> /var/log/avisos_documentos.log 2>&1
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from gestaoDocumentos.vencimentos import avisar, documentos_a_avisar


class Command(BaseCommand):
    help = 'Envia os avisos de vencimento dos documentos (contratos, seguros, alvarás, etc.)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Mostra o que seria enviado sem mandar e-mail nem gravar nada.',
        )
        parser.add_argument(
            '--data', default=None,
            help='Data de referência no formato AAAA-MM-DD (padrão: hoje).',
        )

    def handle(self, *args, **opcoes):
        simular = opcoes['dry_run']
        referencia = None
        if opcoes['data']:
            try:
                referencia = datetime.strptime(opcoes['data'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('--data precisa estar no formato AAAA-MM-DD.')

        pendentes = documentos_a_avisar(hoje=referencia)
        if not pendentes:
            self.stdout.write(self.style.SUCCESS('Nenhum documento a avisar hoje.'))
            return

        enviados, sem_destinatario = 0, 0
        for pendencia in pendentes:
            config = pendencia['config']
            titulo = config['titulo'](pendencia['documento'])
            emails = avisar(pendencia, simular=simular)

            if emails:
                enviados += 1
                estilo = self.style.SUCCESS
                destino = ', '.join(emails)
            else:
                sem_destinatario += 1
                estilo = self.style.WARNING
                destino = 'SEM DESTINATÁRIO'

            prefixo = '[simulação] ' if simular else ''
            self.stdout.write(estilo(
                f'{prefixo}{config["rotulo"]} #{pendencia["documento"].id} — {titulo} — '
                f'{pendencia["dias"]} dia(s) (degrau {pendencia["marco"]}) → {destino}'
            ))

        resumo = f'{enviados} aviso(s) enviado(s)'
        if sem_destinatario:
            resumo += (f'; {sem_destinatario} sem destinatário — preencha o Responsável Interno '
                       f'ou configure EMAILS_AVISO_DOCUMENTOS')
        self.stdout.write(self.style.SUCCESS(resumo))
