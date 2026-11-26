"""26/11/2026 — Peças da Oficina, 2ª etapa: OCR do desenho, IA (catálogo, sugestão, foto), de-para aprendido,
kits, histórico, avisos e revisão. Nenhum teste chama a IA de verdade (o .env local tem a chave)."""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from catalogos import pecas_catalogo as pc
from catalogos import pecas_ia
from catalogos import pecas_ocr
from catalogos import pecas_oficina as po
from catalogos.models import (CatalogoPecas, ConjuntoPecas, DeParaPeca, NotificacaoPecas, PecaCatalogo,
                              SolicitacaoPecas)

BASE = '/catalogos/pecas-oficina/'

CADASTRO = [
    (4809, 'CAPO COMPLETO RK430 218004461', ''),
    (5001, 'FILTRO AR PRIMARIO RK430', ''),
    (5002, 'FILTRO OLEO MOTOR', ''),
    (5003, 'ARRUELA LISA 1/2', ''),
    (6000, 'PARA-LAMA DIREITO', ''),
]
EQUIPS = [{'codigo': 528, 'nome': 'VEC-CF-07 - CAMINHAO RK 430', 'tag': 'VEC-CF-07', 'tipo': 'VEICULOS', 'dados': '',
           'serie_sugerida': None}]


def _sit(cods):
    return {c: {'codigo': c, 'nome': dict((x[0], x[1]) for x in CADASTRO).get(c, ''), 'saldo': 3.0, 'situacao': 'ok',
                'em_compra': False} for c in cods}


class OcrTests(TestCase):
    def test_le_tsv_e_so_fica_com_figs_do_conjunto(self):
        cab = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'
        linhas = [cab, '1\t1\t0\t0\t0\t0\t0\t0\t1000\t500\t-1\t',
                  '5\t1\t1\t1\t1\t1\t100\t50\t20\t15\t91.5\t4',
                  '5\t1\t1\t1\t1\t2\t100\t50\t20\t15\t90.0\t4',     # mesma leitura repetida
                  '5\t1\t1\t1\t1\t3\t300\t200\t30\t15\t88.0\t12',
                  '5\t1\t1\t1\t1\t4\t500\t200\t30\t15\t95.0\t77',   # não existe no conjunto
                  '5\t1\t1\t1\t1\t5\t600\t200\t30\t15\t20.0\t13']   # confiança baixa
        out = pecas_ocr.ler_tsv('\n'.join(linhas), {'4', '12', '13'})
        self.assertEqual([m['fig'] for m in out], ['4', '12'])
        self.assertEqual(out[0], {'fig': '4', 'x': 0.1, 'y': 0.1, 'w': 0.02, 'h': 0.03})

    def test_fig_inteira(self):
        self.assertEqual([pecas_ocr.fig_inteira(f) for f in ('01', '01.1', '13A', '', '0')], ['1', '1', '13', '', '0'])

    def test_sem_tesseract_devolve_vazio(self):
        with mock.patch.object(pecas_ocr, 'tem_tesseract', return_value=False):
            self.assertEqual(pecas_ocr.marcadores('/nao/existe.jpg', ['1']), [])


