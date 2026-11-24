from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient


class AcessoBiComercialTests(TestCase):
    """Módulo BI separado dos pedidos (24/11/2026): só Admin, Master e comercialBI."""

    def cliente(self, grupo=None):
        u = User.objects.create_user(f'u_{grupo}', password='x')
        if grupo:
            u.groups.add(Group.objects.get_or_create(name=grupo)[0])
        c = APIClient()
        c.force_authenticate(u)
        return c

    @mock.patch('biComercial.comercial.painel', return_value={'ok': True})
    @mock.patch('biComercial.comercial.saldo', return_value={'ok': True})
    def test_grupos(self, _saldo, _painel):
        for grupo, esperado in (('comercialBI', 200), ('Master', 200), ('Admin', 200), ('vendasGestao', 403), (None, 403)):
            c = self.cliente(grupo)
            self.assertEqual(c.get('/bi/comercial/').status_code, esperado, grupo)
            self.assertEqual(c.get('/bi/comercial/saldo-pedidos/').status_code, esperado, grupo)
        self.assertEqual(APIClient().get('/bi/comercial/').status_code in (401, 403), True)
