"""Testes do fluxo de aprovação de contratos (paralelo e sequencial)."""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase

from gestaoDocumentos import aprovacoes
from gestaoDocumentos.models import Contrato, DocumentoNotificacao


def _sincrono(funcao, *args):
    """Substitui a thread do e-mail por execução direta, para o teste ver o resultado."""
    funcao(*args)


@patch.object(aprovacoes, '_em_segundo_plano', _sincrono)
class FluxoAprovacaoTest(TestCase):
    def setUp(self):
        self.autor = User.objects.create_user('autor', 'autor@db.com.br', 'x')
        self.ana   = User.objects.create_user('ana', 'ana@db.com.br', 'x')
        self.bruno = User.objects.create_user('bruno', 'bruno@db.com.br', 'x')
        self.carla = User.objects.create_user('carla', 'carla@db.com.br', 'x')
        self.contrato = Contrato.objects.create(
            numero='C-001', objeto_contrato='Locação de empilhadeira',
            contratado='Fornecedor X', criado_por=self.autor,
        )
        mail.outbox = []

    # ── Paralelo ────────────────────────────────────────────────────────────

    def test_paralelo_aciona_todos_de_uma_vez(self):
        aprovacoes.iniciar_fluxo(self.contrato, [self.ana.id, self.bruno.id], 'PARALELO')
        self.contrato.refresh_from_db()

        self.assertEqual(self.contrato.situacao_aprovacao, 'PENDENTE')
        self.assertEqual(self.contrato.aprovacoes.filter(notificado_em__isnull=False).count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('/gestaoDocumentos/gestaoDocumentos?aprovacao=', mail.outbox[0].alternatives[0][0])

    def test_paralelo_so_aprova_no_ultimo(self):
        aprovacoes.iniciar_fluxo(self.contrato, [self.ana.id, self.bruno.id], 'PARALELO')

        aprovacoes.registrar_decisao(self.contrato, self.ana, True, 'De acordo')
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.situacao_aprovacao, 'PENDENTE')

        aprovacoes.registrar_decisao(self.contrato, self.bruno, True)
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.situacao_aprovacao, 'APROVADO')

    # ── Sequencial ──────────────────────────────────────────────────────────

    def test_sequencial_aciona_um_de_cada_vez(self):
        aprovacoes.iniciar_fluxo(
            self.contrato, [self.ana.id, self.bruno.id, self.carla.id], 'SEQUENCIAL')

        notificados = self.contrato.aprovacoes.filter(notificado_em__isnull=False)
        self.assertEqual([a.aprovador_id for a in notificados], [self.ana.id])
        self.assertEqual(len(mail.outbox), 1)

        aprovacoes.registrar_decisao(self.contrato, self.ana, True)
        notificados = self.contrato.aprovacoes.filter(notificado_em__isnull=False)
        self.assertEqual(
            sorted(a.aprovador_id for a in notificados), sorted([self.ana.id, self.bruno.id]))

    def test_sequencial_barra_quem_fura_a_fila(self):
        aprovacoes.iniciar_fluxo(self.contrato, [self.ana.id, self.bruno.id], 'SEQUENCIAL')
        with self.assertRaises(aprovacoes.ErroAprovacao):
            aprovacoes.registrar_decisao(self.contrato, self.bruno, True)

    def test_paralelo_nao_tem_vez(self):
        aprovacoes.iniciar_fluxo(self.contrato, [self.ana.id, self.bruno.id], 'PARALELO')
        aprovacoes.registrar_decisao(self.contrato, self.bruno, True)  # não levanta

    # ── Reprovação e regras gerais ──────────────────────────────────────────

    def test_reprovacao_encerra_o_fluxo(self):
        aprovacoes.iniciar_fluxo(self.contrato, [self.ana.id, self.bruno.id], 'PARALELO')
        mail.outbox = []

        aprovacoes.registrar_decisao(self.contrato, self.ana, False, 'Valor acima do orçado')
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.situacao_aprovacao, 'REPROVADO')

        with self.assertRaises(aprovacoes.ErroAprovacao):
            aprovacoes.registrar_decisao(self.contrato, self.bruno, True)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Reprovado', mail.outbox[0].subject)
        self.assertIn(self.autor.email, mail.outbox[0].to)

    def test_quem_nao_e_aprovador_nao_decide(self):
        aprovacoes.iniciar_fluxo(self.contrato, [self.ana.id], 'PARALELO')
        with self.assertRaises(aprovacoes.ErroAprovacao):
            aprovacoes.registrar_decisao(self.contrato, self.carla, True)

    def test_nao_decide_duas_vezes(self):
        aprovacoes.iniciar_fluxo(self.contrato, [self.ana.id, self.bruno.id], 'PARALELO')
        aprovacoes.registrar_decisao(self.contrato, self.ana, True)
        with self.assertRaises(aprovacoes.ErroAprovacao):
            aprovacoes.registrar_decisao(self.contrato, self.ana, True)

    def test_aprovadores_repetidos_viram_um(self):
        criadas = aprovacoes.iniciar_fluxo(
            self.contrato, [self.ana.id, self.ana.id, self.bruno.id], 'PARALELO')
        self.assertEqual(len(criadas), 2)

    # ── Pendências e sino ───────────────────────────────────────────────────

    def test_pendentes_de_respeita_a_vez_no_sequencial(self):
        aprovacoes.iniciar_fluxo(self.contrato, [self.ana.id, self.bruno.id], 'SEQUENCIAL')
        self.assertEqual(len(aprovacoes.pendentes_de(self.ana)), 1)
        self.assertEqual(len(aprovacoes.pendentes_de(self.bruno)), 0)

        aprovacoes.registrar_decisao(self.contrato, self.ana, True)
        self.assertEqual(len(aprovacoes.pendentes_de(self.bruno)), 1)

    def test_notificacoes_chegam_para_o_sino(self):
        aprovacoes.iniciar_fluxo(self.contrato, [self.ana.id], 'PARALELO')
        self.assertEqual(
            DocumentoNotificacao.objects.filter(
                usuario_notificado=self.ana, tipo='APROVACAO_SOLICITADA').count(), 1)

        aprovacoes.registrar_decisao(self.contrato, self.ana, True)
        self.assertEqual(
            DocumentoNotificacao.objects.filter(
                usuario_notificado=self.autor, tipo='APROVACAO_CONCLUIDA').count(), 1)