class IaCatalogoTests(TestCase):
    def test_monta_paginas_da_ia_juntando_faixas_e_continuacao(self):
        lidas = [
            {'pagina': 1, 'tem_pecas': False, 'conjunto_codigo': '', 'conjunto_nome': 'CAPA', 'desenho_base': 0, 'pecas': []},
            {'pagina': 2, 'tem_pecas': True, 'conjunto_codigo': '', 'conjunto_nome': 'MOTOR', 'desenho_base': 0.55, 'pecas': [
                {'fig': '1', 'codigo': 'A1', 'qtd': '1', 'descricao': 'BLOCO', 'nota': '', 'serie_inicio': 100, 'serie_fim': 200},
                {'fig': '1', 'codigo': 'A1', 'qtd': '1', 'descricao': 'BLOCO', 'nota': '', 'serie_inicio': 300, 'serie_fim': 0},
            ]},
            {'pagina': 3, 'tem_pecas': True, 'conjunto_codigo': '', 'conjunto_nome': 'MOTOR', 'desenho_base': 0, 'pecas': [
                {'fig': '2', 'codigo': 'A2', 'qtd': '4', 'descricao': 'PARAFUSO', 'nota': 'VER 3A001 13.0', 'serie_inicio': 0, 'serie_fim': 0},
            ]},
        ]
        cat = pecas_ia.montar_de_paginas(lidas, {2: (612.0, 792.0), 3: (612.0, 792.0)}, 'Volvo A30')
        self.assertEqual(list(cat['conjuntos']), ['P002'])
        cj = cat['conjuntos']['P002']
        self.assertEqual((cj['paginas'], round(cj['y_tabela'], 1)), ([2, 3], 435.6))
        self.assertEqual(cj['pecas'][0]['faixas'], [[100, 200], [300, 999999]])
        self.assertEqual(cj['pecas'][1]['ver'], '3A001 13.0')

    def test_layout_desconhecido_vai_para_a_ia_e_entra_em_revisao(self):
        tmp = tempfile.mkdtemp()
        lido = pecas_ia.montar_de_paginas([{'pagina': 1, 'tem_pecas': True, 'conjunto_codigo': 'G-10',
                                            'conjunto_nome': 'FREIO', 'desenho_base': 0, 'pecas': [
            {'fig': '1', 'codigo': 'X9', 'qtd': '2', 'descricao': 'PASTILHA', 'nota': '', 'serie_inicio': 0, 'serie_fim': 0}]}],
            {1: (612.0, 792.0)})
        pdf = Path(tmp) / 'cat.pdf'
        pdf.write_bytes(b'%PDF-1.4')
        try:
            with mock.patch.object(po, 'PASTA', Path(tmp)), \
                    mock.patch.object(pc, 'ler_pdf', return_value=[{'largura': 612.0, 'altura': 792.0, 'palavras': []}]), \
                    mock.patch.object(pecas_ia, 'configurada', return_value=True), \
                    mock.patch.object(pecas_ia, 'ler_catalogo', return_value=lido) as ler:
                cat = po.importar(pdf, fabricante='Volvo')
            ler.assert_called_once()
            self.assertEqual((cat.status, cat.origem, cat.nome), ('revisao', 'ia', 'Catálogo'))
            self.assertEqual(cat.conjuntos.get().pecas.get().descricao, 'PASTILHA')
            po.publicar_catalogo(cat)
            self.assertEqual(cat.status, 'pronto')
            with self.assertRaises(ValueError):
                po.publicar_catalogo(cat)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_sem_ia_o_erro_explica(self):
        with mock.patch.object(pc, 'ler_pdf', return_value=[]), \
                mock.patch.object(pecas_ia, 'configurada', return_value=False):
            with self.assertRaisesRegex(ValueError, 'IA não está configurada'):
                po.importar('/x.pdf')


