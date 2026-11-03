from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import AvaliacaoTreinamento, ConviteAvaliacaoTreinamento, Curso, Turma

RESPOSTA = {
    'avaliacao_geral': 'EXCELENTE', 'conteudo_atendeu': 'SIM', 'didatica_instrutor': 'BOM',
    'material_apoio': 'PARCIALMENTE', 'tempo_duracao': 'MUITO CURTO',
    'pontos_positivos': 'Prática na máquina', 'pontos_melhoria': '',
}


class ConviteAvaliacaoTests(APITestCase):
    def setUp(self):
        self.rh = User.objects.create_user('rh', password='x')
        self.rh.groups.add(Group.objects.create(name='RHGestor'))
        curso = Curso.objects.create(nome='NR-12')
        self.turma = Turma.objects.create(curso=curso, instrutor='Fulano', data_inicial=date(2026, 11, 3),
                                          data_final=date(2026, 11, 4))

    def _convite(self):
        self.client.force_authenticate(self.rh)
        r = self.client.post('/unidb/avaliacao/convites/', {'turma': self.turma.id}, format='json')
        self.client.force_authenticate(None)
        self.assertIn(r.status_code, (200, 201), r.data)
        return r.data

    def test_link_da_turma_aceita_varias_respostas_anonimas(self):
        c = self._convite()
        url = f"/unidb/publico/avaliacao/{c['token']}/"
        g = self.client.get(url)
        self.assertEqual((g.status_code, g.data['fechado'], g.data['curso']), (200, False, 'NR-12'))
        self.assertEqual(len(g.data['perguntas']), 5)
        for _ in range(3):
            self.assertEqual(self.client.post(url, RESPOSTA, format='json').status_code, 201)
        av = AvaliacaoTreinamento.objects.filter(turma=self.turma)
        self.assertEqual(av.count(), 3)
        primeira = av.first()
        self.assertEqual((primeira.nome_treinamento, primeira.instrutor, primeira.data_conclusao, primeira.pontos_melhoria),
                         ('NR-12', 'Fulano', date(2026, 11, 4), None))
        self.client.force_authenticate(self.rh)
        lista = self.client.get(f'/unidb/avaliacao/convites/?turma={self.turma.id}').data
        self.assertEqual(lista[0]['respostas'], 3)

    def test_fechadas_sao_obrigatorias_e_valor_fora_da_escala_recusa(self):
        url = f"/unidb/publico/avaliacao/{self._convite()['token']}/"
        incompleta = {**RESPOSTA}
        incompleta.pop('tempo_duracao')
        self.assertEqual(self.client.post(url, incompleta, format='json').status_code, 400)
        self.assertEqual(self.client.post(url, {**RESPOSTA, 'avaliacao_geral': 'OTIMO'}, format='json').status_code, 400)
        self.assertFalse(AvaliacaoTreinamento.objects.exists())

    def test_gerar_de_novo_devolve_o_mesmo_link_aberto(self):
        a, b = self._convite(), self._convite()
        self.assertEqual(a['token'], b['token'])
        self.assertEqual(ConviteAvaliacaoTreinamento.objects.count(), 1)

    def test_cancelado_e_vencido_fecham_e_token_errado_some(self):
        c = self._convite()
        self.client.force_authenticate(self.rh)
        self.client.post(f"/unidb/avaliacao/convites/{c['id']}/cancelar/")
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f"/unidb/publico/avaliacao/{c['token']}/").data['situacao'], 'CANCELADO')
        c2 = self._convite()
        self.assertNotEqual(c['token'], c2['token'])   # cancelado não é reaproveitado
        ConviteAvaliacaoTreinamento.objects.filter(pk=c2['id']).update(expira_em=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.post(f"/unidb/publico/avaliacao/{c2['token']}/", RESPOSTA, format='json').status_code, 400)
        self.assertEqual(self.client.get('/unidb/publico/avaliacao/naoexiste/').status_code, 404)

    def test_convites_so_o_rh(self):
        self.assertEqual(self.client.get('/unidb/avaliacao/convites/').status_code, 401)
        self.client.force_authenticate(User.objects.create_user('outro', password='x'))
        self.assertEqual(self.client.post('/unidb/avaliacao/convites/', {'turma': self.turma.id}, format='json').status_code, 403)
