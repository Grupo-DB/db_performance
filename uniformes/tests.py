from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from aprendizes.tests import criar_colaborador

from .models import Campanha, ItemPedido, Peca, Pedido
from .regras import ler_celula, ler_entrega


class UniformesTests(APITestCase):
    def setUp(self):
        u = User.objects.create_user('rh', password='x')
        u.groups.add(Group.objects.create(name='RHGestor'))
        self.client.force_authenticate(u)
        r = self.client.post('/uniformes/campanhas/', {'nome': 'Inverno/2026', 'ano': 2026}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.campanha = Campanha.objects.get()
        self.pecas = {str(p): p for p in self.campanha.pecas.all()}

    def test_campanha_nasce_com_catalogo_e_regras(self):
        self.assertEqual(len(self.pecas), 5)
        sueter_f = self.pecas['Suéter (Feminino)']
        self.assertEqual(sueter_f.preco_do_tamanho('M'), Decimal('166.00'))
        self.assertEqual(sueter_f.preco_do_tamanho('EX4'), Decimal('187'))
        self.assertIn('3 vezes', self.campanha.regras)

    def test_celula_e_entrega_da_planilha(self):
        self.assertEqual(ler_celula('1 (P)'), (1, 'P'))
        self.assertEqual(ler_celula('2 (GG)'), (2, 'GG'))
        self.assertEqual(ler_celula('1(M)'), (1, 'M'))
        self.assertEqual(ler_celula('1 (PP )'), (1, 'PP'))
        self.assertIsNone(ler_celula('-'))
        self.assertEqual(ler_entrega('2026-07-22 00:00:00'), (True, date(2026, 7, 22), ''))
        self.assertEqual(ler_entrega('Jak levou')[:2], (True, None))
        self.assertEqual(ler_entrega('DEMITIDO'), (False, None, 'Demitido'))

    def test_compra_soma_por_tamanho_e_divide_parcelas(self):
        r = self.client.post('/uniformes/pedidos/', {
            'campanha': self.campanha.id, 'nome': 'Joana', 'genero': 'F', 'modalidade': 'COMPRA', 'parcelas': 3,
            'itens': [
                {'peca': self.pecas['Suéter (Feminino)'].id, 'quantidade': 1, 'tamanho': 'ex2'},
                {'peca': self.pecas['Soft'].id, 'quantidade': 1, 'tamanho': 'M', 'ziper': 'MEIO'},
            ],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(str(r.data['valor_total'])), Decimal('319.00'))
        self.assertEqual(Decimal(str(r.data['valor_parcela'])), Decimal('106.33'))
        self.assertEqual(r.data['itens'][0]['tamanho'], 'EX2')

    def test_alertas_de_quem_ganha(self):
        c = criar_colaborador('Carlos', cargo_nome='Gerente Comercial')
        r = self.client.post('/uniformes/pedidos/', {
            'campanha': self.campanha.id, 'nome': 'Carlos', 'colaborador': c.id, 'cargo': 'Gerente Comercial',
            'genero': 'M', 'modalidade': 'GANHA',
            'itens': [
                {'peca': self.pecas['Camisa'].id, 'quantidade': 3, 'tamanho': 'G'},
                {'peca': self.pecas['Jaqueta'].id, 'quantidade': 1, 'tamanho': 'G'},
                {'peca': self.pecas['Soft'].id, 'quantidade': 1, 'tamanho': 'G'},
            ],
        }, format='json')
        self.assertEqual(r.data['valor_total'], 0)
        self.assertEqual(len(r.data['alertas']), 3, r.data['alertas'])

    def test_editar_itens_e_entregar(self):
        p = Pedido.objects.create(campanha=self.campanha, nome='Rui', genero='M', modalidade='GANHA')
        i = ItemPedido.objects.create(pedido=p, peca=self.pecas['Camisa'], quantidade=2, tamanho='M')
        r = self.client.patch(f'/uniformes/pedidos/{p.id}/', {'itens': [
            {'id': i.id, 'peca': self.pecas['Camisa'].id, 'quantidade': 2, 'tamanho': 'G'},
            {'peca': self.pecas['Jaqueta'].id, 'quantidade': 1, 'tamanho': 'G'},
        ]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['itens_pendentes'], 2)
        r = self.client.post(f'/uniformes/pedidos/{p.id}/entregar/', {}, format='json')
        self.assertEqual(r.data['itens_pendentes'], 0)
        resumo = self.client.get(f'/uniformes/campanhas/{self.campanha.id}/resumo/').data
        self.assertEqual(resumo['itens_pendentes'], 0)
        self.assertEqual({g['peca']: g['por_tamanho'] for g in resumo['grade']}, {'Jaqueta': {'G': 1}, 'Camisa': {'G': 2}})

    def test_importar_abas(self):
        linhas = [
            {'aba': 'FEMININOSCOMPRA', 'nome': 'Ana Paula Dilhe Leal', 'cpf': '032.988.450-60', 'setor': 'RH',
             'jaqueta': '1 (M)', 'sueter': '-', 'camisa': '-', 'soft': '1 (PP )', 'ziper': 'Todo',
             'entrega': '2026-07-22 00:00:00', 'entrega_jaqueta': '2026-08-12 00:00:00'},
            {'aba': 'MASCULINOSGANHA', 'nome': 'Agner Loreto', 'jaqueta': '1 (P)', 'camisa': '2 (P)', 'entrega': 'Jak levou'},
            {'aba': 'MASCULINOSCOMPRA', 'nome': 'Daniel Torres', 'camisa': '1 (P)', 'soft': '1 (M)', 'ziper': 'Meio',
             'entrega': '2026-07-22', 'jaqueta': '1 (G)'},
        ]
        r = self.client.post(f'/uniformes/campanhas/{self.campanha.id}/importar/', {'linhas': linhas}, format='json')
        self.assertEqual(r.data['criados'], 3, r.data)
        ana = Pedido.objects.get(nome='Ana Paula Dilhe Leal')
        self.assertEqual((ana.genero, ana.modalidade), ('F', 'COMPRA'))
        jaqueta = ana.itens.get(peca__nome='Jaqueta')
        self.assertEqual(jaqueta.entregue_em, date(2026, 8, 12))
        self.assertEqual(ana.itens.get(peca__nome='Soft').ziper, 'TODO')
        agner = Pedido.objects.get(nome='Agner Loreto')
        self.assertTrue(all(i.entregue and i.entrega_obs == 'Jak levou' for i in agner.itens.all()))
        daniel = Pedido.objects.get(nome='Daniel Torres')
        self.assertFalse(daniel.itens.get(peca__nome='Jaqueta').entregue)  # a jaqueta veio depois
        self.assertTrue(daniel.itens.get(peca__nome='Soft').entregue)
        r = self.client.post(f'/uniformes/campanhas/{self.campanha.id}/importar/', {'linhas': linhas}, format='json')
        self.assertEqual((r.data['criados'], r.data['atualizados']), (0, 3))
        self.assertEqual(ItemPedido.objects.count(), 7)
