"""E-mail dos vencimentos da experiência — 06/11/2026.

    venv/bin/python manage.py test aprendizes.tests_avisos --settings=db_performance.test_settings
"""
from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from gestaoDocumentos.models import AvisoVencimento

from .avisos import etapas_a_avisar
from .models import Acompanhamento, Etapa

HOJE = date(2026, 11, 10)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAILS_AVISO_EXPERIENCIA=[])
class AvisosExperienciaTests(TestCase):
    def setUp(self):
        rh = User.objects.create_user('rh', email='rh@exemplo.com', password='x')
        rh.groups.add(Group.objects.get_or_create(name='RHGestor')[0])

        def pessoa(nome, tipo, dias, situacao=Etapa.PENDENTE, pessoa=Acompanhamento.EM_ANDAMENTO):
            a = Acompanhamento.objects.create(nome=nome, setor='Expedição', situacao=pessoa)
            return Etapa.objects.create(acompanhamento=a, tipo=tipo, vencimento=HOJE + timedelta(days=dias), situacao=situacao)

        self.prox = pessoa('ANA', Etapa.PRIMEIRO_VENCIMENTO, 5)
        self.hoje = pessoa('BRUNO', Etapa.PRORROGACAO, 0)
        self.venc = pessoa('CARLA', Etapa.PRIMEIRO_VENCIMENTO, -3)
        pessoa('LONGE', Etapa.PRIMEIRO_VENCIMENTO, 20)                      # fora da janela
        pessoa('ANTIGA', Etapa.PRIMEIRO_VENCIMENTO, -60)                    # pendência velha da planilha
        pessoa('FEITA', Etapa.PRIMEIRO_VENCIMENTO, 2, situacao=Etapa.CONCLUIDO)
        pessoa('SAIU', Etapa.PRIMEIRO_VENCIMENTO, 2, pessoa=Acompanhamento.DESLIGADO)
        pessoa('EFETIV', Etapa.EFETIVACAO, 2)                               # só 30/90 avisam

    def rodar(self, dia=HOJE):
        call_command('avisar_experiencia', data=dia.isoformat(), stdout=open('/dev/null', 'w'))

    def test_um_email_com_os_tres_e_degraus(self):
        p = {x['etapa'].id: x['marco'] for x in etapas_a_avisar(HOJE)}
        self.assertEqual(p, {self.prox.id: 7, self.hoje.id: 0, self.venc.id: -1})
        self.rodar()
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ['rh@exemplo.com'])
        self.assertIn('3 vencimento(s)', m.subject)
        for nome in ('ANA', 'BRUNO', 'CARLA'):
            self.assertIn(nome, m.body)
        self.assertNotIn('ANTIGA', m.body)

    def test_nao_repete_no_mesmo_degrau_e_avisa_no_seguinte(self):
        self.rodar()
        self.rodar()
        self.assertEqual(len(mail.outbox), 1)
        # ANA: 5 dias → aviso de "próximo" já foi; no dia do vencimento sai o "vence hoje".
        self.rodar(HOJE + timedelta(days=5))
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('ANA', mail.outbox[1].body)

    def test_dry_run_e_sem_destinatario_nao_registram(self):
        call_command('avisar_experiencia', data=HOJE.isoformat(), dry_run=True, stdout=open('/dev/null', 'w'))
        self.assertEqual(len(mail.outbox), 0)
        User.objects.all().update(is_active=False)
        self.rodar()
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(AvisoVencimento.objects.exists())

    @override_settings(EMAILS_AVISO_EXPERIENCIA=['dp@exemplo.com'])
    def test_lista_fixa_do_settings(self):
        self.rodar()
        self.assertEqual(mail.outbox[0].to, ['dp@exemplo.com', 'rh@exemplo.com'])
