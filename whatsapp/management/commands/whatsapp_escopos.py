"""
Mostra como os escopos do atendimento (RH x TI) estão resolvendo hoje.

O vínculo entre grupo e número é o NOME do número no admin, então vale conferir
depois de cadastrar número novo ou renomear um existente:

    python manage.py whatsapp_escopos
"""
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from whatsapp import services
from whatsapp.models import Conversa, NumeroNegocio


class Command(BaseCommand):
    help = 'Confere o casamento entre grupos, números e conversas do WhatsApp.'

    def handle(self, *args, **opcoes):
        self.stdout.write('NÚMEROS CADASTRADOS')
        for numero in NumeroNegocio.objects.all():
            marca = ' (padrão)' if numero.is_padrao else ''
            ativo = '' if numero.ativo else ' [inativo]'
            self.stdout.write(f'  #{numero.id} {numero.nome}{marca}{ativo} — {numero.phone_number_id}')

        self.stdout.write('')
        for escopo, cfg in services.ESCOPOS.items():
            ids = services.numeros_do_escopo(escopo)
            nomes = list(NumeroNegocio.objects.filter(id__in=ids).values_list('nome', flat=True))
            conversas = Conversa.objects.filter(numero_id__in=ids).count() if ids else 0
            regra = ('equipe inteira vê tudo (compartilhado)'
                     if services.escopo_compartilhado(escopo)
                     else 'cada atendente vê só as suas e as sem dono')
            self.stdout.write(self.style.MIGRATE_HEADING(f'ESCOPO {escopo} — {regra}'))
            if ids:
                self.stdout.write(f'  número(s): {", ".join(nomes)} — {conversas} conversa(s)')
            else:
                self.stdout.write(self.style.ERROR(
                    '  NENHUM número casou: renomeie o cadastro para '
                    f'"{escopo}" ou use settings.WHATSAPP_NUMEROS_POR_ESCOPO.'))
            for papel in ('gestor', 'atendentes'):
                grupo = Group.objects.filter(name=cfg[papel]).first()
                if grupo is None:
                    self.stdout.write(self.style.WARNING(f'  {papel}: grupo {cfg[papel]} NÃO existe'))
                    continue
                pessoas = list(grupo.user_set.values_list('username', flat=True))
                self.stdout.write(f'  {papel} ({cfg[papel]}): {", ".join(pessoas) or "ninguém"}')

            # Atendente que também é gestor volta a enxergar (e a ser avisado de)
            # TODAS as conversas do escopo — o grupo de gestor vence. Num escopo
            # pessoal como o RH isso reproduz exatamente o sintoma de "está
            # notificando pra mim as conversas da colega", com o código certo.
            if not services.escopo_compartilhado(escopo):
                atendentes = Group.objects.filter(name=cfg['atendentes']).first()
                gestores = Group.objects.filter(name=cfg['gestor']).first()
                if atendentes and gestores:
                    nos_dois = set(atendentes.user_set.values_list('username', flat=True)) & \
                               set(gestores.user_set.values_list('username', flat=True))
                    if nos_dois:
                        self.stdout.write(self.style.WARNING(
                            f'  ATENÇÃO: {", ".join(sorted(nos_dois))} está nos DOIS grupos. '
                            'Gestor vê e é avisado de tudo do escopo — se a ideia era '
                            'atender só as suas, tire do grupo de gestor.'))

        sem_grupo = User.objects.filter(
            is_active=True, filas_whatsapp__isnull=False,
        ).exclude(
            groups__name__in=[g for cfg in services.ESCOPOS.values() for g in cfg.values()],
        ).distinct()
        if sem_grupo:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'Em fila de WhatsApp mas fora dos grupos novos (seguem na regra antiga, '
                'a das filas): ' + ', '.join(u.username for u in sem_grupo)))

        orfas = Conversa.objects.filter(numero__isnull=True).count()
        if orfas:
            self.stdout.write('')
            self.stdout.write(f'{orfas} conversa(s) sem número — contam para o escopo do número padrão.')
