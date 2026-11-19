from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from . import regras
from .models import Contato, Cotacao, Produtor, VendedorAgro

PRODUTOS = [{'cod': 1, 'descricao': 'CALCARIO AGRICOLA GRANEL', 'unidade': 'TN', 'preco_padrao': 92.0, 'preco_cliente': False}]


class RegrasTests(SimpleTestCase):
    def test_potencial(self):
        self.assertEqual(regras.potencial(850, Decimal('2.0'), 4), 425.0)
        self.assertEqual(regras.potencial(850, 2, 0), 0.0)
        self.assertIsNone(regras.potencial(None, 2, 4))

    def test_a_vista_e_desconto(self):
        # Protótipo: R$ 86 em 90 dias a 1,2% a.m. ≈ R$ 82,98; padrão 92 → 9,8% efetivo.
        self.assertEqual(regras.a_vista(86, 90), 82.98)
        self.assertEqual(regras.desconto_pct(86, 92), 6.5)
        self.assertEqual(regras.desconto_efetivo(86, 90, 92), 9.8)

    def test_aprovacao(self):
        self.assertTrue(regras.precisa_aprovacao(95, 0, 92))  # começamos com todas
        with mock.patch.object(regras, 'APROVAR_TODAS', False):
            self.assertFalse(regras.precisa_aprovacao(92, 0, 92))
            self.assertTrue(regras.precisa_aprovacao(92, 30, 92))  # prazo come o preço

    def test_prazo_e_conferencia(self):
        self.assertEqual([regras.prazo_em_dias(t) for t in ('1', '', '30', '15/30/45', 'x')], [0, 0, 30, 45, None])
        a = {'cliente': 10, 'produto': 1, 'volume_t': 400, 'preco': 90.0, 'prazo': 60}
        self.assertEqual(regras.conferir(a, dict(a)), [])
        dif = regras.conferir(a, {**a, 'prazo': 90})
        self.assertEqual(dif, [{'campo': 'prazo', 'aprovado': 60.0, 'lancado': 90.0}])


