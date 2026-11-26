"""26/11/2026 — Peças da Oficina: leitura do catálogo do fabricante e solicitações do chefe da oficina."""
import importlib
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from catalogos import pecas_catalogo as pc
from catalogos import pecas_oficina as po
from catalogos.models import (CatalogoPecas, ConjuntoPecas, EquipamentoPecas, ItemErpCatalogo, PecaCatalogo,
                              SolicitacaoPecas)

BASE = '/catalogos/pecas-oficina/'


def _w(x, y, t, larg=None):
    x2 = x + (larg or 5 * len(t))
    return f'<word xMin="{x}" yMin="{y}" xMax="{x2}" yMax="{y + 9}">{t}</word>'


def _pagina(conjunto='2A300 00.0', nome='CAPO DO MOTOR - COMPONENTES', linhas=()):
    cab = [_w(144, 30, 'RK'), _w(168, 30, '430M'), _w(208, 30, 'DC13')]
    cod, sufixo = conjunto.split(' ')
    cab += [_w(488, 38, cod), _w(534, 38, sufixo)]
    x = 144
    for palavra in nome.split(' '):
        cab.append(_w(x, 48, palavra))
        x += 6 * len(palavra) + 4
    col = {'fig': 34, 'codigo': 64, 'qtd': 129, 'descricao': 180, 'nota': 330, 'inicio': 480, 'fim': 520}
    cab += [_w(34, 459, 'Fig.'), _w(64, 459, 'Código'), _w(129, 459, 'Qtd'), _w(180, 459, 'Descrição'),
            _w(230, 459, '(português)'), _w(330, 459, 'Nota'), _w(480, 459, 'Início'), _w(520, 459, 'Fim')]
    y = 482
    for linha in linhas:
        for c, txt in linha.items():
            xx = col[c]
            for palavra in txt.split(' '):
                cab.append(_w(xx, y, palavra))
                xx += 6 * len(palavra) + 4
        y += 12
    cab.append(_w(150, 760, 'Catálogo'))
    cab.append(_w(200, 760, 'de'))
    return f'<page width="612.000000" height="792.000000">{"".join(cab)}</page>'


def _indice():
    return ('<page width="612.000000" height="792.000000">' + _w(100, 100, 'Índice') + _w(100, 120, 'MONTAGEM')
            + '</page>')


class LeituraCatalogoTests(TestCase):
    def test_le_pagina_junta_faixas_e_continuacao(self):
        p1 = _pagina(linhas=[
            {'fig': '0', 'codigo': '218004461', 'qtd': '01', 'descricao': 'CAPO COMPLETO', 'inicio': '233', 'fim': '233'},
            {'fig': '0', 'codigo': '218004461', 'qtd': '01', 'descricao': 'CAPO COMPLETO', 'inicio': '269', 'fim': '301'},
            {'fig': '4', 'qtd': '06', 'descricao': 'ARRUELA PRESS?O', 'inicio': '233', 'fim': '233'},
            {'fig': '13', 'codigo': 'V218004412', 'qtd': '01', 'descricao': 'CARCACA FILTRO', 'nota': 'VER 3A001 13.0',
             'inicio': '233', 'fim': '233'},
            {'descricao': 'COMPLETA'},
        ])
        p2 = _pagina(linhas=[
            {'fig': '14', 'codigo': '100000075756', 'qtd': 'CN', 'descricao': 'TAMPA SUPERIOR', 'inicio': '269', 'fim': '301'},
        ])
        cat = pc.montar_catalogo(pc.ler_paginas_xml(_indice() + p1 + p2 + _pagina('3A001 13.0', 'FILTRO')))
        self.assertEqual(cat['modelo'], 'RK 430M DC13')
        self.assertEqual(list(cat['conjuntos']), ['2A300 00.0', '3A001 13.0'])
        cj = cat['conjuntos']['2A300 00.0']
        self.assertEqual(cj['nome'], 'CAPO DO MOTOR - COMPONENTES')
        self.assertEqual((cj['pagina'], cj['paginas']), (2, [2, 3]))
        pecas = cj['pecas']
        self.assertEqual(len(pecas), 4)
        self.assertEqual(pecas[0]['faixas'], [[233, 233], [269, 301]])
        self.assertEqual(pecas[1]['descricao'], 'ARRUELA PRESSÃO')
        self.assertEqual(pecas[1]['codigo'], '')
        self.assertEqual(pecas[2]['descricao'], 'CARCACA FILTRO COMPLETA')
        self.assertEqual(pecas[2]['ver'], '3A001 13.0')
        self.assertEqual((pecas[3]['codigo'], pecas[3]['qtd']), ('100000075756', 'CN'))

    def test_codigo_do_conjunto_com_ponto(self):
        self.assertEqual(pc.normalizar_codigo_conjunto('1A100.00.2'), '1A100 00.2')

    def test_vale_para_serie(self):
        self.assertTrue(pc.vale_para_serie([[233, 233]], None))
        self.assertTrue(pc.vale_para_serie([], 10))
        self.assertTrue(pc.vale_para_serie([[233, 233], [269, 301]], 280))
        self.assertFalse(pc.vale_para_serie([[233, 233]], 280))

    def test_dados_tecnicos_e_serie_sugerida(self):
        bruto = b'APLICACAO: TRANSPORTE\n\r\n\rNRO SERIE 5A430BSZCB0406\n\rMOTOR SCANIA'
        txt = po.texto_dados(bruto)
        self.assertEqual(txt, 'APLICACAO: TRANSPORTE\nNRO SERIE 5A430BSZCB0406\nMOTOR SCANIA')
        self.assertEqual(po.sugerir_serie(txt), 406)
        self.assertEqual(po.sugerir_serie('CHASSI 41110425'), 425)
        self.assertIsNone(po.sugerir_serie('EMPILHADEIRA LIUGONG'))


