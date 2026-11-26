"""26/11/2026 — acesso por tela do Suprimentos (gestor, comprador, almoxarife, pesada)."""
from types import SimpleNamespace

from django.contrib.auth.models import Group, User
from django.test import TestCase

from catalogos.views import _almox_acesso

TELAS = ('visao', 'indicadores', 'catalogo', 'insumos')
ESPERADO = {
    'comprasGestor': {'visao', 'indicadores', 'catalogo', 'insumos'},
    'comprasComprador': {'visao', 'catalogo', 'insumos'},
    'comprasAlmoxarife': {'visao', 'catalogo'},
    'comprasPesada': {'catalogo'},
    'outroGrupo': set(),
}


class SuprimentosGruposTests(TestCase):
    def _req(self, grupo):
        u = User.objects.create_user(username=f'u_{grupo}', password='x')
        u.groups.add(Group.objects.get_or_create(name=grupo)[0])
        return SimpleNamespace(user=u)

    def test_migration_cria_os_grupos(self):
        import importlib
        from django.apps import apps
        mig = importlib.import_module('catalogos.migrations.0014_grupos_suprimentos')
        mig.criar(apps, None)
        mig.criar(apps, None)  # de novo não duplica
        for nome in ('comprasGestor', 'comprasComprador', 'comprasAlmoxarife', 'comprasPesada'):
            self.assertTrue(Group.objects.filter(name=nome).exists(), nome)

    def test_telas_por_grupo(self):
        for grupo, telas in ESPERADO.items():
            req = self._req(grupo)
            for tela in TELAS:
                pode = _almox_acesso(req, tela=tela) is None
                self.assertEqual(pode, tela in telas, f'{grupo} × {tela}')

    def test_so_gestor_edita(self):
        for grupo in ESPERADO:
            pode = _almox_acesso(self._req(grupo), editar=True) is None
            self.assertEqual(pode, grupo == 'comprasGestor', grupo)

    def test_foto_vale_para_quem_tem_qualquer_tela(self):
        self.assertIsNone(_almox_acesso(self._req('comprasPesada')))
        self.assertIsNotNone(_almox_acesso(self._req('outroGrupo')))
