"""Testes dos avisos de vencimento de documentos."""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from gestaoDocumentos import vencimentos
from gestaoDocumentos.models import AvisoVencimento, Contrato, DocumentoNotificacao, Seguro


class MarcosTest(TestCase):
    """A escolha do degrau é a regra que decide quantos e-mails a pessoa recebe."""

    def test_janela_grande_usa_os_degraus_padrao(self):
        self.assertEqual(vencimentos.marcos_da_janela(90), [90, 30, 15, 7, 1, 0])

    def test_janela_curta_descarta_degraus_maiores(self):
        self.assertEqual(vencimentos.marcos_da_janela(5), [5, 1, 0])

    def test_sem_janela_cai_no_padrao(self):
        self.assertEqual(vencimentos.marcos_da_janela(None), [30, 15, 7, 1, 0])

    def test_documento_longe_nao_tem_degrau(self):
        self.assertIsNone(vencimentos.marco_atual(120, 90))

    def test_degrau_e_o_mais_proximo_ja_alcancado(self):
        # 12 dias restantes está no degrau de 15, não no de 30 nem no de 7.
        self.assertEqual(vencimentos.marco_atual(12, 90), 15)

    def test_atraso_do_comando_nao_dispara_todos_os_degraus(self):
        # Rodou faltando 90 dias e só voltou a rodar faltando 3: um aviso, o de 7.
        self.assertEqual(vencimentos.marco_atual(3, 90), 7)

    def test_vencido_tem_degrau_proprio(self):
        self.assertEqual(vencimentos.marco_atual(-5, 30), vencimentos.MARCO_VENCIDO)


