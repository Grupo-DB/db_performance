"""Testes do F-018.1 (ficha de entrevista do ex funcionário)."""
from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from recrutamento.models import Candidato, FichaEntrevista


class FichaExFuncionarioTest(APITestCase):
    def setUp(self):
        self.candidato = Candidato.objects.create(nome='FULANO DE TAL')
        self.client.force_authenticate(User.objects.create_superuser('rh', 'rh@db.com.br', 'x'))

    def test_ficha_nova_e_padrao(self):
        ficha = FichaEntrevista.objects.create(candidato=self.candidato)
        self.assertEqual(ficha.modelo, FichaEntrevista.MODELO_PADRAO)

    def test_avaliacao_em_tres_niveis_alimenta_o_booleano(self):
        casos = {'ATENDE': True, 'NAO_ATENDE': False, 'PARCIAL': None, '': None}
        for avaliacao, esperado in casos.items():
            ficha = FichaEntrevista.objects.create(
                candidato=self.candidato, modelo=FichaEntrevista.MODELO_EX_FUNCIONARIO,
                avaliacao_requisitos=avaliacao, atende_requisitos=True,
            )
            self.assertIs(ficha.atende_requisitos, esperado, avaliacao)

    def test_ficha_padrao_nao_mexe_no_booleano(self):
        ficha = FichaEntrevista.objects.create(candidato=self.candidato, atende_requisitos=True)
        self.assertIs(ficha.atende_requisitos, True)

    def test_api_grava_respostas_e_filtra_por_modelo(self):
        resposta = self.client.post('/recrutamento/fichas/', {
            'candidato': self.candidato.id,
            'modelo': 'EX_FUNCIONARIO',
            'resultado': 'PRE_SEL_FUTURO',
            'avaliacao_requisitos': 'PARCIAL',
            'respostas_ex_funcionario': {
                'ultima_experiencia': 'Operador de britagem',
                'competencias': ['Liderança', 'Segurança'],
            },
        }, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        ficha = FichaEntrevista.objects.get(pk=resposta.data['id'])
        self.assertEqual(ficha.respostas_ex_funcionario['competencias'], ['Liderança', 'Segurança'])
        self.assertIsNone(ficha.atende_requisitos)

        FichaEntrevista.objects.create(candidato=self.candidato)
        lista = self.client.get('/recrutamento/fichas/', {'modelo': 'EX_FUNCIONARIO'})
        linhas = lista.data['results'] if isinstance(lista.data, dict) else lista.data
        self.assertEqual([f['id'] for f in linhas], [ficha.id])
        self.assertEqual(linhas[0]['modelo'], 'EX_FUNCIONARIO')
