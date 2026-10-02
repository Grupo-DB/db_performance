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

FIN_LIMPO = {
    'bloqueado': False, 'aberto': 0.0, 'vencido': 0.0, 'a_vencer': 0.0, 'qtd_aberto': 0, 'qtd_vencido': 0,
    'maior_atraso': 0, 'negativado': False, 'protestado': False, 'titulos_vencidos': [], 'proximos': [],
}


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
        # O financeiro do cliente vem do ERP; aqui, cliente em dia salvo onde o teste diz o contrário.
        self.fin = dict(FIN_LIMPO)
        patcher = mock.patch('pedidosVenda.erp.situacao_financeira', side_effect=lambda cod: self.fin)
        patcher.start()
        self.addCleanup(patcher.stop)

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

    def test_atraso_dentro_da_tolerancia_segue_direto(self, _):
        self.fin.update(vencido=500.0, qtd_vencido=1, maior_atraso=3)
        p = self._criar()
        r = self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {}, format='json')
        self.assertEqual(r.json()['status'], 'ENVIADO')
        self.assertEqual(r.json()['pendencia_financeira'], '')

    def test_titulo_vencido_vai_para_o_gestor_com_justificativa(self, _):
        self.fin.update(vencido=4600.0, qtd_vencido=2, maior_atraso=58, protestado=True)
        p = self._criar()
        api = self._como(self.ext_user)
        r = api.post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('58 dias', r.json()['detail'])
        r = api.post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {'justificativa': 'Cliente pagou ontem, comprovante no WhatsApp'}, format='json')
        self.assertEqual(r.json()['status'], 'AGUARDANDO_APROVACAO')
        self.assertIn('protestado', r.json()['pendencia_financeira'])
        self.assertTrue(PedidoVendaNotificacao.objects.filter(usuario_notificado=self.gestor, tipo='APROVACAO_SOLICITADA').exists())
        r = self._como(self.gestor).post(f'/pedidosVenda/pedidos/{p["id"]}/aprovar/', {}, format='json')
        self.assertEqual(r.json()['status'], 'ENVIADO')

    def test_cliente_bloqueado_no_erp_tambem(self, _):
        self.fin['bloqueado'] = True
        p = self._criar()
        r = self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {'justificativa': 'liberado pelo financeiro'}, format='json')
        self.assertEqual(r.json()['status'], 'AGUARDANDO_APROVACAO')
        self.assertIn('bloqueado', r.json()['pendencia_financeira'])

    def test_erp_fora_do_ar_nao_trava_o_envio(self, _):
        with mock.patch('pedidosVenda.erp.situacao_financeira', side_effect=OSError('sem ERP')):
            p = self._criar()
            r = self._como(self.ext_user).post(f'/pedidosVenda/pedidos/{p["id"]}/enviar/', {}, format='json')
        self.assertEqual(r.json()['status'], 'ENVIADO')

    def test_sincronizacao_offline_nao_duplica(self, _):
        corpo = {'id_offline': 'off-7f3a', 'cliente_cod': 105, 'cliente_nome': 'OBRA', 'prazo_pagamento': '30',
                 'itens': [{'produto_cod': 1, 'descricao': 'CALCARIO', 'unidade': 'TN', 'quantidade': '10',
                            'preco_tabela': '95', 'preco_unitario': '92'}]}
        api = self._como(self.ext_user)
        r1 = api.post('/pedidosVenda/pedidos/', corpo, format='json')
        r2 = api.post('/pedidosVenda/pedidos/', corpo, format='json')  # a resposta do 1º "se perdeu"
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()['id'], r2.json()['id'])
        self.assertEqual(PedidoVenda.objects.filter(id_offline='off-7f3a').count(), 1)
        r3 = self._como(self.outro).post('/pedidosVenda/pedidos/', corpo, format='json')
        self.assertEqual(r3.status_code, 409)

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