@mock.patch('comercialAgro.erp_agro.financeiro', return_value={'vencido': 0, 'bloqueado': False})
@mock.patch('comercialAgro.erp_agro.produtos', return_value=PRODUTOS)
class FluxoTests(TestCase):
    def setUp(self):
        self.vend_user = User.objects.create_user('paulo', first_name='Paulo')
        self.vend = VendedorAgro.objects.create(user=self.vend_user, carteira='C2 · Centro', repcods=[82])
        self.gestor = User.objects.create_user('lucas')
        self.gestor.groups.add(Group.objects.get_or_create(name='agroGestor')[0])
        self.interno = User.objects.create_user('rai')
        self.interno.groups.add(Group.objects.get_or_create(name='agroInterno')[0])
        self.outro = User.objects.create_user('nada')

    def cli(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_sem_perfil_nao_entra(self, *_):
        self.assertEqual(self.cli(self.outro).get('/comercialAgro/eu/').status_code, 403)

    def test_contato_exige_proximo_passo(self, *_):
        p = Produtor.objects.create(nome='Ernesto')
        r = self.cli(self.vend_user).post('/comercialAgro/contatos/', {
            'produtor': p.id, 'tipo': 'VISITA', 'data_hora': '2026-11-19T14:32:00-03:00', 'resultado': 'INTERESSADO',
            'proximo_passo': ' ', 'proximo_data': '2026-12-09'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('proximo_passo', r.data)

    def test_fluxo_completo(self, *_):
        v = self.cli(self.vend_user)
        r = v.post('/comercialAgro/produtores/', {'nome': 'Ernesto Weber', 'tipo': 'PRODUTOR', 'area_ha': '850',
                                                  'dose_t_ha': '2', 'ciclo_anos': 4, 'culturas': ['Soja', 'Banana']},
                   format='json')
        self.assertEqual(r.status_code, 201, r.data)
        pid = r.data['id']
        self.assertEqual((r.data['potencial_t'], r.data['culturas'], r.data['origem']), (425.0, ['Soja'], 'PROSPECT'))

        r = v.post('/comercialAgro/cotacoes/', {'produtor': pid, 'produto_cod': 1, 'volume_t': '400',
                                                'retirada': '2027-05-15', 'preco': '86', 'prazo_dias': 90,
                                                'justificativa': 'Concorrente a 84 posto'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        cid = r.data['id']
        self.assertEqual((r.data['status'], r.data['preco_padrao'], r.data['retirada']), ('AGUARDANDO', '92.00', '2027-05-01'))
        self.assertIn('Prospect', r.data['pendencia_credito'])

        # Vendedor não decide; gestor contrapropõe; vendedor aceita.
        self.assertEqual(v.post(f'/comercialAgro/cotacoes/{cid}/decidir/', {'acao': 'aprovar'}).status_code, 403)
        g = self.cli(self.gestor)
        r = g.post(f'/comercialAgro/cotacoes/{cid}/decidir/', {'acao': 'contrapropor', 'preco': '89', 'prazo': 60,
                                                               'condicao': 'SINAL30', 'recado': 'Ofereça a coleta'})
        self.assertEqual(r.data['status'], 'CONTRAPROPOSTA')
        r = v.post(f'/comercialAgro/cotacoes/{cid}/responder/', {'aceitar': True}, format='json')
        self.assertEqual((r.data['status'], r.data['preco_final'], r.data['prazo_final']), ('APROVADA', '89.00', 60))

        # Interno: cadastro do prospect antes do pedido.
        i = self.cli(self.interno)
        fila = i.get('/comercialAgro/fila/').data
        self.assertEqual([len(fila['cadastros']), len(fila['pedidos'])], [1, 1])
        self.assertEqual(i.post(f'/comercialAgro/cotacoes/{cid}/lancar/', {'pedido': 10530}).status_code, 400)
        with mock.patch('comercialAgro.erp_agro.cliente', return_value={'nome': 'ERNESTO WEBER'}):
            r = i.post(f'/comercialAgro/produtores/{pid}/cadastrado/', {'cliente_sga': 48213})
        self.assertEqual(r.data['cadastro'], 'CADASTRADO')

        lido = {'numero': 10530, 'cliente': 48213, 'prazo': 90, 'prazo_texto': '90', 'situacao': 0,
                'itens': [{'produto': 1, 'descricao': 'x', 'toneladas': 400.0, 'preco': 89.0}]}
        with mock.patch('comercialAgro.erp_agro.pedido', return_value=lido):
            r = i.post(f'/comercialAgro/cotacoes/{cid}/lancar/', {'pedido': 10530})
        self.assertEqual((r.data['status'], r.data['divergente']), ('LANCADA', True))
        self.assertEqual(r.data['conferencia']['diferencas'][0]['campo'], 'prazo')
        with mock.patch('comercialAgro.erp_agro.pedido', return_value={**lido, 'prazo': 60}):
            r = i.post(f'/comercialAgro/cotacoes/{cid}/conferir/')
        self.assertFalse(r.data['divergente'])
        self.assertIsNotNone(r.data['corrigido_em'])

    def test_recusa_exige_motivo_e_listas_por_papel(self, *_):
        p = Produtor.objects.create(nome='Boa Vista', cliente_sga=10, cadastro='CADASTRADO', origem='SGA')
        Cotacao.objects.create(produtor=p, vendedor=self.vend, produto_cod=1, produto_nome='x', volume_t=10,
                               retirada=date(2027, 5, 1), preco=90, prazo_dias=0)
        outro_v = VendedorAgro.objects.create(user=User.objects.create_user('julio'), repcods=[34])
        c2 = Cotacao.objects.create(produtor=p, vendedor=outro_v, produto_cod=1, produto_nome='x', volume_t=10,
                                    retirada=date(2027, 5, 1), preco=90, prazo_dias=0)
        self.assertEqual(len(self.cli(self.vend_user).get('/comercialAgro/cotacoes/').data), 1)
        self.assertEqual(len(self.cli(self.gestor).get('/comercialAgro/cotacoes/?modo=aprovacao').data), 2)
        r = self.cli(self.gestor).post(f'/comercialAgro/cotacoes/{c2.id}/decidir/', {'acao': 'recusar'})
        self.assertEqual(r.status_code, 400)

    def test_painel(self, *_):
        p = Produtor.objects.create(nome='A', coleta_oferecida=True)
        Contato.objects.create(produtor=p, vendedor=self.vend, data_hora='2026-11-19T10:00:00-03:00',
                               resultado='INTERESSADO', proximo_passo='Ligar', proximo_data=date(2026, 11, 20))
        with mock.patch('comercialAgro.erp_agro.pedidos', return_value=[]):
            r = self.cli(self.gestor).get('/comercialAgro/painel/?semana=2026-11-19')
        self.assertEqual((r.data['contatos'], r.data['coletas_solo'], r.data['prospects_novos']), (1, 1, 1))
        self.assertEqual(r.data['por_vendedor'][0], {'nome': 'Paulo', 'contatos': 1})
        self.assertEqual(self.cli(self.vend_user).get('/comercialAgro/painel/').status_code, 403)

    def test_cadastro_de_vendedor_mantem_o_grupo(self, *_):
        g = self.cli(self.gestor)
        r = g.post('/comercialAgro/vendedores/', {'user': self.outro.id, 'repcods': ['34', 34, 82], 'carteira': 'C1'}, format='json')
        self.assertEqual((r.status_code, r.data['repcods']), (201, [34, 82]))
        self.assertTrue(self.outro.groups.filter(name='agroVendedor').exists())
        g.patch(f"/comercialAgro/vendedores/{r.data['id']}/", {'ativo': False}, format='json')
        self.assertFalse(self.outro.groups.filter(name='agroVendedor').exists())
        r = g.post(f"/comercialAgro/vendedores/{r.data['id']}/meta/", {'ano': 2026, 'toneladas': '30000'})
        self.assertEqual(r.data['metas'][0]['toneladas'], '30000.0')


class VendedoresComissoesTests(TestCase):
    def test_casa_por_nome_e_email(self):
        from comissoes.models import Representante
        gestor = User.objects.create_user('lucas')
        gestor.groups.add(Group.objects.get_or_create(name='agroGestor')[0])
        u_email = User.objects.create_user('everton', email='everton@x.com')
        Representante.objects.create(nome='Everton Marques Dorneles', segmento='AGRO', email='EVERTON@x.com')
        Representante.objects.create(nome='Rodrigo Chaves Cruz', segmento='CC')
        sga = [{'cod': 82, 'nome': 'EVERTON MARQUES DORNELES', 'inativo': 'N'},
               {'cod': 38, 'nome': 'RODRIGO CHAVES CRUZ (FRONTEIRA)', 'inativo': 'N'},
               {'cod': 42, 'nome': 'RODRIGO CHAVES CRUZ (PLANALTO)', 'inativo': 'N'},
               {'cod': 9, 'nome': 'RODRIGO CHAVES CRUZ', 'inativo': 'S'}]
        c = APIClient()
        c.force_authenticate(gestor)
        with mock.patch('pedidosVenda.erp.representantes', return_value=sga):
            r = c.get('/comercialAgro/vendedores/comissoes/')
        ev, ro = r.data
        self.assertEqual((ev['nome'], ev['agro'], ev['user'], ev['repcods']), ('Everton Marques Dorneles', True, u_email.id, [82]))
        self.assertEqual((ro['agro'], ro['user'], ro['repcods']), (False, None, [38, 42]))
