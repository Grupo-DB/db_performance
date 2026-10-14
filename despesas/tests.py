import shutil
import tempfile

from django.contrib.auth.models import Group, User
from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from .models import Despesa

URL = '/despesas/despesas/'
MEDIA_TESTE = tempfile.mkdtemp(prefix='despesas_teste_')


@override_settings(MEDIA_ROOT=MEDIA_TESTE)
class FluxoDespesasTests(APITestCase):
    """manage.py test despesas --settings=db_performance.test_settings"""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_TESTE, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.gestor = User.objects.create_user('gestor', password='x', first_name='Gina', last_name='Gestora')
        self.gestor.groups.add(Group.objects.get_or_create(name='despesasGestor')[0])
        self.ana = User.objects.create_user('ana', password='x', first_name='Ana', last_name='Souza')
        self.ana.groups.add(Group.objects.get_or_create(name='lancadorDespesas')[0])
        self.beto = User.objects.create_user('beto', password='x', first_name='Beto', last_name='Lima')
        self.beto.groups.add(Group.objects.get_or_create(name='lancadorDespesas')[0])
        self.fora = User.objects.create_user('fora', password='x')

    def lancar(self, user, **dados):
        self.client.force_authenticate(user)
        corpo = {'tipo': 'combustivel', 'data': '2026-10-10', 'valor': '120.50', 'reembolsavel': 'true', **dados}
        return self.client.post(URL, corpo, format='multipart')

    def test_sem_grupo_nao_entra(self):
        self.client.force_authenticate(self.fora)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_lancador_lanca_em_nome_proprio_e_ve_so_as_suas(self):
        r = self.lancar(self.ana, colaborador='Outra Pessoa',
                        novos_anexos=SimpleUploadedFile('nota.png', b'\x89PNG', content_type='image/png'))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['colaborador'], 'Ana Souza')
        self.assertEqual(r.data['status'], 'PENDENTE')
        self.assertEqual(len(r.data['anexos']), 1)
        self.lancar(self.beto)
        self.client.force_authenticate(self.ana)
        self.assertEqual([d['colaborador'] for d in self.client.get(URL).data], ['Ana Souza'])
        self.client.force_authenticate(self.gestor)
        self.assertEqual(len(self.client.get(URL).data), 2)

    def test_lancador_nao_muda_status_por_patch(self):
        d = self.lancar(self.ana).data
        r = self.client.patch(f"{URL}{d['id']}/", {'status': 'LANCADA', 'lancada': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Despesa.objects.get(pk=d['id']).status, 'PENDENTE')

    def test_outros_exige_descricao_e_valor_positivo(self):
        r = self.lancar(self.ana, tipo='outros')
        self.assertIn('descricao', r.data)
        r = self.lancar(self.ana, valor='0')
        self.assertIn('valor', r.data)
        self.assertEqual(self.lancar(self.ana, tipo='outros', descricao='Cópia de chave').status_code, 201)

    def test_fluxo_completo(self):
        d = self.lancar(self.ana).data
        self.client.force_authenticate(self.ana)
        self.assertEqual(self.client.post(f"{URL}{d['id']}/aprovar/").status_code, 403)

        self.client.force_authenticate(self.gestor)
        self.assertEqual(self.client.post(f"{URL}{d['id']}/recusar/", {}).status_code, 400)  # sem motivo
        r = self.client.post(f"{URL}{d['id']}/recusar/", {'motivo': 'Sem nota fiscal'})
        self.assertEqual(r.data['status'], 'RECUSADA')
        self.assertEqual(r.data['aprovado_por'], 'Gina Gestora')

        # Ana corrige a recusada: volta para pendente.
        self.client.force_authenticate(self.ana)
        r = self.client.patch(f"{URL}{d['id']}/", {'valor': '99'}, format='json')
        self.assertEqual(r.data['status'], 'PENDENTE')

        self.client.force_authenticate(self.gestor)
        self.assertEqual(self.client.post(f"{URL}{d['id']}/lancar/").status_code, 400)  # não aprovada
        self.assertEqual(self.client.post(f"{URL}{d['id']}/aprovar/").data['status'], 'APROVADA')
        r = self.client.post(f"{URL}{d['id']}/lancar/")
        self.assertEqual((r.data['status'], r.data['lancada']), ('LANCADA', True))
        r = self.client.post(f"{URL}{d['id']}/reembolsar/")
        self.assertTrue(r.data['reembolsada'])
        self.assertIsNotNone(r.data['reembolsada_em'])

        # Lançada: ninguém edita nem exclui; o gestor reabre se precisar.
        self.assertEqual(self.client.patch(f"{URL}{d['id']}/", {'valor': '1'}, format='json').status_code, 403)
        self.assertEqual(self.client.delete(f"{URL}{d['id']}/").status_code, 403)
        self.assertEqual(self.client.post(f"{URL}{d['id']}/reabrir/").data['status'], 'PENDENTE')

    def test_aprovada_fica_travada_para_o_dono(self):
        d = self.lancar(self.ana).data
        self.client.force_authenticate(self.gestor)
        self.client.post(f"{URL}{d['id']}/aprovar/")
        self.client.force_authenticate(self.ana)
        self.assertEqual(self.client.patch(f"{URL}{d['id']}/", {'valor': '1'}, format='json').status_code, 403)
        self.assertEqual(self.client.delete(f"{URL}{d['id']}/").status_code, 403)

    def test_acao_em_lote(self):
        ids = [self.lancar(self.ana).data['id'], self.lancar(self.beto, reembolsavel='false').data['id']]
        self.client.force_authenticate(self.gestor)
        r = self.client.post(f'{URL}acao-lote/', {'ids': ids, 'acao': 'aprovar'}, format='json')
        self.assertEqual(len(r.data['alteradas']), 2)
        r = self.client.post(f'{URL}acao-lote/', {'ids': ids, 'acao': 'reembolsar'}, format='json')
        self.assertEqual(len(r.data['alteradas']), 1)  # a do Beto não é reembolsável
        self.assertEqual(len(r.data['erros']), 1)

    def test_despesa_antiga_casada_pelo_nome(self):
        Despesa.objects.create(colaborador='Ana Souza', tipo='pedagio', data='2026-05-06', valor=10, lancada=False)
        self.client.force_authenticate(self.ana)
        self.assertEqual(len(self.client.get(URL).data), 1)
        self.client.force_authenticate(self.beto)
        self.assertEqual(len(self.client.get(URL).data), 0)

    def test_perfil(self):
        self.client.force_authenticate(self.gestor)
        self.assertEqual(self.client.get(f'{URL}perfil/').data, {'nome': 'Gina Gestora', 'gestor': True})
        self.client.force_authenticate(self.ana)
        self.assertFalse(self.client.get(f'{URL}perfil/').data['gestor'])

    def test_anexo_so_de_despesa_visivel(self):
        d = self.lancar(self.ana, novos_anexos=SimpleUploadedFile('n.png', b'\x89PNG', content_type='image/png')).data
        anexo = d['anexos'][0]['id']
        self.client.force_authenticate(self.beto)
        self.assertEqual(self.client.delete(f'/despesas/documento-anexos/{anexo}/').status_code, 404)
        self.client.force_authenticate(self.ana)
        self.assertEqual(self.client.delete(f'/despesas/documento-anexos/{anexo}/').status_code, 204)
