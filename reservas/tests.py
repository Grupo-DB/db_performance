from datetime import date, time

from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from .models import Objeto, Reserva


class PermissoesReservasTests(APITestCase):
    """22/10/2026: todos veem a agenda; só a gestão cria, edita e exclui. Sem login, nada."""

    def setUp(self):
        self.objeto = Objeto.objects.create(nome='Sala UniDB', tipo='Sala')
        self.reserva = Reserva.objects.create(objeto='Sala UniDB', data_inicio=date(2026, 10, 22), hora_inicio=time(8),
                                              data_fim=date(2026, 10, 22), hora_fim=time(10), responsavel='Ana')
        self.qualquer = User.objects.create_user('colaborador', password='x')
        self.gestor = User.objects.create_user('gestor', password='x')
        self.gestor.groups.add(Group.objects.create(name='gestorReservas'))
        self.nova = {'objeto': 'Sala UniDB', 'data_inicio': '2026-10-23', 'hora_inicio': '08:00', 'data_fim': '2026-10-23',
                     'hora_fim': '09:00', 'responsavel': 'Bia'}

    def test_sem_login_nao_ve_nem_altera(self):
        self.assertEqual(self.client.get('/reservas/reservas/').status_code, 401)
        self.assertEqual(self.client.post('/reservas/reservas/', self.nova).status_code, 401)
        self.assertEqual(self.client.delete(f'/reservas/reservas/{self.reserva.id}/').status_code, 401)

    def test_qualquer_usuario_ve_mas_nao_altera(self):
        self.client.force_authenticate(self.qualquer)
        self.assertEqual(len(self.client.get('/reservas/reservas/').data), 1)
        self.assertEqual(len(self.client.get('/reservas/objetos/').data), 1)
        self.assertEqual(self.client.post('/reservas/reservas/', self.nova).status_code, 403)
        self.assertEqual(self.client.patch(f'/reservas/reservas/{self.reserva.id}/', {'responsavel': 'X'}).status_code, 403)
        self.assertEqual(self.client.delete(f'/reservas/reservas/{self.reserva.id}/').status_code, 403)
        self.assertEqual(self.client.post('/reservas/objetos/', {'nome': 'Carro', 'tipo': 'Automóvel'}).status_code, 403)
        self.assertTrue(Reserva.objects.filter(pk=self.reserva.id, responsavel='Ana').exists())

    def test_gestao_continua_criando_editando_e_excluindo(self):
        self.client.force_authenticate(self.gestor)
        self.assertEqual(self.client.post('/reservas/reservas/', self.nova).status_code, 201)
        self.assertEqual(self.client.patch(f'/reservas/reservas/{self.reserva.id}/', {'responsavel': 'Ana Paula'}).status_code, 200)
        self.assertEqual(self.client.delete(f'/reservas/reservas/{self.reserva.id}/').status_code, 204)
