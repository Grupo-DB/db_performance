"""
Mostra como os escopos do atendimento (RH x TI) estão resolvendo hoje.

O vínculo entre grupo e número é o NOME do número no admin, então vale conferir
depois de cadastrar número novo ou renomear um existente:

    python manage.py whatsapp_escopos
    python manage.py whatsapp_escopos --usuario ana   # por que ESTA pessoa vê o que vê
    python manage.py whatsapp_escopos --conversa 5199  # dono, avisos e autores de UMA conversa
"""
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from whatsapp import services
from whatsapp.models import Conversa, NumeroNegocio


class Command(BaseCommand):
    help = 'Confere o casamento entre grupos, números e conversas do WhatsApp.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--usuario', action='append', default=[],
            help='username, nome ou e-mail (parcial). Explica o que a pessoa enxerga e por quê. Pode repetir.')
        parser.add_argument(
            '--conversa', action='append', default=[],
            help='id, nome do contato ou parte do telefone. Linha do tempo de mensagens e avisos. Pode repetir.')

    def handle(self, *args, **opcoes):
        if opcoes['usuario'] or opcoes['conversa']:
            for termo in opcoes['usuario']:
                self._explicar_usuario(termo)
            for termo in opcoes['conversa']:
                self._linha_do_tempo(termo)
            return

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

        # Staff conta como gestor de TODOS os escopos (services.filtro_de_conversas,
        # pode_atender, eh_gestor_de). Quem ganhou staff só para editar texto no
        # admin passa a ver e a ser avisado de todo o RH sem estar no grupo.
        staff = User.objects.filter(
            is_active=True, is_staff=True,
            groups__name__in=[cfg['atendentes'] for cfg in services.ESCOPOS.values()],
        ).distinct()
        if staff:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'ATENÇÃO: atendente(s) com is_staff — enxergam e atendem TUDO, de todos os '
                'números, como gestor: ' + ', '.join(u.username for u in staff)))

    def _explicar_usuario(self, termo):
        from django.db.models import Q

        achados = User.objects.filter(
            Q(username__icontains=termo) | Q(first_name__icontains=termo)
            | Q(last_name__icontains=termo) | Q(email__icontains=termo)
        ).order_by('username')
        if not achados:
            self.stdout.write(self.style.ERROR(f'Nenhum usuário casa com "{termo}".'))
            return
        for u in achados:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'{u.username} — {u.get_full_name() or "(sem nome)"}{"" if u.is_active else " [INATIVO]"}'))
            grupos = sorted(u.groups.values_list('name', flat=True))
            self.stdout.write(f'  staff: {u.is_staff}   superusuário: {u.is_superuser}')
            self.stdout.write(f'  grupos do WhatsApp: {", ".join(g for g in grupos if "hatsapp" in g) or "nenhum"}')
            self.stdout.write(f'  filas: {", ".join(u.filas_whatsapp.values_list("nome", flat=True)) or "nenhuma"}')
            papeis = services.escopos_do_usuario(u)
            if u.is_staff:
                motivo = 'STAFF: vê, é avisado e atende TODAS as conversas de todos os números'
            elif not papeis:
                motivo = 'fora dos grupos novos: regra antiga, vê tudo das filas de que participa'
            else:
                motivo = '; '.join(
                    f'{e}: ' + ('gestor — vê e é avisado de tudo do número' if p == 'gestor'
                                else 'atendente, equipe vê tudo' if services.escopo_compartilhado(e)
                                else 'atendente — só as suas e as sem dono')
                    for e, p in papeis.items())
            self.stdout.write(f'  regra: {motivo}')

            visiveis = services.conversas_visiveis(u).filter(status='ABERTA')
            de_outro = visiveis.exclude(responsavel=u).exclude(responsavel__isnull=True)
            self.stdout.write(
                f'  conversas abertas que enxerga: {visiveis.count()} '
                f'(sem dono: {visiveis.filter(responsavel__isnull=True).count()}, '
                f'de OUTRO atendente: {de_outro.count()})')
            for c in de_outro.select_related('responsavel', 'numero')[:10]:
                self.stdout.write(
                    f'    #{c.pk} {c.contato_nome or c.contato_telefone} — com '
                    f'{c.responsavel.username} — número {getattr(c.numero, "nome", "(padrão)")} '
                    f'[escopo {services.escopo_da_conversa(c) or "nenhum"}]')

    def _linha_do_tempo(self, termo, limite=40):
        """Mensagens (com autor) e avisos (com destinatário) misturados por horário."""
        from django.db.models import Q
        from django.utils import timezone

        from whatsapp.models import WhatsAppNotificacao

        filtro = Q(contato_nome__icontains=termo) | Q(contato_telefone__icontains=termo)
        if termo.isdigit():
            filtro |= Q(pk=int(termo))
        conversas = Conversa.objects.filter(filtro).select_related('responsavel', 'numero', 'fila')
        if not conversas:
            self.stdout.write(self.style.ERROR(f'Nenhuma conversa casa com "{termo}".'))
            return
        for c in conversas.order_by('-ultima_mensagem_em')[:5]:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'#{c.pk} {c.contato_nome or "-"} {c.contato_telefone} — {c.status} — '
                f'número {getattr(c.numero, "nome", "(padrão)")} [escopo {services.escopo_da_conversa(c) or "nenhum"}] — '
                f'fila {getattr(c.fila, "nome", "-")} — dono AGORA: {getattr(c.responsavel, "username", "ninguém")}'))
            eventos = []
            for m in c.mensagens.select_related('autor').order_by('-created_at')[:limite]:
                if m.direcao == 'ENTRADA':
                    quem = 'cliente'
                else:
                    quem = m.autor.username if m.autor_id else 'robô/celular'
                eventos.append((m.created_at, f'msg {m.direcao:<7} {quem:<22} {(m.texto or m.tipo)[:60]!r}'))
            for n in (WhatsAppNotificacao.objects.filter(conversa=c)
                      .select_related('usuario_notificado').order_by('-created_at')[:limite]):
                eventos.append((n.created_at, f'aviso -> {n.usuario_notificado.username:<20} {n.tipo}{"" if n.lido else " (não lido)"}'))
            for quando, texto in sorted(eventos)[-limite:]:
                self.stdout.write(f'  {timezone.localtime(quando):%d/%m %H:%M:%S}  {texto}')
