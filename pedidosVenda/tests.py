"""
Fluxo do pedido de venda, com o ERP simulado.

    venv/bin/python manage.py test pedidosVenda --settings=db_performance.test_settings
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from .models import PedidoVenda, PedidoVendaNotificacao, VendedorPerfil

TABELA = {1: 95.0, 2743: 12.03}


def _precos(filial, cliente, produtos):
    return {p: TABELA[p] for p in produtos if p in TABELA}


@mock.patch('pedidosVenda.erp.precos_vigentes', side_effect=_precos)
class FluxoPedidoTest(TestCase):
    def setUp(self):
        self.ext_user = User.objects.create_user('externo', first_name='Glauber')
        self.int_user = User.objects.create_user('interno', first_name='Jaklainy')
        self.gestor = User.objects.create_user('gestor')
        self.gestor.groups.add(Group.objects.create(name='vendasGestao'))
        self.outro = User.objects.create_user('outro')

        self.p_int = VendedorPerfil.objects.create(user=self.int_user, tipo='INTERNO')
        self.p_ext = VendedorPerfil.objects.create(
            user=self.ext_user, tipo='EXTERNO', repcods=[41], filial_padrao=0,
            desconto_maximo=Decimal('5'), interno=self.p_int,
        )
        VendedorPerfil.objects.create(user=self.outro, tipo='EXTERNO')
        self.api = APIClient()

    def _como(self, user):
        self.api.force_authenticate(user)
        return self.api

    def _criar(self, preco=Decimal('92'), **extra):
        dados = {
            'cliente_cod': 105, 'cliente_nome': 'OBRA MATERIAIS', 'prazo_pagamento': '30',
            'itens': [
                {'produto_cod': 1, 'descricao': 'CALCARIO GRANEL', 'unidade': 'TN',
                 'quantidade': '10', 'preco_tabela': '95', 'preco_unitario': str(preco)},
            ],
            **extra,
        }
        r = self._como(self.ext_user).post('/pedidosVenda/pedidos/', dados, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def test_cria_com_padroes_do_perfil(self, _):
        p = self._criar()
        self.assertEqual(p['status'], 'RASCUNHO')
        self.assertEqual(p['repcod'], 41)
        self.assertEqual(p['interno'], self.int_user.pk)
        self.assertEqual(Decimal(p['total']), Decimal('920.00'))
        self.assertAlmostEqual(p['itens'][0]['dif_tabela_perc'], -3.15789, places=4)

    def test_envio_dentro_do_teto_vai_para_o_interno(self, _):
        p = self._criar()
        r = self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['status'], 'ENVIADO')
        self.assertTrue(PedidoVendaNotificacao.objects.filter(usuario_notificado=self.int_user, tipo='NOVO_PEDIDO').exists())

    def test_desconto_acima_do_teto_exige_justificativa_e_aprovacao(self, _):
        p = self._criar(preco=Decimal('80'))  # 15,8% abaixo da tabela, teto 5%
        api = self._como(self.ext_user)
        r = api.post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('justificativa', r.json()['detail'])

        r = api.post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {'justificativa': 'Concorrência'}, format='json')
        self.assertEqual(r.json()['status'], 'AGUARDANDO_APROVACAO')
        self.assertTrue(PedidoVendaNotificacao.objects.filter(usuario_notificado=self.gestor).exists())

        # Interno não lança antes da aprovação.
        r = self._como(self.int_user).post(f'/pedidosVenda/pedidos/{p["id"]}/assumir/', {}, format='json')
        self.assertEqual(r.status_code, 400)

        r = self._como(self.gestor).post(f'/pedidosVenda/pedidos/{p["id"]}/aprovar/', {}, format='json')
        self.assertEqual(r.json()['status'], 'ENVIADO')
        self.assertEqual(r.json()['aprovado_por'], self.gestor.pk)

    def test_preco_de_tabela_vem_do_erp_e_nao_do_navegador(self, _):
        # Navegador diz que a tabela é 80 (desconto zero); o ERP diz 95.
        p = self._criar(preco=Decimal('80'), itens=[
            {'produto_cod': 1, 'descricao': 'X', 'quantidade': '1', 'preco_tabela': '80', 'preco_unitario': '80'},
        ])
        r = self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {}, format='json')
        # O desconto é medido sobre os 95 do ERP: 15,79%, acima do teto de 5%.
        self.assertEqual(r.status_code, 400)
        self.assertIn('15,79%', r.json()['detail'])

    def test_produto_sem_preco_na_unidade_nao_envia(self, _):
        p = self._criar(itens=[{'produto_cod': 999, 'descricao': 'SEM TABELA', 'quantidade': '1',
                                'preco_tabela': '10', 'preco_unitario': '10'}])
        r = self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('não tem preço', r.json()['detail'])

    @mock.patch('pedidosVenda.erp.pedido_erp')
    def test_interno_assume_e_lanca_conferindo_o_erp(self, pedido_erp, _):
        p = self._criar()
        self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {}, format='json')
        api = self._como(self.int_user)
        self.assertEqual(api.post(f'/pedidosVenda/pedidos/{p["id"]}/assumir/').json()['status'], 'EM_LANCAMENTO')

        pedido_erp.return_value = None
        r = api.post(f'/pedidosVenda/pedidos/{p["id"]}/lancar/', {'numero_erp': '135999'}, format='json')
        self.assertEqual(r.status_code, 400)

        pedido_erp.return_value = {'numero': 135999, 'cliente': 7}
        r = api.post(f'/pedidosVenda/pedidos/{p["id"]}/lancar/', {'numero_erp': '135999'}, format='json')
        self.assertIn('outro cliente', r.json()['detail'])

        pedido_erp.return_value = {'numero': 135999, 'cliente': 105}
        r = api.post(f'/pedidosVenda/pedidos/{p["id"]}/lancar/', {'numero_erp': '135999'}, format='json')
        self.assertEqual(r.json()['status'], 'LANCADO')
        self.assertEqual(r.json()['numero_erp'], 135999)
        self.assertTrue(PedidoVendaNotificacao.objects.filter(usuario_notificado=self.ext_user, tipo='LANCADO').exists())

    def test_devolvido_volta_a_ser_editavel_e_reenviado(self, _):
        p = self._criar()
        self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/')
        r = self._como(self.int_user).post(f'/pedidosVenda/pedidos/{p["id"]}/devolver/', {'motivo': ''}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self._como(self.int_user).post(f'/pedidosVenda/pedidos/{p["id"]}/devolver/', {'motivo': 'Prazo errado'}, format='json')
        self.assertEqual(r.json()['status'], 'DEVOLVIDO')

        api = self._como(self.ext_user)
        r = api.patch(f'/pedidosVenda/pedidos/{p["id"]}/', {'prazo_pagamento': '30/60'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = api.post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/')
        self.assertEqual(r.json()['status'], 'ENVIADO')
        self.assertEqual(r.json()['motivo_devolucao'], '')

    def test_enviado_nao_e_editavel(self, _):
        p = self._criar()
        api = self._como(self.ext_user)
        api.post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/')
        r = api.patch(f'/pedidosVenda/pedidos/{p["id"]}/', {'observacoes': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_externo_so_ve_os_proprios(self, _):
        p = self._criar()
        r = self._como(self.outro).get(f'/pedidosVenda/pedidos/{p["id"]}/')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self._como(self.outro).get('/pedidosVenda/pedidos/').json(), [])
        # Interno não vê rascunho alheio, mas vê depois de enviado.
        self.assertEqual(self._como(self.int_user).get(f'/pedidosVenda/pedidos/{p["id"]}/').status_code, 404)
        self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/')
        self.assertEqual(self._como(self.int_user).get(f'/pedidosVenda/pedidos/{p["id"]}/').status_code, 200)

    def test_sem_perfil_nao_entra(self, _):
        anonimo = User.objects.create_user('semperfil')
        self.assertEqual(self._como(anonimo).get('/pedidosVenda/pedidos/').status_code, 403)
        self.assertEqual(self._como(anonimo).get('/pedidosVenda/eu/').json()['perfil'], None)

    def test_pre_cadastro_exige_campos_minimos(self, _):
        p = self._criar(cliente_cod=None, cliente_nome='NOVO CLIENTE', cliente_novo={'nome': 'NOVO CLIENTE'})
        r = self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('CNPJ/CPF', r.json()['detail'])

    def test_duplicar_e_resumo(self, _):
        p = self._criar()
        r = self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/duplicar/')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(len(r.json()['itens']), 1)
        resumo = self._como(self.ext_user).get('/pedidosVenda/pedidos/resumo/').json()
        self.assertEqual(resumo['por_status'], {'RASCUNHO': 2})

    def test_gestor_cadastra_perfil_e_grupo_acompanha(self, _):
        novo = User.objects.create_user('novo')
        r = self._como(self.gestor).post('/pedidosVenda/vendedores/', {
            'user': novo.pk, 'tipo': 'EXTERNO', 'repcods': ['42', 38], 'desconto_maximo': '3',
            'interno': self.p_int.pk,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['repcods'], [38, 42])
        self.assertTrue(novo.groups.filter(name='vendasPedidos').exists())
        self.assertEqual(self._como(self.ext_user).get('/pedidosVenda/vendedores/').status_code, 403)


class FotoProdutoTest(TestCase):
    def setUp(self):
        import tempfile
        from django.test import override_settings
        self._media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        self._media.enable()
        self.gestor = User.objects.create_user('gestor')
        self.gestor.groups.add(Group.objects.create(name='vendasGestao'))
        self.vendedor = User.objects.create_user('vend')
        VendedorPerfil.objects.create(user=self.vendedor, tipo='EXTERNO')
        self.api = APIClient()

    def tearDown(self):
        self._media.disable()

    def _png(self, w=2000, h=1000):
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buf = BytesIO()
        Image.new('RGBA', (w, h), (200, 30, 30, 128)).save(buf, format='PNG')
        return SimpleUploadedFile('foto.png', buf.getvalue(), content_type='image/png')

    def test_gestor_envia_redimensiona_e_mapa_vale_para_todos_os_codigos(self):
        from PIL import Image
        self.api.force_authenticate(self.gestor)
        r = self.api.post('/pedidosVenda/fotos/', {'arquivo': self._png(), 'codigos': '[2743, 11598]', 'descricao': 'CAL'}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        from .models import FotoProduto
        f = FotoProduto.objects.get()
        self.assertEqual(f.codigos, [2743, 11598])
        self.assertEqual(max(Image.open(f.imagem.path).size), 1200)
        self.assertEqual(max(Image.open(f.miniatura.path).size), 240)

        self.api.force_authenticate(self.vendedor)
        mapa = self.api.get('/pedidosVenda/fotos/mapa/').json()
        self.assertEqual(set(mapa), {'2743', '11598'})
        # O arquivo sai pela API, sem token (é um <img>), e não por /media.
        caminho = mapa['2743']['miniatura']
        self.assertTrue(caminho.startswith(f'fotos/{f.pk}/arquivo/?t=mini'))
        anonimo = APIClient()
        r = anonimo.get('/pedidosVenda/' + caminho)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/jpeg')
        self.assertEqual(max(Image.open(__import__('io').BytesIO(b''.join(r.streaming_content))).size), 240)
        self.assertEqual(anonimo.get(f'/pedidosVenda/fotos/{f.pk + 99}/arquivo/').status_code, 404)
        r = self.api.post('/pedidosVenda/fotos/', {'arquivo': self._png(), 'codigos': '1'}, format='multipart')
        self.assertEqual(r.status_code, 403)

    def test_codigo_nao_pode_ter_duas_fotos(self):
        self.api.force_authenticate(self.gestor)
        self.api.post('/pedidosVenda/fotos/', {'arquivo': self._png(), 'codigos': '2743'}, format='multipart')
        r = self.api.post('/pedidosVenda/fotos/', {'arquivo': self._png(), 'codigos': '2743,1'}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertIn('2743', str(r.json()))

    def test_arquivo_que_nao_e_imagem(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.api.force_authenticate(self.gestor)
        r = self.api.post('/pedidosVenda/fotos/', {'arquivo': SimpleUploadedFile('x.png', b'nada'), 'codigos': '1'}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_importacao_em_lote_respeita_foto_existente(self):
        import json, tempfile
        from pathlib import Path
        from django.core.management import call_command
        from PIL import Image
        from .models import FotoProduto
        pasta = Path(tempfile.mkdtemp())
        Image.new('RGB', (800, 1200), 'red').save(pasta / 'a.jpg')
        Image.new('RGB', (800, 1200), 'blue').save(pasta / 'b.jpg')
        (pasta / 'mapeamento.json').write_text(json.dumps([
            {'arquivo': 'a.jpg', 'descricao': 'A', 'codigos': [1, 2]},
            {'arquivo': 'b.jpg', 'descricao': 'B', 'codigos': [3]},
        ]))
        self.api.force_authenticate(self.gestor)
        self.api.post('/pedidosVenda/fotos/', {'arquivo': self._png(), 'codigos': '3', 'descricao': 'manual'}, format='multipart')

        call_command('importar_fotos_produtos', str(pasta), stdout=open('/dev/null', 'w'))
        self.assertEqual(sorted(FotoProduto.objects.values_list('descricao', flat=True)), ['A', 'manual'])

        call_command('importar_fotos_produtos', str(pasta), '--substituir', stdout=open('/dev/null', 'w'))
        self.assertEqual(sorted(FotoProduto.objects.values_list('descricao', flat=True)), ['A', 'B'])
