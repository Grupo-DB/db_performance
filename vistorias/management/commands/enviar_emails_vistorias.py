"""Cron a cada minuto: manda os e-mails de vistoria que ficaram pendentes (reinício, SMTP fora)."""
from django.core.management.base import BaseCommand

from vistorias import avisos


class Command(BaseCommand):
    help = 'Envia e-mails pendentes do módulo de vistorias (suspensão, liberação, cancelamento, rejeição).'

    def handle(self, *args, **opts):
        n = avisos.enviar_pendentes()
        if n:
            self.stdout.write(f'{n} e-mail(s) enviado(s).')
