"""Define a senha única do Cockpit Financeiro e derruba quem estava logado.

    python manage.py senha_cockpit          # pergunta a senha (não fica no histórico do shell)
"""
import getpass

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from cockpitFinanceiro.models import ConfiguracaoCockpit


class Command(BaseCommand):
    help = 'Define a senha única de acesso ao Cockpit Financeiro.'

    def handle(self, *args, **opts):
        senha = getpass.getpass('Nova senha: ')
        if len(senha) < 10:
            raise CommandError('Use pelo menos 10 caracteres.')
        if senha != getpass.getpass('Repita: '):
            raise CommandError('As senhas não conferem.')
        config = ConfiguracaoCockpit.atual()
        config.senha_hash = make_password(senha)
        config.versao_senha += 1
        config.save()
        self.stdout.write(self.style.SUCCESS('Senha definida. Sessões anteriores foram encerradas.'))
