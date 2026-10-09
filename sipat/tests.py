from datetime import date

from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from .models import Evento, Participante, Premio, Presenca, Sorteio


class SorteioSipatTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('org', password='x')
        self.user.groups.add(Group.objects.create(name='Sipat'))
        self.client.force_authenticate(self.user)
        r = self.client.post('/sipat/eventos/', {
            'nome': '27ª SIPATMIN', 'data_inicio': '2026-10-19', 'data_fim': '2026-10-23',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.evento = Evento.objects.get(pk=r.data['id'])
        self.assertEqual(len(self.evento.dias), 5)

    def _importar(self, linhas):
        return self.client.post(f'/sipat/eventos/{self.evento.id}/importar/', {'linhas': linhas}, format='json')

    def test_importa_e_reimporta_sem_duplicar(self):
        r = self._importar([{'matricula': 10.0, 'nome': 'Ana'}, {'nome': 'José Silva'}, {'nome': ''}])
        self.assertEqual((r.data['criados'], r.data['ignorados']), (2, 1))
        r = self._importar([{'matricula': '10', 'nome': 'Ana', 'setor': 'Britagem'}, {'nome': 'JOSE  SILVA'}])
        self.assertEqual((r.data['criados'], r.data['atualizados']), (0, 1))
        self.assertEqual(Participante.objects.get(matricula='10').setor, 'Britagem')

    def test_premio_maior_so_semana_inteira_e_sorteado_sai_da_urna(self):
        self._importar([{'matricula': str(i), 'nome': f'P{i}'} for i in range(1, 5)])
        p1, p2, p3, _ = Participante.objects.order_by('id')
        for d in self.evento.dias:  # P1 manhã todo dia; P2 alterna turnos todo dia
            Presenca.objects.create(participante=p1, data=d, turno='M')
            Presenca.objects.create(participante=p2, data=d, turno='T' if d.endswith(('0', '2')) else 'M')
        for d in self.evento.dias[:4]:  # P3 faltou um dia
            Presenca.objects.create(participante=p3, data=d, turno='M')

        maior = Premio.objects.create(evento=self.evento, descricao='TV', categoria='MAIOR',
                                      regra='SEMANA', quantidade=3)
        r = self.client.get(f'/sipat/premios/{maior.id}/concorrentes/')
        self.assertEqual(r.data['total'], 2)

        ganhadores = set()
        for _ in range(2):
            r = self.client.post(f'/sipat/premios/{maior.id}/sortear/')
            self.assertEqual(r.status_code, 201, r.data)
            ganhadores.add(r.data['sorteio']['participante'])
        self.assertEqual(ganhadores, {p1.id, p2.id})
        r = self.client.post(f'/sipat/premios/{maior.id}/sortear/')
        self.assertEqual(r.status_code, 400)  # urna vazia: os dois já saíram

        menor = Premio.objects.create(evento=self.evento, descricao='Caneca', regra='QUALQUER', quantidade=1)
        r = self.client.post(f'/sipat/premios/{menor.id}/sortear/')
        self.assertEqual(r.data['sorteio']['participante'], p3.id)
        r = self.client.post(f'/sipat/premios/{menor.id}/sortear/')
        self.assertEqual(r.status_code, 400)  # quantidade esgotada

    def test_regra_dia_turno_e_ausente_libera_unidade(self):
        self._importar([{'nome': 'A'}, {'nome': 'B'}])
        a, b = Participante.objects.order_by('id')
        dia = self.evento.dias[1]
        Presenca.objects.create(participante=a, data=dia, turno='M')
        Presenca.objects.create(participante=b, data=dia, turno='T')
        premio = Premio.objects.create(evento=self.evento, descricao='Kit', regra='DIA',
                                       data=date.fromisoformat(dia), turno='T')
        r = self.client.post(f'/sipat/premios/{premio.id}/sortear/')
        self.assertEqual(r.data['sorteio']['participante'], b.id)
        self.client.post(f"/sipat/sorteios/{r.data['sorteio']['id']}/ausente/")
        self.assertEqual(r.data['premio']['restantes'], 0)
        r = self.client.post(f'/sipat/premios/{premio.id}/sortear/')
        self.assertEqual(r.status_code, 400)  # B continua fora e A é da manhã

    def test_presenca_marca_desmarca_e_valida_dia(self):
        self._importar([{'nome': 'A'}])
        a = Participante.objects.get()
        url = f'/sipat/participantes/{a.id}/presenca/'
        r = self.client.post(url, {'data': self.evento.dias[0], 'turno': 'M'}, format='json')
        self.assertEqual(r.data['presencas'], [f'{self.evento.dias[0]}|M'])
        r = self.client.post(url, {'data': self.evento.dias[0], 'turno': 'M', 'presente': False}, format='json')
        self.assertEqual(r.data['presencas'], [])
        r = self.client.post(url, {'data': '2026-10-24', 'turno': 'M'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_sem_grupo_nao_acessa(self):
        self.client.force_authenticate(User.objects.create_user('x', password='x'))
        self.assertEqual(self.client.get('/sipat/eventos/').status_code, 403)
