"""26/11/2026 — Peças da Oficina: leitura do catálogo do fabricante e solicitações do chefe da oficina."""
import importlib
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth.models import Group, User
from django.test import TestCase
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