@override_settings(EMAILS_AVISO_DOCUMENTOS=['documentos@db.com.br'])
class AvisoVencimentoTest(TestCase):
    def setUp(self):
        self.autor = User.objects.create_user('autor', 'autor@db.com.br', 'x')
        self.hoje = date(2026, 9, 21)
        mail.outbox = []

    def _contrato(self, dias, prazo_aviso=None):
        return Contrato.objects.create(
            numero='C-001', contratado='Fornecedor X', criado_por=self.autor,
            data_fim=self.hoje + timedelta(days=dias), prazo_aviso=prazo_aviso,
        )

    def test_contrato_fora_da_janela_nao_avisa(self):
        self._contrato(dias=45)  # sem prazo_aviso: janela padrão de 30
        self.assertEqual(vencimentos.documentos_a_avisar(hoje=self.hoje), [])

    def test_prazo_aviso_antecipa_o_aviso(self):
        self._contrato(dias=45, prazo_aviso=90)
        pendentes = vencimentos.documentos_a_avisar(hoje=self.hoje)
        self.assertEqual(len(pendentes), 1)
        self.assertEqual(pendentes[0]['marco'], 90)

    def test_envia_email_e_notificacao(self):
        self._contrato(dias=10, prazo_aviso=30)
        for pendencia in vencimentos.documentos_a_avisar(hoje=self.hoje):
            vencimentos.avisar(pendencia)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Vence em 10 dias', mail.outbox[0].subject)
        self.assertEqual(
            sorted(mail.outbox[0].to), ['autor@db.com.br', 'documentos@db.com.br'])
        self.assertEqual(
            DocumentoNotificacao.objects.filter(
                usuario_notificado=self.autor, tipo='VENCIMENTO_PROXIMO').count(), 1)

    def test_nao_reenvia_o_mesmo_degrau(self):
        self._contrato(dias=10, prazo_aviso=30)
        for pendencia in vencimentos.documentos_a_avisar(hoje=self.hoje):
            vencimentos.avisar(pendencia)
        mail.outbox = []

        # Segunda rodada no mesmo dia: nada a fazer.
        self.assertEqual(vencimentos.documentos_a_avisar(hoje=self.hoje), [])

        # No dia seguinte ainda é o degrau 15: continua calado.
        self.assertEqual(
            vencimentos.documentos_a_avisar(hoje=self.hoje + timedelta(days=1)), [])
        self.assertEqual(len(mail.outbox), 0)

    def test_degrau_seguinte_volta_a_avisar(self):
        self._contrato(dias=10, prazo_aviso=30)
        for pendencia in vencimentos.documentos_a_avisar(hoje=self.hoje):
            vencimentos.avisar(pendencia)

        # 5 dias depois restam 5: cai no degrau de 7 e avisa de novo.
        pendentes = vencimentos.documentos_a_avisar(hoje=self.hoje + timedelta(days=5))
        self.assertEqual(len(pendentes), 1)
        self.assertEqual(pendentes[0]['marco'], 7)

    def test_vencido_avisa_uma_vez_so(self):
        self._contrato(dias=-3)
        pendentes = vencimentos.documentos_a_avisar(hoje=self.hoje)
        self.assertEqual(pendentes[0]['marco'], vencimentos.MARCO_VENCIDO)
        vencimentos.avisar(pendentes[0])
        self.assertIn('[Vencido]', mail.outbox[0].subject)

        self.assertEqual(
            vencimentos.documentos_a_avisar(hoje=self.hoje + timedelta(days=30)), [])

    def test_vence_hoje_tem_texto_proprio(self):
        self._contrato(dias=0)
        vencimentos.avisar(vencimentos.documentos_a_avisar(hoje=self.hoje)[0])
        self.assertIn('[Vence hoje]', mail.outbox[0].subject)

    def test_dry_run_nao_grava_nem_envia(self):
        self._contrato(dias=10)
        for pendencia in vencimentos.documentos_a_avisar(hoje=self.hoje):
            vencimentos.avisar(pendencia, simular=True)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(AvisoVencimento.objects.count(), 0)

    def test_seguro_tambem_e_varrido(self):
        Seguro.objects.create(
            seguradora='Porto', numero_apolice='123',
            data_fim=self.hoje + timedelta(days=7),
        )
        pendentes = vencimentos.documentos_a_avisar(hoje=self.hoje)
        self.assertEqual(len(pendentes), 1)
        self.assertEqual(pendentes[0]['config']['rotulo'], 'Seguro')

    def test_responsavel_interno_casa_com_colaborador(self):
        from avaliacoes.management.models import (
            Ambiente, Area, Cargo, Colaborador, Empresa, Filial, Setor,
        )
        empresa = Empresa.objects.create(
            nome='DB', cnpj='1', endereco='r', cidade='c', estado='RS', codigo='01')
        filial = Filial.objects.create(
            empresa=empresa, nome='Matriz', cnpj='1', endereco='r', cidade='c',
            estado='RS', codigo='01')
        area = Area.objects.create(empresa=empresa, filial=filial, nome='Adm')
        setor = Setor.objects.create(empresa=empresa, filial=filial, area=area, nome='TI')
        ambiente = Ambiente.objects.create(
            empresa=empresa, filial=filial, area=area, setor=setor, nome='Escritório')
        cargo = Cargo.objects.create(
            empresa=empresa, filial=filial, area=area, setor=setor, ambiente=ambiente,
            nome='Analista')
        Colaborador.objects.create(
            nome='Maria Souza', email='maria@db.com.br', empresa=empresa, filial=filial,
            setor=setor, area=area, cargo=cargo, ambiente=ambiente,
        )
        contrato = self._contrato(dias=10)
        contrato.responsavel_interno = 'maria souza'  # o cadastro é texto livre
        contrato.save()

        _, emails = vencimentos.destinatarios_do_documento(contrato)
        self.assertIn('maria@db.com.br', emails)

    def test_sem_ninguem_identificado_o_comando_avisa_a_lista_fixa(self):
        contrato = Contrato.objects.create(
            numero='C-antigo', data_fim=self.hoje + timedelta(days=10))
        _, emails = vencimentos.destinatarios_do_documento(contrato)
        self.assertEqual(emails, ['documentos@db.com.br'])


@override_settings(EMAILS_AVISO_DOCUMENTOS=['documentos@db.com.br'])
class ComandoAvisarVencimentosTest(TestCase):
    """O comando é o que o cron chama; vale garantir que a fiação funciona."""

    def setUp(self):
        self.hoje = date.today()
        Contrato.objects.create(
            numero='C-900', contratado='Fornecedor Y',
            data_fim=self.hoje + timedelta(days=7),
        )
        mail.outbox = []

    def test_dry_run_lista_sem_enviar(self):
        from io import StringIO
        from django.core.management import call_command

        saida = StringIO()
        call_command('avisar_vencimentos', '--dry-run', stdout=saida)

        self.assertIn('C-900' if 'C-900' in saida.getvalue() else 'Fornecedor Y', saida.getvalue())
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(AvisoVencimento.objects.count(), 0)

    def test_execucao_envia_e_a_segunda_nao_repete(self):
        from io import StringIO
        from django.core.management import call_command

        call_command('avisar_vencimentos', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(AvisoVencimento.objects.count(), 1)

        call_command('avisar_vencimentos', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