def _nota(cod, etapa_sit=0, carga=None, placa='', tara=0.0, peso=10.0):
    return {
        'cod': cod, 'num': -cod if etapa_sit == 0 else cod, 'sit': etapa_sit, 'filial': 0, 'pedido': 1,
        'emitida_em': None, 'criado_em': '2026-10-01', 'cliente_cod': cod, 'cliente': f'CLI {cod}',
        'fantasia': '', 'cidade': 'X-RS', 'repcod': 41, 'vendedor': 'V', 'placa': placa,
        'motorista': 'M' if placa else None, 'motorista_celular': None, 'transportador': None,
        'peso': peso, 'tara': tara, 'bruto': peso + tara, 'limite_peso': 0, 'total': 100.0,
        'carga_cod': carga, 'carga_desc': f'CARGA {carga}' if carga else None, 'carga_data': '2026-10-02' if carga else None,
        'carga_tipo': 1 if carga else None, 'produto': 'P', 'qtd_itens': 1,
    }


class PainelCargasTest(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.ext_user = User.objects.create_user('externo')
        self.int_user = User.objects.create_user('interno')
        self.tv = User.objects.create_user('tv')
        self.tv.groups.add(Group.objects.create(name='cargasPainel'))
        self.nada = User.objects.create_user('nada')
        VendedorPerfil.objects.create(user=self.int_user, tipo='INTERNO')
        VendedorPerfil.objects.create(user=self.ext_user, tipo='EXTERNO', repcods=[41, 53])
        self.api = APIClient()

    def _get(self, user, url='/pedidosVenda/cargas/'):
        self.api.force_authenticate(user)
        return self.api.get(url)

    def test_etapas_e_agrupamento_da_carga_composta(self):
        from . import cargas
        # Notas cruas passam pela mesma conversão do SQL.
        with mock.patch('pedidosVenda.erp._rows', return_value=[
            _nota(1, carga=7), _nota(2, carga=7, placa='ABC-1234', tara=15), _nota(3), _nota(4, etapa_sit=1, carga=8, placa='X'),
        ]):
            notas = cargas._notas('')
        por_cod = {n['cod']: n for n in notas}
        self.assertEqual(por_cod[1]['etapa'], 'PROGRAMADO')
        self.assertEqual(por_cod[1]['carregamento'], 1)
        self.assertEqual(por_cod[2]['etapa'], 'NO_PATIO')
        self.assertEqual(por_cod[2]['liquido'], 10.0)
        self.assertEqual(por_cod[4]['etapa'], 'FATURADO')
        self.assertEqual(por_cod[4]['nota'], 4)

        grupos = {c['chave']: c for c in cargas.agrupar_cargas(notas)}
        self.assertEqual(set(grupos), {'c7', 'n3', 'c8'})
        self.assertEqual(grupos['c7']['etapa'], 'NO_PATIO')  # um carregamento com caminhão leva a carga junto
        self.assertEqual(grupos['c7']['peso'], 20.0)
        self.assertEqual(grupos['c7']['placa'], 'ABC-1234')
        self.assertEqual(grupos['c8']['etapa'], 'FATURADO')
        self.assertFalse(grupos['n3']['composta'])

    @mock.patch('pedidosVenda.cargas.painel', return_value={'cargas': [], 'aguardando': []})
    def test_escopo_por_perfil(self, painel):
        self.assertEqual(self._get(self.nada).status_code, 403)

        r = self._get(self.ext_user)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['ve_todas'])
        self.assertEqual(painel.call_args.args[3], [41, 53])

        for user in (self.int_user, self.tv):
            r = self._get(user)
            self.assertTrue(r.json()['ve_todas'])
            self.assertIsNone(painel.call_args.args[3])

        r = self._get(self.int_user, '/pedidosVenda/cargas/?escopo=meus&filial=3')
        self.assertFalse(r.json()['ve_todas'])
        self.assertEqual(painel.call_args.args[2], 3)

    @mock.patch('pedidosVenda.cargas.painel', return_value={'cargas': [], 'aguardando': []})
    def test_pre_pedidos_do_app_e_periodo(self, painel):
        PedidoVenda.objects.create(vendedor=self.ext_user, status='ENVIADO', cliente_nome='OBRA', total=Decimal('10'))
        PedidoVenda.objects.create(vendedor=self.ext_user, status='LANCADO', cliente_nome='JÁ NO SGA')
        r = self._get(self.tv)
        self.assertEqual([p['cliente'] for p in r.json()['pre_pedidos']], ['OBRA'])
        self.assertEqual(self._get(self.tv, '/pedidosVenda/cargas/?inicio=2026-01-01&fim=2026-06-01').status_code, 400)


