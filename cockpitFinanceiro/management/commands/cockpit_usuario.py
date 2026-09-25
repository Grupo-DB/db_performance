"""Gerencia os usuários do Cockpit Financeiro.

    python manage.py cockpit_usuario listar
    python manage.py cockpit_usuario criar <login> "<Nome>" [--edicao]
    python manage.py cockpit_usuario resetar <login>        # nova senha provisória
    python manage.py cockpit_usuario perfil <login> leitura|edicao
    python manage.py cockpit_usuario bloquear <login>
    python manage.py cockpit_usuario desbloquear <login>

`criar` e `resetar` mostram uma senha provisória: passe-a à pessoa por um canal diferente do
link. No primeiro acesso ela é obrigada a trocar. Resetar, bloquear e mudar perfil derrubam
as sessões abertas daquele usuário.
"""
import re
import secrets
import string

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from cockpitFinanceiro.models import UsuarioCockpit

LOGIN_VALIDO = re.compile(r'^[a-z0-9._-]{2,60}$')


def _provisoria():
    # Sem caracteres que se confundem (0/O, 1/l/I) — a senha é ditada ou copiada à mão.
    alfabeto = ''.join(c for c in string.ascii_letters + string.digits if c not in '0O1lI')
    return ''.join(secrets.choice(alfabeto) for _ in range(10))


class Command(BaseCommand):
    help = 'Gerencia os usuários do Cockpit Financeiro (listar, criar, resetar, perfil, bloquear, desbloquear).'

    def add_arguments(self, parser):
        parser.add_argument('acao', choices=['listar', 'criar', 'resetar', 'perfil', 'bloquear', 'desbloquear'])
        parser.add_argument('login', nargs='?')
        parser.add_argument('extra', nargs='?', help='nome (criar) ou perfil (perfil)')
        parser.add_argument('--edicao', action='store_true', help='cria já com perfil de edição')

    def _get(self, login):
        if not login:
            raise CommandError('Informe o login.')
        u = UsuarioCockpit.objects.filter(login=login.strip().lower()).first()
        if not u:
            raise CommandError(f'Usuário "{login}" não existe.')
        return u

    def _mostra_senha(self, u, senha):
        self.stdout.write(self.style.SUCCESS(f'\n  Usuário: {u.login}\n  Senha provisória: {senha}\n'))
        self.stdout.write('  Passe a senha por um canal diferente do link. No primeiro acesso ela será trocada.\n')

    def handle(self, acao, login=None, extra=None, edicao=False, **_):
        if acao == 'listar':
            for u in UsuarioCockpit.objects.all():
                acesso = f'{u.ultimo_acesso:%d/%m/%Y %H:%M}' if u.ultimo_acesso else 'nunca acessou'
                situacao = 'ativo' if u.ativo else 'BLOQUEADO'
                troca = 'troca pendente' if u.trocar_senha else ''
                self.stdout.write(f'{u.login:24} {u.nome:30} {u.perfil:8} {situacao:10} {troca:15} {acesso}')
            return

        if acao == 'criar':
            login = (login or '').strip().lower()
            if not LOGIN_VALIDO.match(login):
                raise CommandError('Login inválido: use letras minúsculas, números, ponto, hífen ou _.')
            if not extra:
                raise CommandError('Informe o nome entre aspas: criar <login> "Nome Sobrenome"')
            if UsuarioCockpit.objects.filter(login=login).exists():
                raise CommandError(f'Já existe o usuário "{login}". Use resetar para gerar nova senha.')
            senha = _provisoria()
            u = UsuarioCockpit.objects.create(
                login=login, nome=extra.strip(), senha_hash=make_password(senha), trocar_senha=True,
                perfil=UsuarioCockpit.PERFIL_EDICAO if edicao else UsuarioCockpit.PERFIL_LEITURA,
            )
            self.stdout.write(f'Criado {u} — perfil {u.get_perfil_display()}.')
            self._mostra_senha(u, senha)
            return

        u = self._get(login)
        if acao == 'resetar':
            senha = _provisoria()
            u.senha_hash = make_password(senha)
            u.trocar_senha = True
            u.versao += 1
            u.save()
            self._mostra_senha(u, senha)
        elif acao == 'perfil':
            if extra not in (UsuarioCockpit.PERFIL_LEITURA, UsuarioCockpit.PERFIL_EDICAO):
                raise CommandError('Perfil deve ser "leitura" ou "edicao".')
            u.perfil = extra
            u.versao += 1
            u.save()
            self.stdout.write(self.style.SUCCESS(f'{u} agora é {u.get_perfil_display()}.'))
        elif acao in ('bloquear', 'desbloquear'):
            u.ativo = acao == 'desbloquear'
            u.versao += 1
            u.save()
            self.stdout.write(self.style.SUCCESS(f'{u} {"desbloqueado" if u.ativo else "bloqueado"}.'))