class Base(TestCase):
    def setUp(self):
        self.oficina = User.objects.create(username='oficina', first_name='Chefe')
        self.oficina.groups.add(Group.objects.get_or_create(name='comprasOficina')[0])
        self.comprador = User.objects.create(username='comprador')
        self.comprador.groups.add(Group.objects.get_or_create(name='comprasComprador')[0])
        self.cat = CatalogoPecas.objects.create(nome='RK 430M DC13', fabricante='Randon', paginas=3)
        self.cj = ConjuntoPecas.objects.create(catalogo=self.cat, codigo='2A300 00.0', nome='CAPO', pagina=2,
                                               marcadores=[{'fig': '1', 'x': .1, 'y': .1, 'w': .02, 'h': .02}])
        self.p1 = PecaCatalogo.objects.create(conjunto=self.cj, fig='01', codigo='218004461', quantidade='01',
                                              descricao='CAPO COMPLETO', faixas=[[233, 233]])
        self.p2 = PecaCatalogo.objects.create(conjunto=self.cj, fig='02', codigo='370500999', quantidade='01',
                                              descricao='FILTRO AR PRIMARIO', ordem=1)
        self.patches = [
            mock.patch.object(po, 'equipamentos_sga', return_value=EQUIPS),
            mock.patch.object(po, '_cadastro_sga', return_value=CADASTRO),
            mock.patch.object(po.ax, '_cacheado', side_effect=lambda k, s, f: f()),
            mock.patch.object(po, '_situacao_itens', side_effect=_sit),
            mock.patch.object(po, '_nomes_sga', side_effect=lambda cods: {c: n for c, n, _ in CADASTRO if c in cods}),
            mock.patch.object(pecas_ia, 'configurada', return_value=False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def cli(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c

    def solicitar(self, urgente=False, itens=None):
        r = self.cli(self.oficina).post(f'{BASE}solicitacoes/', {
            'equipamento': 528, 'urgente': urgente,
            'itens': itens or [{'peca': self.p2.id, 'quantidade': 2}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data


class DeParaTests(Base):
    def test_codigo_no_nome_ja_casa_e_vinculo_entra_na_frente(self):
        sug = po.sugestoes_sga(['218004461', '370500999'])
        self.assertEqual(sug['218004461'][0]['codigo'], 4809)
        self.assertFalse(sug['218004461'][0]['vinculado'])
        self.assertNotIn('370500999', sug)
        po.vincular_sga('370500999', 5001, self.comprador)
        sug = po.sugestoes_sga(['370500999'])
        self.assertEqual((sug['370500999'][0]['codigo'], sug['370500999'][0]['vinculado']), (5001, True))
        # com ou sem o V
        po.vincular_sga('V555666777', 5003, self.comprador)
        self.assertEqual(po.itens_sga(['555666777'])['555666777'], [5003])
        self.assertEqual(po.desvincular_sga('555666777', 5003), 1)

    def test_api_vincular_so_comprador(self):
        url = f'{BASE}depara/'
        self.assertEqual(self.cli(self.oficina).post(url, {'codigo': '370500999', 'item_sga': 5001}, format='json').status_code, 403)
        r = self.cli(self.comprador).post(url, {'codigo': '370500999', 'item_sga': 5001, 'origem': 'ia'}, format='json')
        self.assertEqual((r.status_code, r.data['origem']), (201, 'ia'))
        self.assertEqual(self.cli(self.comprador).post(url, {'codigo': '370500999', 'item_sga': 99}, format='json').status_code, 400)
        r = self.cli(self.comprador).post(url, {'codigo': '370500999', 'item_sga': 5001, 'remover': True}, format='json')
        self.assertEqual(r.data['removidos'], 1)

    def test_escolher_item_na_solicitacao_ensina(self):
        sol = self.solicitar()
        item = sol['itens'][0]['id']
        r = self.cli(self.comprador).patch(f'{BASE}solicitacoes/{sol["id"]}/itens/{item}/', {'item_sga': 5001}, format='json')
        self.assertEqual((r.status_code, r.data['itens'][0]['item_sga']), (200, 5001))
        self.assertEqual(DeParaPeca.objects.get().origem, 'solicitacao')
        self.assertEqual(self.cli(self.oficina).patch(f'{BASE}solicitacoes/{sol["id"]}/itens/{item}/', {'item_sga': 5001},
                                                      format='json').status_code, 403)

    def test_candidatos_exigem_o_tipo_da_peca(self):
        c = po.candidatos_sga('FILTRO AR PRIMARIO')
        self.assertEqual([x['codigo'] for x in c], [5001, 5002])
        self.assertEqual(po.candidatos_sga('DE PARA COM'), [])

    def test_sugestao_por_palavras_e_pela_ia(self):
        r = self.cli(self.comprador).post(f'{BASE}sugerir-sga/', {'codigo': '370500999', 'descricao': 'FILTRO AR PRIMARIO'},
                                          format='json')
        self.assertEqual((r.data['fonte'], r.data['sugestoes'][0]['item_sga']), ('palavras', 5001))
        with mock.patch.object(pecas_ia, 'configurada', return_value=True), \
                mock.patch.object(pecas_ia, 'sugerir_itens_sga',
                                  return_value=[{'item_sga': 5001, 'confianca': 'alta', 'motivo': 'mesmo filtro'}]) as ia:
            r = self.cli(self.comprador).post(f'{BASE}sugerir-sga/', {'descricao': 'FILTRO AR PRIMARIO'}, format='json')
        self.assertEqual((r.data['fonte'], r.data['sugestoes'][0]['confianca']), ('ia', 'alta'))
        self.assertEqual(ia.call_args[0][1][0]['codigo'], 5001)
        self.assertEqual(self.cli(self.oficina).post(f'{BASE}sugerir-sga/', {'descricao': 'X'}, format='json').status_code, 403)

    def test_busca_itens_do_sga(self):
        r = self.cli(self.oficina).get(f'{BASE}itens-sga/', {'q': 'filtro ar'})
        self.assertEqual([i['codigo'] for i in r.data], [5001])
        self.assertEqual(self.cli(self.oficina).get(f'{BASE}itens-sga/', {'q': '6000'}).data[0]['codigo'], 6000)

    def test_ia_so_devolve_item_da_lista(self):
        resposta = mock.Mock(stop_reason='end_turn', content=[mock.Mock(
            type='text', text='{"sugestoes": [{"item_sga": 5001, "confianca": "alta", "motivo": "ok"},'
                              ' {"item_sga": 123456, "confianca": "alta", "motivo": "inventado"}]}')])
        cliente = mock.Mock()
        cliente.messages.create.return_value = resposta
        with mock.patch.object(pecas_ia, '_cliente_e_modelo', return_value=(cliente, 'claude-opus-5-5')):
            out = pecas_ia.sugerir_itens_sga({'descricao': 'FILTRO'}, [{'codigo': 5001, 'nome': 'FILTRO AR'}])
        self.assertEqual([x['item_sga'] for x in out], [5001])


class KitHistoricoTests(Base):
    def test_kit_crud_e_permissao(self):
        url = f'{BASE}kits/'
        dados = {'nome': 'Revisão 500 h', 'catalogo': self.cat.id,
                 'itens': [{'peca': self.p2.id, 'quantidade': 2}, {'descricao': 'ÓLEO 15W40', 'quantidade': 20}]}
        self.assertEqual(self.cli(self.comprador).post(url, dados, format='json').status_code, 403)
        r = self.cli(self.oficina).post(url, dados, format='json')
        self.assertEqual((r.status_code, r.data['n_itens']), (201, 2))
        kid = r.data['id']
        self.assertEqual(self.cli(self.oficina).get(url, {'catalogo': self.cat.id}).data[0]['nome'], 'Revisão 500 h')
        r = self.cli(self.oficina).put(f'{url}{kid}/', {**dados, 'itens': dados['itens'][:1]}, format='json')
        self.assertEqual(r.data['n_itens'], 1)
        self.assertEqual(self.cli(self.oficina).post(url, {'nome': '', 'itens': []}, format='json').status_code, 400)
        self.assertEqual(self.cli(self.oficina).delete(f'{url}{kid}/').status_code, 204)

    def test_historico_conta_vezes_e_ignora_cancelada(self):
        self.solicitar()
        self.solicitar(itens=[{'peca': self.p2.id, 'quantidade': 1}, {'peca': self.p1.id, 'quantidade': 1}])
        cancelada = self.solicitar(itens=[{'peca': self.p1.id, 'quantidade': 5}])
        SolicitacaoPecas.objects.filter(pk=cancelada['id']).update(status='cancelada')
        r = self.cli(self.oficina).get(f'{BASE}equipamentos/528/historico/')
        self.assertEqual(r.data['total_solicitacoes'], 2)
        filtro = r.data['pecas'][0]
        self.assertEqual((filtro['codigo'], filtro['vezes'], filtro['quantidade']), ('370500999', 2, 3.0))
        self.assertEqual(r.data['pecas'][1]['vezes'], 1)


class AvisosTests(Base):
    def test_nova_avisa_compras_e_mudanca_avisa_quem_pediu(self):
        gestor = User.objects.create(username='gestor')
        gestor.groups.add(Group.objects.get_or_create(name='comprasGestor')[0])
        sol = self.solicitar(urgente=True)
        n = NotificacaoPecas.objects.filter(usuario=self.comprador).get()
        self.assertEqual(n.tipo, 'URGENTE')
        self.assertTrue(NotificacaoPecas.objects.filter(usuario=gestor).exists())
        self.assertFalse(NotificacaoPecas.objects.filter(usuario=self.oficina).exists())
        self.cli(self.comprador).patch(f'{BASE}solicitacoes/{sol["id"]}/', {'status': 'em_compra', 'resposta': 'OC 1234'},
                                       format='json')
        aviso = NotificacaoPecas.objects.get(usuario=self.oficina)
        self.assertEqual(aviso.tipo, 'STATUS')
        self.assertIn('Em compra — OC 1234', aviso.mensagem)
        r = self.cli(self.oficina).get(f'{BASE}notificacoes/')
        self.assertEqual((len(r.data), r.data[0]['lido']), (1, False))
        self.cli(self.oficina).post(f'{BASE}notificacoes/marcar_como_lido/', {'notificacao_ids': 'todas'}, format='json')
        self.assertTrue(NotificacaoPecas.objects.get(usuario=self.oficina).lido)
        # só recado, sem mudar situação
        self.cli(self.comprador).patch(f'{BASE}solicitacoes/{sol["id"]}/', {'resposta': 'chega dia 05'}, format='json')
        self.assertEqual(NotificacaoPecas.objects.filter(usuario=self.oficina).first().tipo, 'RESPOSTA')

    def test_cancelamento_avisa_quem_tratava(self):
        sol = self.solicitar()
        self.cli(self.comprador).patch(f'{BASE}solicitacoes/{sol["id"]}/', {'resposta': 'vendo'}, format='json')
        self.cli(self.oficina).patch(f'{BASE}solicitacoes/{sol["id"]}/', {'status': 'cancelada'}, format='json')
        self.assertEqual(NotificacaoPecas.objects.filter(usuario=self.comprador).first().tipo, 'CANCELADA')

    @override_settings(PECAS_WHATSAPP_TEMPLATE='pecas_oficina_aviso')
    def test_whatsapp_so_para_quem_pediu(self):
        r = self.cli(self.comprador).put(f'{BASE}preferencias/', {'whatsapp': '(51) 99999-0000', 'avisar_whatsapp': True},
                                         format='json')
        self.assertEqual((r.status_code, r.data['whatsapp'], r.data['whatsapp_disponivel']), (200, '51999990000', True))
        with mock.patch('catalogos.tasks.whatsapp_notificacao_pecas.delay', side_effect=po.enviar_whatsapp), \
                mock.patch('whatsapp.graph_api.enviar_template') as envio, \
                self.captureOnCommitCallbacks(execute=True):
            self.solicitar()
        envio.assert_called_once()
        self.assertEqual(envio.call_args[0][:2], ('51999990000', 'pecas_oficina_aviso'))

    def test_preferencia_valida_celular(self):
        url = f'{BASE}preferencias/'
        self.assertEqual(self.cli(self.oficina).put(url, {'whatsapp': '123', 'avisar_whatsapp': False}, format='json').status_code, 400)
        self.assertEqual(self.cli(self.oficina).put(url, {'whatsapp': '', 'avisar_whatsapp': True}, format='json').status_code, 400)
        self.assertFalse(self.cli(self.oficina).get(url).data['whatsapp_disponivel'])


class RevisaoIdentificarTests(Base):
    def test_faixas_de_texto(self):
        self.assertEqual(po.faixas_de_texto('233, 269-301'), [[233, 233], [269, 301]])
        self.assertEqual(po.faixas_de_texto([[301, 269]]), [[269, 301]])
        self.assertEqual(po.faixas_de_texto(''), [])

    def test_editar_tabela_e_conjunto(self):
        cli = self.cli(self.oficina)
        linhas = [{'id': self.p1.id, 'fig': '1', 'codigo': '218004461', 'quantidade': '1', 'descricao': 'CAPO',
                   'faixas': '233, 269-301'},
                  {'fig': '3', 'codigo': 'N1', 'quantidade': '2', 'descricao': 'NOVA', 'nota': 'VER 3A001 13.0', 'faixas': ''}]
        r = cli.put(f'{BASE}conjuntos/{self.cj.id}/pecas/', {'pecas': linhas}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([p['descricao'] for p in r.data['pecas']], ['CAPO', 'NOVA'])
        self.assertFalse(PecaCatalogo.objects.filter(pk=self.p2.id).exists())
        self.assertEqual(PecaCatalogo.objects.get(pk=self.p1.id).faixas, [[233, 233], [269, 301]])
        self.assertEqual(PecaCatalogo.objects.get(descricao='NOVA').ver, '3A001 13.0')
        self.assertEqual(r.data['marcadores'][0]['fig'], '1')
        outro = ConjuntoPecas.objects.create(catalogo=self.cat, codigo='3A001 13.0', nome='FILTRO', pagina=3)
        self.assertEqual(cli.patch(f'{BASE}conjuntos/{outro.id}/', {'codigo': '2A300 00.0'}, format='json').status_code, 400)
        self.assertEqual(cli.patch(f'{BASE}conjuntos/{outro.id}/', {'nome': 'FILTRO AR'}, format='json').data['nome'], 'FILTRO AR')
        self.assertEqual(self.cli(self.comprador).delete(f'{BASE}conjuntos/{outro.id}/').status_code, 403)
        self.assertEqual(cli.delete(f'{BASE}conjuntos/{outro.id}/').status_code, 204)

    def test_revisao_e_publicar(self):
        self.cat.status, self.cat.origem = 'revisao', 'ia'
        self.cat.save()
        r = self.cli(self.oficina).get(f'{BASE}catalogos/{self.cat.id}/revisao/')
        self.assertEqual(len(r.data['conjuntos_revisao'][0]['pecas']), 2)
        r = self.cli(self.oficina).post(f'{BASE}catalogos/{self.cat.id}/publicar/')
        self.assertEqual(r.data['status'], 'pronto')

    def test_ligar_recusa_catalogo_sem_pecas(self):
        vazio = CatalogoPecas.objects.create(nome='Vazio', status='erro')
        r = self.cli(self.oficina).put(f'{BASE}equipamentos/528/', {'catalogo': vazio.id}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_identificar_sem_ia_busca_pelo_texto(self):
        url = f'{BASE}catalogos/{self.cat.id}/identificar/'
        r = self.cli(self.oficina).post(url, {'texto': 'filtro do ar'}, format='multipart')
        self.assertEqual((r.status_code, r.data['ia']), (200, False))
        self.assertEqual(r.data['pecas'][0]['codigo'], '370500999')
        foto = SimpleUploadedFile('p.jpg', b'\xff\xd8\xff', content_type='image/jpeg')
        r = self.cli(self.oficina).post(url, {'foto': foto}, format='multipart')
        self.assertIn('não está configurada', r.data['aviso'])
        self.assertEqual(self.cli(self.oficina).post(url, {}, format='multipart').status_code, 400)

    def test_identificar_com_ia(self):
        url = f'{BASE}catalogos/{self.cat.id}/identificar/'
        resp = {'descricao': 'Capô do motor', 'codigos_lidos': ['218004461'], 'palavras_chave': ['FILTRO'],
                'conjuntos': [{'codigo': '2A300 00.0', 'motivo': 'capô'}]}
        foto = SimpleUploadedFile('p.png', b'\x89PNG', content_type='image/png')
        with mock.patch.object(pecas_ia, 'configurada', return_value=True), \
                mock.patch.object(pecas_ia, 'identificar', return_value=resp):
            r = self.cli(self.oficina).post(url, {'foto': foto}, format='multipart')
        self.assertTrue(r.data['ia'])
        self.assertEqual(r.data['pecas'][0]['codigo'], '218004461')  # código lido pesa mais que palavra
        self.assertEqual(r.data['conjuntos'][0]['id'], self.cj.id)
        txt = SimpleUploadedFile('p.txt', b'x', content_type='text/plain')
        self.assertEqual(self.cli(self.oficina).post(url, {'foto': txt}, format='multipart').status_code, 400)