class FolhaCargaTest(TestCase):
    def setUp(self):
        self.interno = User.objects.create_user('interno')
        VendedorPerfil.objects.create(user=self.interno, tipo='INTERNO')
        self.externo = User.objects.create_user('externo')
        VendedorPerfil.objects.create(user=self.externo, tipo='EXTERNO', repcods=[41])
        self.expedicao = User.objects.create_user('expedicao')
        self.expedicao.groups.add(Group.objects.create(name='cargasPainel'))
        self.api = APIClient()
        from django.core.cache import cache
        cache.clear()  # a conferência no SGA fica 20 s em cache, com chave igual entre os testes

    def _folha(self, **extra):
        self.api.force_authenticate(self.interno)
        corpo = {'descricao': 'RIO GRANDE ENTREGAR 10/10', 'filial': 0, 'placa': 'iwd 7c31', 'lotacao': '32', 'itens': [
            {'pedido': 501, 'cliente': 'A', 'cidade': 'Rio Grande-RS', 'peso': '12.5'},
            {'pedido': 502, 'cliente': 'B', 'cidade': 'Pelotas-RS', 'peso': '8'},
        ], **extra}
        return self.api.post('/pedidosVenda/folhas-carga/', corpo, format='json')

    @mock.patch('pedidosVenda.cargas.situacao_no_sga', return_value={})
    def test_interno_monta_na_ordem_de_entrega(self, _):
        r = self._folha()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['placa'], 'IWD7C31')
        self.assertEqual([i['ordem'] for i in r.data['itens']], [1, 2])
        self.assertEqual(r.data['peso'], 20.5)
        # Reordena: o que vai primeiro é o que entra primeiro na lista.
        folha = r.data['id']
        r = self.api.patch(f'/pedidosVenda/folhas-carga/{folha}/', {'itens': [
            {'pedido': 502, 'peso': '8'}, {'pedido': 501, 'peso': '12.5'}]}, format='json')
        self.assertEqual([(i['pedido'], i['ordem']) for i in r.data['itens']], [(502, 1), (501, 2)])

    @mock.patch('pedidosVenda.cargas.situacao_no_sga', return_value={})
    def test_pedido_nao_vai_em_duas_folhas_abertas(self, _):
        self._folha()
        r = self._folha(descricao='OUTRA')
        self.assertEqual(r.status_code, 400)
        self.assertIn('já está na folha', str(r.data))

    def test_fecha_sozinha_quando_todos_os_pedidos_estao_no_sga(self):
        self._folha()
        sga = {501: {'etapa': 'PROGRAMADO', 'numero': 1, 'carga_cod': 77, 'carga_desc': 'X'}}
        with mock.patch('pedidosVenda.cargas.situacao_no_sga', return_value=sga):
            r = self.api.get('/pedidosVenda/folhas-carga/')
        self.assertEqual(r.data[0]['status'], 'MONTANDO')
        self.assertEqual(r.data[0]['itens'][0]['sga']['carga_cod'], 77)
        self.assertIsNone(r.data[0]['itens'][1]['sga'])
        sga[502] = {'etapa': 'PROGRAMADO', 'numero': 2, 'carga_cod': 77, 'carga_desc': 'X'}
        from django.core.cache import cache
        cache.clear()
        with mock.patch('pedidosVenda.cargas.situacao_no_sga', return_value=sga):
            r = self.api.get('/pedidosVenda/folhas-carga/')
        self.assertEqual(r.data[0]['status'], 'NO_SGA')
        self.assertEqual(r.data[0]['carga_sga'], 77)
        # Fechada sai da lista das abertas e não aceita mais edição.
        r = self.api.get('/pedidosVenda/folhas-carga/')
        self.assertEqual(r.data, [])

    @mock.patch('pedidosVenda.cargas.situacao_no_sga', return_value={})
    def test_expedicao_olha_e_externo_nem_isso(self, _):
        self._folha()
        self.api.force_authenticate(self.expedicao)
        self.assertEqual(self.api.get('/pedidosVenda/folhas-carga/').status_code, 200)
        self.assertEqual(self.api.post('/pedidosVenda/folhas-carga/', {'descricao': 'x'}, format='json').status_code, 403)
        self.api.force_authenticate(self.externo)
        self.assertEqual(self.api.get('/pedidosVenda/folhas-carga/').status_code, 403)

    @mock.patch('pedidosVenda.cargas.situacao_no_sga', return_value={})
    def test_cancelar_e_reabrir(self, _):
        folha = self._folha().data['id']
        r = self.api.post(f'/pedidosVenda/folhas-carga/{folha}/cancelar/')
        self.assertEqual(r.data['status'], 'CANCELADA')
        self.assertEqual(self._folha(descricao='NOVA').status_code, 201)  # pedidos liberados
        r = self.api.post(f'/pedidosVenda/folhas-carga/{folha}/reabrir/')
        self.assertEqual(r.status_code, 400)


