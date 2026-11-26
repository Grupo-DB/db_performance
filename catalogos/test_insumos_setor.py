"""26/11/2026 — painéis de Insumos por setor: o gestor monta, o chefe só acompanha os dele."""
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from catalogos import almox_insumos as ins
from catalogos import almoxarifado as a
from catalogos.models import InsumoMonitorado, PainelInsumosSetor

BASE = '/catalogos/erp/almoxarifado/insumos/'


class InsumosSetorTests(TestCase):
    def setUp(self):
        self.gestor = User.objects.create(username='gestor')
        self.gestor.groups.add(Group.objects.get_or_create(name='comprasGestor')[0])
        self.comprador = User.objects.create(username='comprador')
        self.comprador.groups.add(Group.objects.get_or_create(name='comprasComprador')[0])
        self.chefe = User.objects.create(username='chefe', first_name='Chefe', last_name='Moagem')
        self.outro = User.objects.create(username='outro')

    def cli(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c

    def criar(self, nome='Moagem', filial=0, resp=None, **extra):
        r = self.cli(self.gestor).post(f'{BASE}setores/', {'nome': nome, 'filial': filial,
                                       'responsaveis': resp if resp is not None else [self.chefe.id], **extra}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def painel_get(self, u, **params):
        with mock.patch.object(ins, 'painel', side_effect=lambda filial, *a_, qual=None, **k: {
                'itens': [], 'filial_usada': filial, 'painel': f'setor:{qual.pk}' if ins.eh_setor(qual) else qual}), \
                mock.patch.object(a, 'filiais', return_value=[]):
            return self.cli(u).get(BASE, {'dias': 90, **params})

    def test_so_gestor_cria_e_chefe_entra_no_grupo(self):
        self.assertEqual(self.cli(self.comprador).post(f'{BASE}setores/', {'nome': 'X'}, format='json').status_code, 403)
        self.assertEqual(self.cli(self.gestor).post(f'{BASE}setores/', {'nome': ' '}, format='json').status_code, 400)
        p = self.criar()
        self.assertEqual(p['responsaveis'], [{'id': self.chefe.id, 'nome': 'Chefe Moagem'}])
        self.assertTrue(self.chefe.groups.filter(name='comprasChefeSetor').exists())
        # tirar o chefe do painel tira do grupo
        r = self.cli(self.gestor).patch(f"{BASE}setores/{p['id']}/", {'responsaveis': []}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.chefe.groups.filter(name='comprasChefeSetor').exists())

    def test_chefe_em_dois_paineis_continua_no_grupo_ao_apagar_um(self):
        p1, p2 = self.criar('Moagem'), self.criar('Ensaque')
        self.assertEqual(self.cli(self.gestor).delete(f"{BASE}setores/{p1['id']}/").status_code, 204)
        self.assertTrue(self.chefe.groups.filter(name='comprasChefeSetor').exists())
        self.cli(self.gestor).delete(f"{BASE}setores/{p2['id']}/")
        self.assertFalse(self.chefe.groups.filter(name='comprasChefeSetor').exists())

    def test_gestor_monta_e_itens_ficam_separados_do_padrao(self):
        InsumoMonitorado.objects.all().delete()
        InsumoMonitorado.objects.create(tipo='grupo', codigo=1702, filial=0)
        p = self.criar(copiar_padrao=True)
        qual = f"setor:{p['id']}"
        c = self.cli(self.gestor)
        self.assertEqual(c.post(f'{BASE}monitorados/', {'tipo': 'grupo', 'codigo': 1702, 'painel': qual}, format='json').status_code, 200)
        r = c.post(f'{BASE}monitorados/', {'tipo': 'item', 'codigo': 251, 'painel': qual, 'filial': 3}, format='json')
        self.assertEqual(r.status_code, 201)
        setor = PainelInsumosSetor.objects.get(pk=p['id'])
        self.assertEqual(sorted(m['codigo'] for m in ins.monitorados_app(setor=setor)), [251, 1702])
        self.assertEqual(InsumoMonitorado.objects.get(pk=r.data['id']).filial, 0)   # filial do painel, não a mandada
        self.assertEqual([m['codigo'] for m in ins.monitorados_app(0)], [1702])     # padrão intacto
        # chefe não edita
        self.assertEqual(self.cli(self.chefe).delete(f"{BASE}monitorados/{r.data['id']}/", {'painel': qual}).status_code, 403)
        self.assertEqual(c.delete(f"{BASE}monitorados/{r.data['id']}/?painel={qual}").status_code, 204)
        # trocar a filial do painel leva as linhas junto
        c.patch(f"{BASE}setores/{p['id']}/", {'filial': 3}, format='json')
        self.assertEqual(set(setor.monitorados.values_list('filial', flat=True)), {3})

    def test_chefe_ve_so_os_dele(self):
        meu = self.criar('Moagem')
        alheio = self.criar('Ensaque', filial=3, resp=[self.outro.id])
        r = self.painel_get(self.chefe)                      # sem painel pedido: cai no dele
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['painel'], r.data['so_setor']), (f"setor:{meu['id']}", True))
        self.assertEqual([p['id'] for p in r.data['paineis_setor']], [meu['id']])
        self.assertEqual(self.painel_get(self.chefe, painel='padrao').data['painel'], f"setor:{meu['id']}")
        self.assertEqual(self.painel_get(self.chefe, painel=f"setor:{alheio['id']}").status_code, 403)
        # a filial do painel manda, não a da URL
        self.assertEqual(self.painel_get(self.chefe, painel=f"setor:{meu['id']}", filial=5).data['filial_usada'], 0)
        # telas que ele não tem
        self.assertEqual(self.cli(self.chefe).get('/catalogos/erp/almoxarifado/catalogo/opcoes/').status_code, 403)
        self.assertEqual(self.cli(self.chefe).get(f'{BASE}usuarios/').status_code, 403)
        # quem não é chefe nem tem Insumos
        self.assertEqual(self.painel_get(self.outro.__class__.objects.create(username='ninguem')).status_code, 403)

    def test_gestor_ve_todos_e_comprador_segue_com_o_dele(self):
        self.criar('Moagem')
        self.criar('Ensaque', resp=[self.outro.id])
        self.assertEqual(len(self.painel_get(self.gestor).data['paineis_setor']), 2)
        r = self.painel_get(self.comprador)
        self.assertEqual((r.data['painel'], r.data['so_setor'], r.data['paineis_setor']), ('meu', False, []))

    def test_lista_de_usuarios_para_o_gestor(self):
        r = self.cli(self.gestor).get(f'{BASE}usuarios/', {'busca': 'moag'})
        self.assertEqual([u['login'] for u in r.data], ['chefe'])

    def test_serie_do_chefe_so_de_item_do_painel(self):
        import pandas as pd
        meu = self.criar('Moagem', filial=3)
        setor = PainelInsumosSetor.objects.get(pk=meu['id'])
        InsumoMonitorado.objects.create(painel_setor=setor, filial=3, tipo='grupo', codigo=10)
        InsumoMonitorado.objects.create(painel_setor=setor, filial=3, tipo='item', codigo=900)
        df = pd.DataFrame({'ESTQCOD': [1, 2, 900], 'GALM': [11, 20, 20]})          # 11 é filho de 10
        grupos = pd.DataFrame({'GALMCOD': [10, 11, 20], 'GALMNOME': ['A', 'A1', 'B'], 'GALMGALMPAI': [0, 10, 0]})
        url = f'{BASE}serie/%d/'
        with mock.patch.object(a, '_preparado', return_value=(df, {'grupos': grupos}, {})), \
                mock.patch.object(ins, 'serie_item', side_effect=lambda cod, filial, passo: {'filial': filial}):
            c = self.cli(self.chefe)
            q = {'painel': f"setor:{meu['id']}", 'filial': 0}
            r = c.get(url % 1, q)                                       # dentro do subgrupo
            self.assertEqual((r.status_code, r.data['filial']), (200, 3))
            self.assertEqual(c.get(url % 900, q).status_code, 200)      # item avulso
            self.assertEqual(c.get(url % 2, q).status_code, 403)        # fora do painel
            self.assertEqual(c.get(url % 1).status_code, 200)           # sem painel: cai no dele
            self.assertEqual(self.cli(self.outro).get(url % 1, q).status_code, 403)
            self.assertEqual(self.cli(self.gestor).get(url % 2, q).status_code, 200)   # gestor lê tudo
            self.assertEqual(self.cli(self.comprador).get(url % 2).status_code, 200)

    def test_nome_do_colaborador_no_lugar_do_login(self):
        from types import SimpleNamespace
        sem = User.objects.create(username='jose.silva')
        self.assertEqual(ins.nome_usuario(sem), 'jose.silva')               # sem colaborador: o login
        self.assertEqual(ins.nome_usuario(self.chefe), 'Chefe Moagem')      # sem colaborador: nome do usuário
        com = SimpleNamespace(colaborador=SimpleNamespace(nome='José da Silva'), username='jose.silva',
                              get_full_name=lambda: '')
        self.assertEqual(ins.nome_usuario(com), 'José da Silva')
