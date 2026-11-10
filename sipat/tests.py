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

    def test_so_presentes_no_turno_do_sorteio(self):
        from datetime import timedelta
        from django.utils import timezone
        hoje = timezone.localdate()
        self._importar([{'nome': 'Manhã'}, {'nome': 'Tarde'}, {'nome': 'Ontem'}])
        manha, tarde, ontem = Participante.objects.order_by('id')
        Presenca.objects.create(participante=manha, data=hoje, turno='M')
        Presenca.objects.create(participante=tarde, data=hoje, turno='T')
        Presenca.objects.create(participante=ontem, data=hoje - timedelta(days=1), turno='T')
        premio = Premio.objects.create(evento=self.evento, descricao='Kit', regra='QUALQUER',
                                       quantidade=2, so_presentes_no_turno=True)

        self.assertEqual(self.client.get(f'/sipat/premios/{premio.id}/concorrentes/?turno=T').data['total'], 1)
        self.assertEqual(self.client.get(f'/sipat/premios/{premio.id}/concorrentes/').data['total'], 0)
        self.assertEqual(self.client.post(f'/sipat/premios/{premio.id}/sortear/').status_code, 400)

        r = self.client.post(f'/sipat/premios/{premio.id}/sortear/', {'turno': 'T'}, format='json')
        self.assertEqual(r.data['sorteio']['participante'], tarde.id)
        r = self.client.post(f'/sipat/premios/{premio.id}/sortear/', {'turno': 'T'}, format='json')
        self.assertEqual(r.status_code, 400)  # quem esteve só de manhã ou ontem não entra
        self.assertIn('tarde', r.data['detail'])

        # Desligado, volta a valer só a regra do prêmio.
        premio.so_presentes_no_turno = False
        premio.save()
        self.assertEqual(self.client.get(f'/sipat/premios/{premio.id}/concorrentes/').data['total'], 2)

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

    def test_ganhador_do_dia_concorre_na_semana(self):
        """06/11: prêmio do dia não tira ninguém do sorteio da semana; o contrário continua tirando."""
        self._importar([{'nome': 'A'}, {'nome': 'B'}])
        a, b = Participante.objects.order_by('id')
        for d in self.evento.dias:
            for p in (a, b):
                Presenca.objects.create(participante=p, data=d, turno='M')
        dia = Premio.objects.create(evento=self.evento, descricao='Caneca', regra='QUALQUER', quantidade=1)
        r = self.client.post(f'/sipat/premios/{dia.id}/sortear/')
        ganhou_dia = r.data['sorteio']['participante']

        tv = Premio.objects.create(evento=self.evento, descricao='TV', categoria='MAIOR', regra='SEMANA', quantidade=2)
        self.assertEqual(self.client.get(f'/sipat/premios/{tv.id}/concorrentes/').data['total'], 2)
        ganhou_tv = {self.client.post(f'/sipat/premios/{tv.id}/sortear/').data['sorteio']['participante'] for _ in range(2)}
        self.assertEqual(ganhou_tv, {a.id, b.id})   # inclusive quem já levou a caneca

        # Quem ganhou TV não concorre a outro prêmio do dia (os dois ganharam: urna vazia).
        outro = Premio.objects.create(evento=self.evento, descricao='Boné', regra='QUALQUER', quantidade=1)
        self.assertEqual(self.client.get(f'/sipat/premios/{outro.id}/concorrentes/').data['total'], 0)
        r = self.client.get(f'/sipat/participantes/{ganhou_dia}/')
        self.assertEqual(len(r.data['sorteios']), 2)

    def test_semana_inteira_e_presente_no_turno_do_sorteio(self):
        """06/11: semana inteira + "só presentes no turno" = veio todos os dias E está no turno sorteado."""
        self._importar([{'nome': 'Semana e tarde'}, {'nome': 'Semana só manhã'}, {'nome': 'Só hoje à tarde'}])
        a, b, c = Participante.objects.order_by('id')
        hoje = self.evento.dias[-1]
        for d in self.evento.dias:
            Presenca.objects.create(participante=a, data=d, turno='M')
            Presenca.objects.create(participante=b, data=d, turno='M')
        Presenca.objects.create(participante=a, data=hoje, turno='T')
        Presenca.objects.create(participante=c, data=hoje, turno='T')
        tv = Premio.objects.create(evento=self.evento, descricao='TV', categoria='MAIOR', regra='SEMANA',
                                   so_presentes_no_turno=True)
        r = self.client.get(f'/sipat/premios/{tv.id}/concorrentes/', {'turno': 'T', 'data': hoje, 'lista': 1})
        self.assertEqual([x['nome'] for x in r.data['lista']], ['Semana e tarde'])
        r = self.client.get(f'/sipat/premios/{tv.id}/concorrentes/', {'turno': 'M', 'data': hoje})
        self.assertEqual(r.data['total'], 2)

    def test_data_manual_e_lista_de_concorrentes(self):
        self._importar([{'nome': 'Zé', 'matricula': '7'}, {'nome': 'Ana'}])
        ze, ana = Participante.objects.order_by('id')
        dia = self.evento.dias[2]
        Presenca.objects.create(participante=ze, data=dia, turno='T')
        Presenca.objects.create(participante=ana, data=self.evento.dias[0], turno='T')
        premio = Premio.objects.create(evento=self.evento, descricao='Kit', regra='QUALQUER', so_presentes_no_turno=True)
        url = f'/sipat/premios/{premio.id}/concorrentes/'

        r = self.client.get(url, {'turno': 'T', 'data': dia, 'lista': 1})
        self.assertEqual(r.data['total'], 1)
        self.assertEqual(r.data['lista'][0]['nome'], 'Zé')
        self.assertEqual(r.data['lista'][0]['matricula'], '7')
        self.assertNotIn('lista', self.client.get(url, {'turno': 'T', 'data': dia}).data)
        self.assertEqual(self.client.get(url, {'turno': 'T', 'data': 'xx'}).status_code, 400)

        r = self.client.post(f'/sipat/premios/{premio.id}/sortear/', {'turno': 'T', 'data': self.evento.dias[0]}, format='json')
        self.assertEqual(r.data['sorteio']['participante'], ana.id)