class ItensSgaTests(TestCase):
    def test_chaves_do_codigo(self):
        self.assertEqual(po._chaves_codigo('V218004412'), {'V218004412', '218004412'})
        self.assertEqual(po._chaves_codigo('370200202K'), {'370200202K', '370200202'})
        self.assertEqual(po._chaves_codigo('SG/4'), set())

    def test_casa_por_nome_referencia_e_mapeamento_manual(self):
        ItemErpCatalogo.objects.create(cod_erp='999', cod_catalogo='210102404')
        idx = {'208000418': [4809, 20408], '218004412': [77]}
        with mock.patch.object(po, '_indice_sga', return_value=idx):
            r = po.itens_sga(['208000418', 'V218004412', '210102404', '123'])
        self.assertEqual(r, {'208000418': [4809, 20408], 'V218004412': [77], '210102404': [999]})

    def test_indice_pega_codigo_no_nome_sem_pegar_numero_maior(self):
        import pandas as pd
        df = pd.DataFrame([
            {'ESTQCOD': 1, 'ESTQNOME': 'COXIM DIANTEIRO 208000418', 'ESTQREF': ''},
            {'ESTQCOD': 2, 'ESTQNOME': 'PECA 2080004180', 'ESTQREF': ''},
            {'ESTQCOD': 3, 'ESTQNOME': 'BUCHA', 'ESTQREF': '40316'},
            {'ESTQCOD': 5, 'ESTQNOME': 'BUCHA MOLA', 'ESTQREF': '3271/6000'},
            {'ESTQCOD': 4, 'ESTQNOME': 'FILTRO', 'ESTQREF': 'V218004412'},
        ])
        with mock.patch.object(po.ax, '_ler', return_value=df), \
                mock.patch.object(po.ax, '_cacheado', side_effect=lambda k, s, f: f()):
            idx = po._indice_sga()
        self.assertEqual(idx['208000418'], [1])
        self.assertEqual(idx['2080004180'], [2])
        self.assertNotIn('40316', idx)  # referência curta (menos de 6) não entra
        self.assertEqual(idx['3271/6000'], [5])
        self.assertEqual(idx['V218004412'], [4])
        self.assertEqual(idx['218004412'], [4])