class EstoqueErpTest(TestCase):
    def test_fabricado_nao_tem_disponivel_e_revenda_desconta_os_pedidos(self):
        from django.core.cache import cache
        from . import erp
        cache.clear()
        fisico = [{'cod': 2743, 'saldo': -364.0, 'fabricado': 1}, {'cod': 26, 'saldo': 1571.0, 'fabricado': 0}]
        pedidos = [{'cod': 2743, 'saldo': 17085.0}, {'cod': 26, 'saldo': 333.0}]
        with mock.patch('pedidosVenda.erp._rows', side_effect=[fisico, pedidos]):
            e = erp.estoque(0)
        self.assertEqual(e[2743]['origem'], 'FABRICADO')
        self.assertEqual(e[26], {'fisico': 1571.0, 'comprometido': 333.0, 'disponivel': 1238.0, 'origem': 'REVENDA'})


class CarteiraTest(TestCase):
    def _linha(self, cli, data, linha=1827, nome='CAL', valor=1000):
        return {'cliente': cli, 'data': data, 'repcod': 41, 'linha_cod': linha, 'linha': nome, 'valor': valor, 'tn': 1}

    def test_ciclo_positivacao_e_linha_perdida(self):
        from datetime import date
        from .carteira import calcular
        hoje = date(2026, 10, 15)
        linhas = [
            # 1: compra a cada ~30 dias e já comprou em outubro.
            self._linha(1, '2026-07-10'), self._linha(1, '2026-08-10'), self._linha(1, '2026-09-10'), self._linha(1, '2026-10-05'),
            # 2: ciclo de 20 dias, última há 45 ⇒ atrasado; argamassa parou em maio ⇒ linha perdida.
            self._linha(2, '2026-05-01', 1824, 'ARGAMASSA'), self._linha(2, '2026-08-01'), self._linha(2, '2026-08-11'), self._linha(2, '2026-08-31'),
            # 3: uma compra só ⇒ sem ciclo.
            self._linha(3, '2026-09-20'),
            # 4: sem comprar há mais de 180 dias ⇒ inativo.
            self._linha(4, '2026-01-10'), self._linha(4, '2026-02-10'),
        ]
        d = calcular(linhas, hoje, {1: {'nome': 'UM'}})
        por = {c['cod']: c for c in d['clientes']}
        self.assertEqual(por[1]['situacao'], 'COMPROU')
        self.assertEqual(por[2]['situacao'], 'ATRASADO')
        self.assertEqual(por[2]['ciclo_dias'], 20)
        self.assertEqual(por[2]['atraso_dias'], 25)
        self.assertEqual(por[2]['linhas_perdidas'], ['ARGAMASSA'])
        self.assertEqual(por[3]['situacao'], 'SEM_CICLO')
        self.assertEqual(por[4]['situacao'], 'INATIVO')
        self.assertEqual(d['resumo']['carteira'], 4)
        self.assertEqual(d['resumo']['positivados'], 1)
        self.assertEqual(d['resumo']['positivacao'], 25.0)
        # Setembro até o dia 15: só o cliente 1 (dia 10); o 3 comprou dia 20 e não entra.
        self.assertEqual(d['resumo']['positivados_mes_anterior'], 1)
        cal = next(m for m in d['mix'] if m['nome'] == 'CAL')
        self.assertEqual(cal['clientes'], 3)  # o inativo não entra no mix
