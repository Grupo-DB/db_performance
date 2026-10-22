"""Filtro "Recebido em" do banco de talentos (22/10/2026)."""
from datetime import date
from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase
from recrutamento.models import Candidato


class RecebidoEmTests(APITestCase):
    def test_filtra_por_intervalo_de_recebimento(self):
        u = User.objects.create_user('rh', password='x')
        u.groups.add(Group.objects.get_or_create(name='RHGestor')[0])
        self.client.force_authenticate(u)
        Candidato.objects.create(nome='A', data_recebimento=date(2026, 9, 1))
        Candidato.objects.create(nome='B', data_recebimento=date(2026, 10, 10))
        Candidato.objects.create(nome='C', data_recebimento=date(2026, 10, 22))
        Candidato.objects.create(nome='D')
        nomes = lambda q: sorted(c['nome'] for c in self.client.get('/recrutamento/candidatos/' + q).data)
        self.assertEqual(nomes('?recebido_de=2026-10-01&recebido_ate=2026-10-22'), ['B', 'C'])
        self.assertEqual(nomes('?recebido_de=2026-10-11'), ['C'])
        self.assertEqual(nomes('?recebido_ate=2026-09-30'), ['A'])
        self.assertEqual(nomes('?recebido_de=lixo'), ['A', 'B', 'C', 'D'])