EQUIPS = [
    {'codigo': 528, 'nome': 'VEC-CF-07 - CAMINHAO FORA EST RK 430B', 'tag': 'VEC-CF-07', 'tipo': 'VEICULOS PESADOS',
     'dados': 'NRO SERIE 5A430BSZCB0406', 'serie_sugerida': 406},
    {'codigo': 917, 'nome': 'VEC-EC-15 - EMPILHADEIRA', 'tag': 'VEC-EC-15', 'tipo': 'EMPILHADEIRA', 'dados': '',
     'serie_sugerida': None},
]


class SolicitacoesTests(TestCase):
    def setUp(self):
        self.oficina = User.objects.create(username='oficina', first_name='Chefe', last_name='Oficina')
        self.oficina.groups.add(Group.objects.get_or_create(name='comprasOficina')[0])
        self.comprador = User.objects.create(username='comprador')
        self.comprador.groups.add(Group.objects.get_or_create(name='comprasComprador')[0])
        self.pesada = User.objects.create(username='pesada')
        self.pesada.groups.add(Group.objects.get_or_create(name='comprasPesada')[0])
        self.cat = CatalogoPecas.objects.create(nome='RK 430M DC13', fabricante='Randon')
        self.cj = ConjuntoPecas.objects.create(catalogo=self.cat, codigo='2A300 00.0', nome='CAPO', pagina=60)
        self.sub = ConjuntoPecas.objects.create(catalogo=self.cat, codigo='3A001 13.0', nome='FILTRO', pagina=90,
                                                ordem=1)
        ConjuntoPecas.objects.create(catalogo=self.cat, codigo='1A000 00.1', nome='CHASSI SÉRIE 233', pagina=23, ordem=2)
        self.p1 = PecaCatalogo.objects.create(conjunto=self.cj, fig='0', codigo='218004461', quantidade='01',
                                              descricao='CAPO COMPLETO', faixas=[[233, 233], [269, 301]])
        self.p2 = PecaCatalogo.objects.create(conjunto=self.cj, fig='13', codigo='V218004412', quantidade='01',
                                              descricao='CARCACA FILTRO', ver='3A001 13.0', faixas=[[233, 233]], ordem=1)
        PecaCatalogo.objects.create(conjunto=self.cj.catalogo.conjuntos.get(codigo='1A000 00.1'), fig='1',
                                    codigo='370400703', quantidade='01', descricao='CHASSI', faixas=[[233, 233]])
        self.patches = [
            mock.patch.object(po, 'equipamentos_sga', return_value=EQUIPS),
            mock.patch.object(po, '_indice_sga', return_value={'218004461': [4809]}),
            mock.patch.object(po, '_situacao_itens', side_effect=lambda cods: {
                c: {'codigo': c, 'nome': 'CAPO', 'saldo': 2.0, 'situacao': 'ok', 'em_compra': False} for c in cods}),
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

    def test_acesso_por_grupo(self):
        self.assertEqual(self.cli(self.pesada).get(BASE).status_code, 403)
        r = self.cli(self.oficina).get(BASE)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['pode_pedir'], r.data['pode_ligar'], r.data['pode_tratar']), (True, True, False))
        self.assertEqual(r.data['catalogos'][0]['conjuntos'], 3)
        r = self.cli(self.comprador).get(BASE)
        self.assertEqual((r.data['pode_pedir'], r.data['pode_ligar'], r.data['pode_tratar']), (False, False, True))

    def test_ligar_equipamento_e_filtrar_pela_serie(self):
        r = self.cli(self.comprador).put(f'{BASE}equipamentos/528/', {'catalogo': self.cat.id, 'serie': 280}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.cli(self.oficina).put(f'{BASE}equipamentos/528/', {'catalogo': self.cat.id, 'serie': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.cli(self.oficina).put(f'{BASE}equipamentos/528/', {'catalogo': self.cat.id, 'serie': 280}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['catalogo'], r.data['serie']), (self.cat.id, 280))
        self.assertEqual(EquipamentoPecas.objects.get(equipamento=528).nome, EQUIPS[0]['nome'])
        lista = self.cli(self.oficina).get(f'{BASE}equipamentos/').data
        self.assertEqual(lista[0]['codigo'], 528)  # ligado primeiro
        # Índice: o conjunto só da série 233 some para a 280
        todos = self.cli(self.oficina).get(f'{BASE}catalogos/{self.cat.id}/conjuntos/').data['conjuntos']
        s280 = self.cli(self.oficina).get(f'{BASE}catalogos/{self.cat.id}/conjuntos/', {'serie': 280}).data['conjuntos']
        self.assertEqual(len(todos), 3)
        self.assertEqual([c['codigo'] for c in s280], ['2A300 00.0', '3A001 13.0'])
        # Conjunto: a linha da faixa 233 some; item do SGA sugerido com saldo
        cj = self.cli(self.oficina).get(f'{BASE}conjuntos/{self.cj.id}/', {'serie': 280}).data
        self.assertEqual([p['codigo'] for p in cj['pecas']], ['218004461'])
        self.assertEqual(cj['pecas'][0]['sga'][0]['codigo'], 4809)
        cj = self.cli(self.oficina).get(f'{BASE}conjuntos/{self.cj.id}/').data
        self.assertEqual(cj['pecas'][1]['ver_id'], self.sub.id)
        # Série fora das faixas do catálogo (RK 430B nº 406 num catálogo 233/269–301): mostra tudo e avisa
        r = self.cli(self.oficina).get(f'{BASE}catalogos/{self.cat.id}/conjuntos/', {'serie': 406}).data
        self.assertEqual((r['serie_fora'], r['faixas'], len(r['conjuntos'])), (True, [[233, 233], [269, 301]], 3))
        cj = self.cli(self.oficina).get(f'{BASE}conjuntos/{self.cj.id}/', {'serie': 406}).data
        self.assertEqual(len(cj['pecas']), 2)

    def test_busca_por_codigo_e_por_palavra(self):
        r = self.cli(self.oficina).get(f'{BASE}catalogos/{self.cat.id}/busca/', {'q': '218004412'}).data
        self.assertEqual([p['codigo'] for p in r], ['V218004412'])
        r = self.cli(self.oficina).get(f'{BASE}catalogos/{self.cat.id}/busca/', {'q': 'capo comp'}).data
        self.assertEqual([p['codigo'] for p in r], ['218004461'])
        self.assertEqual(r[0]['conjunto_codigo'], '2A300 00.0')

    def test_fluxo_da_solicitacao(self):
        EquipamentoPecas.objects.create(equipamento=528, catalogo=self.cat, serie=280)
        dados = {'equipamento': 528, 'urgente': True, 'observacao': 'Parado',
                 'itens': [{'peca': self.p1.id, 'quantidade': 1, 'item_sga': 4809},
                           {'descricao': 'Lâmpada farol', 'codigo': '', 'quantidade': '2,5'}]}
        self.assertEqual(self.cli(self.comprador).post(f'{BASE}solicitacoes/', dados, format='json').status_code, 403)
        self.assertEqual(self.cli(self.oficina).post(f'{BASE}solicitacoes/', {**dados, 'itens': []},
                                                     format='json').status_code, 400)
        r = self.cli(self.oficina).post(f'{BASE}solicitacoes/', dados, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data['numero'], r.data['serie'], r.data['solicitante']), (1, 280, 'Chefe Oficina'))
        self.assertEqual(r.data['itens'][0]['conjunto'], '2A300 00.0 CAPO · fig. 0')
        self.assertEqual(r.data['itens'][1]['quantidade'], 2.5)
        r2 = self.cli(self.oficina).post(f'{BASE}solicitacoes/', dados, format='json')
        self.assertEqual(r2.data['numero'], 2)
        sid = r.data['id']
        # chefe não muda a situação, comprador sim
        self.assertEqual(self.cli(self.oficina).patch(f'{BASE}solicitacoes/{sid}/', {'status': 'atendida'},
                                                      format='json').status_code, 403)
        r = self.cli(self.comprador).patch(f'{BASE}solicitacoes/{sid}/', {'status': 'em_compra', 'resposta': 'OC 1234'},
                                           format='json')
        self.assertEqual((r.status_code, r.data['status'], r.data['resposta']), (200, 'em_compra', 'OC 1234'))
        self.assertEqual(r.data['itens'][0]['sga']['saldo'], 2.0)
        # já em compra: o chefe não cancela mais; a 2ª (aberta) ele cancela
        self.assertEqual(self.cli(self.oficina).patch(f'{BASE}solicitacoes/{sid}/', {'status': 'cancelada'},
                                                      format='json').status_code, 403)
        r = self.cli(self.oficina).patch(f"{BASE}solicitacoes/{r2.data['id']}/", {'status': 'cancelada'}, format='json')
        self.assertEqual(r.data['status'], 'cancelada')
        abertas = self.cli(self.comprador).get(f'{BASE}solicitacoes/', {'status': 'abertas'}).data
        self.assertEqual([s['numero'] for s in abertas], [1])

    def test_equipamento_inexistente(self):
        r = self.cli(self.oficina).post(f'{BASE}solicitacoes/', {'equipamento': 1, 'itens': [
            {'descricao': 'x', 'quantidade': 1}]}, format='json')
        self.assertEqual(r.status_code, 400)


class MigrationTests(TestCase):
    def test_cria_grupo(self):
        mig = importlib.import_module('catalogos.migrations.0016_pecas_oficina')
        Group.objects.filter(name='comprasOficina').delete()
        mig.criar_grupo(django_apps, None)
        self.assertTrue(Group.objects.filter(name='comprasOficina').exists())


PDF_FALSO = b'%PDF-1.4 catalogo de teste'


def _ler_pdf_falso(_caminho):
    return pc.ler_paginas_xml(_pagina(linhas=[
        {'fig': '0', 'codigo': '218004461', 'qtd': '01', 'descricao': 'CAPO COMPLETO', 'inicio': '233', 'fim': '233'},
    ]))


def _desenho_falso(_pdf, _pagina, _larg, _y, destino):
    Path(destino).write_bytes(b'jpg')


class EnvioCatalogoTests(TestCase):
    """26/11/2026 — o PDF do catálogo sobe pela tela e é lido em segundo plano."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.oficina = User.objects.create(username='oficina')
        self.oficina.groups.add(Group.objects.get_or_create(name='comprasOficina')[0])
        self.comprador = User.objects.create(username='comprador')
        self.comprador.groups.add(Group.objects.get_or_create(name='comprasComprador')[0])
        self.patches = [
            mock.patch.object(po, 'PASTA', Path(self.tmp)),
            mock.patch.object(pc, 'tem_poppler', return_value=True),
            # O .env local tem a IA configurada: teste nunca chama a API de verdade.
            mock.patch.object(po.pecas_ia, 'configurada', return_value=False),
            mock.patch.object(po.pecas_ocr, 'tem_tesseract', return_value=False),
            mock.patch.object(pc, 'ler_pdf', side_effect=_ler_pdf_falso),
            mock.patch.object(pc, 'renderizar_desenho', side_effect=_desenho_falso),
            # Celery síncrono: o .delay roda a importação na hora.
            mock.patch('catalogos.tasks.importar_catalogo_pecas.delay', side_effect=po.executar_importacao),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c

    def enviar(self, u, url=f'{BASE}catalogos/', conteudo=PDF_FALSO, **campos):
        arq = SimpleUploadedFile('RK430.pdf', conteudo, content_type='application/pdf')
        with self.captureOnCommitCallbacks(execute=True):
            return self.cli(u).post(url, {'pdf': arq, **campos}, format='multipart')

    def test_envia_e_importa_em_segundo_plano(self):
        r = self.enviar(self.oficina, fabricante='Randon')
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.data['status'], 'importando')
        cat = CatalogoPecas.objects.get(pk=r.data['id'])
        self.assertEqual((cat.status, cat.nome, cat.fabricante, cat.erro), ('pronto', 'RK 430M DC13', 'Randon', ''))
        self.assertEqual(cat.conjuntos.count(), 1)
        self.assertTrue(cat.conjuntos.get().desenho)
        self.assertFalse((Path(self.tmp) / str(cat.pk) / 'enviado.pdf').exists())
        self.assertTrue((Path(self.tmp) / str(cat.pk) / 'catalogo.pdf').exists())
        lista = self.cli(self.oficina).get(f'{BASE}catalogos/').data
        self.assertEqual((lista[0]['status'], lista[0]['conjuntos']), ('pronto', 1))
        self.assertTrue(self.cli(self.oficina).get(BASE).data['pode_importar'])

    def test_quem_pode_e_o_que_aceita(self):
        self.assertEqual(self.enviar(self.comprador).status_code, 403)
        self.assertFalse(self.cli(self.comprador).get(BASE).data['pode_importar'])
        r = self.enviar(self.oficina, conteudo=b'nao sou pdf')
        self.assertEqual((r.status_code, r.data['erro']), (400, 'O arquivo não é um PDF.'))
        r = self.cli(self.oficina).post(f'{BASE}catalogos/', {}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(CatalogoPecas.objects.exists())

    def test_pdf_sem_pagina_de_pecas_vira_erro(self):
        with mock.patch.object(pc, 'ler_pdf', return_value=pc.ler_paginas_xml(_indice())):
            r = self.enviar(self.oficina, nome='Volvo A30')
        cat = CatalogoPecas.objects.get(pk=r.data['id'])
        self.assertEqual((cat.status, cat.nome), ('erro', 'Volvo A30'))
        self.assertIn('Nenhuma página de peças', cat.erro)

    def test_nova_edicao_que_falha_mantem_a_anterior(self):
        cat = CatalogoPecas.objects.get(pk=self.enviar(self.oficina).data['id'])
        with mock.patch.object(pc, 'ler_pdf', side_effect=RuntimeError('pdf quebrado')):
            r = self.enviar(self.oficina, url=f'{BASE}catalogos/{cat.pk}/pdf/', edicao='2020')
        self.assertEqual(r.status_code, 202)
        cat.refresh_from_db()
        self.assertEqual((cat.status, cat.erro, cat.edicao), ('pronto', 'Não foi possível ler este PDF.', '2020'))
        self.assertEqual(cat.conjuntos.count(), 1)

    def test_celery_fora_le_numa_thread(self):
        class ThreadNaHora:
            def __init__(self, target, args, daemon):
                self.target, self.args = target, args

            def start(self):
                self.target(*self.args)

        with mock.patch('catalogos.tasks.importar_catalogo_pecas.delay', side_effect=ConnectionError('redis')), \
                mock.patch.object(po.threading, 'Thread', ThreadNaHora):
            r = self.enviar(self.oficina)
        self.assertEqual(CatalogoPecas.objects.get(pk=r.data['id']).status, 'pronto')

    def test_importacao_travada_libera_reenvio(self):
        cat = CatalogoPecas.objects.create(nome='X', status='importando',
                                           enviado_em=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.cli(self.oficina).get(f'{BASE}catalogos/').data[0]['status'], 'erro')
        self.assertEqual(self.enviar(self.oficina, url=f'{BASE}catalogos/{cat.pk}/pdf/').status_code, 202)
        recente = CatalogoPecas.objects.create(nome='Y', status='importando', enviado_em=timezone.now())
        r = self.enviar(self.oficina, url=f'{BASE}catalogos/{recente.pk}/pdf/')
        self.assertEqual(r.status_code, 400)

    def test_renomeia_e_exclui(self):
        cat = CatalogoPecas.objects.get(pk=self.enviar(self.oficina).data['id'])
        EquipamentoPecas.objects.create(equipamento=528, catalogo=cat, serie=300)
        r = self.cli(self.oficina).patch(f'{BASE}catalogos/{cat.pk}/', {'nome': 'RK 430M', 'edicao': '2014'},
                                         format='json')
        self.assertEqual((r.status_code, r.data['nome'], r.data['edicao']), (200, 'RK 430M', '2014'))
        self.assertEqual(self.cli(self.oficina).patch(f'{BASE}catalogos/{cat.pk}/', {'nome': ' '},
                                                      format='json').status_code, 400)
        self.assertEqual(self.cli(self.comprador).delete(f'{BASE}catalogos/{cat.pk}/').status_code, 403)
        self.assertEqual(self.cli(self.oficina).delete(f'{BASE}catalogos/{cat.pk}/').status_code, 204)
        self.assertFalse((Path(self.tmp) / str(cat.pk)).exists())
        self.assertIsNone(EquipamentoPecas.objects.get(equipamento=528).catalogo)
