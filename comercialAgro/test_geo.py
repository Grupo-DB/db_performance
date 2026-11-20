import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
from django.contrib.auth.models import Group, User
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from . import geo
from .models import AreaPlantada, Contato, ImovelCar, Produtor, VendedorAgro

# Quadrado de 0,01° com furo de 0,004° no meio (lng, lat).
QUADRADO = {'type': 'MultiPolygon', 'coordinates': [[
    [[-53.0, -30.0], [-52.99, -30.0], [-52.99, -30.01], [-53.0, -30.01], [-53.0, -30.0]],
    [[-52.997, -30.003], [-52.993, -30.003], [-52.993, -30.007], [-52.997, -30.007], [-52.997, -30.003]],
]]}


def feature(cod, area, geom=QUADRADO, mun=4303004):
    return {'type': 'Feature', 'geometry': geom, 'properties': {
        'cod_imovel': cod, 'area': area, 'municipio': 'Cachoeira do Sul', 'cod_municipio_ibge': mun,
        'm_fiscal': area / 20, 'status_imovel': 'AT', 'tipo_imovel': 'IRU'}}


class GeoTests(SimpleTestCase):
    def test_ler_pam_ignora_vazios(self):
        dados = [{'cab': 1},
                 {'V': '32000', 'D1C': '4300034', 'D1N': 'Aceguá - RS', 'D3C': '2025', 'D4C': '40124', 'D4N': 'Soja'},
                 {'V': '-', 'D1C': '4300034', 'D1N': 'Aceguá - RS', 'D3C': '2025', 'D4C': '40127', 'D4N': 'Trigo'},
                 {'V': '...', 'D1C': '4300035', 'D1N': 'X - RS', 'D3C': '2025', 'D4C': '40124', 'D4N': 'Soja'}]
        self.assertEqual(geo.ler_pam(dados), [{'ano': 2025, 'municipio_ibge': 4300034, 'municipio': 'Aceguá',
                                               'cultura': 'Soja', 'hectares': 32000.0}])
        self.assertEqual(geo.potencial_t(32000), 16000.0)

    def test_dentro_respeita_furo_e_centroide(self):
        px = np.array([-52.999, -52.995, -52.98])
        py = np.array([-30.001, -30.005, -30.005])
        self.assertEqual(geo.dentro(px, py, QUADRADO).tolist(), [True, False, False])
        lat, lng = geo.centroide(QUADRADO)
        self.assertAlmostEqual(lat, -30.005, places=6)
        self.assertAlmostEqual(lng, -52.995, places=6)

    def test_simplificar_mantem_cantos(self):
        linha = [[-53.0 + i * 0.0001, -30.0 + (0.00001 if i % 2 else 0)] for i in range(50)]
        poly = {'type': 'Polygon', 'coordinates': [linha + [[-53.0, -30.01], linha[0]]]}
        s = geo.simplificar(poly)
        self.assertLessEqual(len(s['coordinates'][0][0]), 5)
        self.assertEqual(geo.simplificar(QUADRADO)['coordinates'][0][0][0], [-53.0, -30.0])

    def test_imovel_arredonda_e_calcula_centro(self):
        im = geo.imovel(feature('RS-1', 112.3456))
        self.assertEqual((im['codigo'], im['area_ha'], im['municipio_ibge']), ('RS-1', 112.35, 4303004))
        self.assertEqual(im['latitude'], -30.005)

    def test_mapa_lavoura_metade(self):
        # Grade de 0,0005° (20×20 px cobrindo o quadrado); metade esquerda é lavoura.
        with tempfile.TemporaryDirectory() as d:
            m = np.zeros((20, 20), dtype=bool)
            m[:, :10] = True
            np.save(Path(d) / 'lavoura.npy', np.packbits(m, axis=1))
            (Path(d) / 'lavoura.json').write_text(json.dumps(
                {'ano': 2024, 'x0': -53.0, 'dx': 0.0005, 'y0': -30.0, 'dy': -0.0005, 'largura': 20, 'altura': 20}))
            mapa = geo.MapaLavoura(Path(d))
            frac, pct = mapa.lavoura(QUADRADO)
            self.assertAlmostEqual(frac, 0.5, places=2)  # o furo é simétrico
            im = geo.com_lavoura({'area_ha': 100.0, 'geometria': QUADRADO}, mapa)
            self.assertEqual((im['lavoura_ha'], im['lavoura_pct'], im['lavoura_ano']), (50.0, 50.0, 2024))
            fora = {'type': 'Polygon', 'coordinates': [[[-60, -20], [-59, -20], [-59, -21], [-60, -20]]]}
            self.assertIsNone(mapa.lavoura(fora))


@mock.patch('comercialAgro.erp_agro.ultimas_compras', side_effect=lambda cods: {4849: date.today(), 5000: date(2023, 3, 1)})
class DadosPublicosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('paulo')
        self.vend = VendedorAgro.objects.create(user=self.user, repcods=[82])
        self.gestor = User.objects.create_user('lucas')
        self.gestor.groups.add(Group.objects.get_or_create(name='agroGestor')[0])

    def cli(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c

    def test_mercado(self, *_):
        AreaPlantada.objects.create(ano=2025, municipio_ibge=4303004, municipio='Cachoeira do Sul', cultura='Soja', hectares=100000)
        AreaPlantada.objects.create(ano=2025, municipio_ibge=4303004, municipio='Cachoeira do Sul', cultura='Arroz', hectares=20000)
        AreaPlantada.objects.create(ano=2025, municipio_ibge=4300034, municipio='Aceguá', cultura='Soja', hectares=32000)
        AreaPlantada.objects.create(ano=2025, municipio_ibge=3100104, municipio='Abadia dos Dourados', cultura='Café', hectares=1000)
        AreaPlantada.objects.create(ano=2025, municipio_ibge=3100104, municipio='Abadia dos Dourados', cultura='Milho 2ª safra', hectares=10)
        self.semrede = [mock.patch('comercialAgro.erp_agro.vendas_mensais', return_value=[]),
                        mock.patch('comercialAgro.views._pedreiras', return_value=[]),
                        mock.patch('comercialAgro.geo.baixar_pam', side_effect=AssertionError('não devia baixar'))]
        for m in self.semrede:
            m.start()
            self.addCleanup(m.stop)
        vendas = {4303004: {'clientes': 12, 'toneladas': 15000.0, 'valor': 1.0}, 4205407: {'clientes': 1, 'toneladas': 900.0, 'valor': 1.0}}
        with mock.patch('comercialAgro.erp_agro.vendas_por_municipio', return_value=vendas) as vm:
            r = self.cli(self.gestor).get('/comercialAgro/mercado/')
            self.assertIsNone(vm.call_args.args[2])  # gestor vê a empresa toda
            self.cli(self.user).get('/comercialAgro/mercado/')
            self.assertEqual(vm.call_args.args[2], [82])  # vendedor vê o que é dele
        cach = next(m for m in r.data['municipios'] if m['ibge'] == 4303004)
        self.assertEqual((cach['potencial_t'], cach['vendido_t'], cach['participacao'], cach['a_ganhar_t']),
                         (60000.0, 15000.0, 25.0, 45000.0))
        self.assertEqual(r.data['totais']['vendido_fora_rs_t'], 900)
        self.assertEqual(r.data['municipios'][0]['ibge'], 4303004)  # maior a ganhar primeiro
        self.assertNotIn(3100104, [m['ibge'] for m in r.data['municipios']])  # MG fora da visão do RS

        # Brasil: uma linha por estado, com os hectares de cada município por cultura em `partes`.
        with mock.patch('comercialAgro.erp_agro.vendas_por_municipio', return_value=vendas):
            r = self.cli(self.gestor).get('/comercialAgro/mercado/?uf=BR')
        por = {e['sigla']: e for e in r.data['municipios']}
        self.assertEqual(set(por), {'RS', 'MG', 'SC'})  # SC só tem venda
        rs = por['RS']
        self.assertEqual((rs['hectares'], rs['vendido_t'], rs['clientes'], rs['municipios'], len(rs['partes'])), (152000, 15000.0, 12, 2, 2))
        soja = r.data['culturas'].index('Soja')
        self.assertEqual(sorted(p[soja] for p in rs['partes']), [32000, 100000])
        self.assertEqual((r.data['uf'], r.data['totais']['vendido_fora_t']), ('BR', 0))

        # Outra UF pela sigla.
        with mock.patch('comercialAgro.erp_agro.vendas_por_municipio', return_value=vendas):
            r = self.cli(self.gestor).get('/comercialAgro/mercado/?uf=mg')
        self.assertEqual(([m['ibge'] for m in r.data['municipios']], r.data['uf_sigla']), ([3100104], 'MG'))

    def test_clientes_do_municipio(self, *_):
        Produtor.objects.create(nome='Tiago', cliente_sga=4849, cadastro='CADASTRADO')
        linhas = [{'cliente': 4849, 'nome': 'TIAGO', 'vendedor': 'X', 'pedidos': 2, 'toneladas': 50.0, 'valor': 1.0, 'ultima': date(2026, 10, 1)}]
        with mock.patch('comercialAgro.erp_agro.clientes_do_municipio', return_value=linhas) as cm:
            r = self.cli(self.user).get('/comercialAgro/mercado/4303004/clientes/')
        self.assertEqual(cm.call_args.args[0], 4303004)
        self.assertEqual(cm.call_args.args[3], [82])  # vendedor só vê os dele
        self.assertEqual(r.data[0]['produtor'], Produtor.objects.get(cliente_sga=4849).id)

    def test_prospeccao_cruza_produtores(self, *_):
        p = Produtor.objects.create(nome='Tiago', cliente_sga=4849, car_codigo='RS-B', cadastro='CADASTRADO')
        Produtor.objects.create(nome='Ernesto', car_codigo='RS-C')
        Produtor.objects.create(nome='Velho', cliente_sga=5000, car_codigo='RS-D', cadastro='CADASTRADO')
        imoveis = [geo.imovel(feature(c, a)) for c, a in (('RS-A', 300), ('RS-B', 900), ('RS-C', 150), ('RS-D', 120))]
        with mock.patch('comercialAgro.geo.car_municipio', return_value=imoveis) as cm:
            r = self.cli(self.user).get('/comercialAgro/prospeccao/?municipio=4303004&min_ha=100')
            self.cli(self.user).get('/comercialAgro/prospeccao/?municipio=4303004&min_ha=100')
            self.assertEqual(cm.call_count, 1)  # segunda vez sai do banco
        self.assertEqual([(i['codigo'], i['situacao']) for i in r.data['imoveis']],
                         [('RS-A', 'livre'), ('RS-D', 'ex_cliente'), ('RS-C', 'conhecido'), ('RS-B', 'cliente')])
        self.assertEqual(r.data['resumo'], {'livre': 1, 'ex_cliente': 1, 'conhecido': 1, 'contato': 0, 'cliente': 1})
        self.assertEqual(r.data['imoveis'][1]['produtor']['ultima_compra'], date(2023, 3, 1))
        self.assertEqual(r.data['imoveis'][3]['produtor']['id'], p.id)

    def test_visita_com_gps_liga_o_car(self, *_):
        p = Produtor.objects.create(nome='Ernesto')
        with mock.patch('comercialAgro.geo.car_no_ponto', return_value=geo.imovel(feature('RS-Z', 947))):
            r = self.cli(self.user).post('/comercialAgro/contatos/', {
                'produtor': p.id, 'tipo': 'VISITA', 'data_hora': '2026-11-19T14:32:00-03:00', 'latitude': '-30.005',
                'longitude': '-52.995', 'resultado': 'INTERESSADO', 'proximo_passo': 'Voltar', 'proximo_data': '2026-12-01'}, format='json')
            self.assertEqual(r.status_code, 201, r.data)
            p.refresh_from_db()
            self.assertEqual(p.car_codigo, 'RS-Z')
            r = self.cli(self.user).get('/comercialAgro/car/ponto/?lat=-30.005&lng=-52.995')
        self.assertEqual((r.data['imovel']['codigo'], r.data['produtor']['id']), ('RS-Z', p.id))
        self.assertTrue(ImovelCar.objects.filter(codigo='RS-Z').exists())


class CamadaCarTests(SimpleTestCase):
    def test_camada_por_uf(self):
        self.assertEqual(geo.camada_car(51), 'sicar:sicar_imoveis_mt')
        self.assertEqual(geo.camada_car(None), 'sicar:sicar_imoveis_rs')
        self.assertEqual(geo.uf_do_codigo_car('MT-5107925-BAFA'), 51)
        self.assertEqual(geo.uf_do_codigo_car('xx'), 43)
        with mock.patch('comercialAgro.geo._wfs', return_value={'features': [], 'numberMatched': 0}) as wfs:
            geo.car_municipio(5107925, 100)
        self.assertEqual(wfs.call_args.kwargs['uf'], 51)

    def test_lavoura_so_no_rs(self):
        mapa = mock.Mock(ano=2024)
        mapa.lavoura.return_value = (0.5, 50.0)
        g = {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        self.assertEqual(geo.com_lavoura({'municipio_ibge': 4303004, 'area_ha': 100, 'geometria': g}, mapa)['lavoura_ha'], 50.0)
        self.assertNotIn('lavoura_ha', geo.com_lavoura({'municipio_ibge': 4205407, 'area_ha': 100, 'geometria': g}, mapa))


class SimuladorTests(TestCase):
    def setUp(self):
        self.gestor = User.objects.create_user('lucas')
        self.gestor.groups.add(Group.objects.get_or_create(name='agroGestor')[0])
        self.c = APIClient()
        self.c.force_authenticate(self.gestor)

    def test_concorrencia_conta_empresas_e_ignora_a_db(self):
        from .views import _concorrencia
        cent = {4303004: (-30.04, -52.89)}  # Cachoeira do Sul
        ped = [{'titular': 'A LTDA', 'latitude': -30.54, 'longitude': -53.41},   # ~75 km
               {'titular': 'A LTDA', 'latitude': -30.55, 'longitude': -53.42},   # mesma empresa
               {'titular': 'B LTDA', 'latitude': -30.32, 'longitude': -52.32},   # ~63 km
               {'titular': 'Dagoberto Barcellos S/A', 'latitude': -30.54, 'longitude': -53.41}]
        with mock.patch('comercialAgro.geo.centroides_municipios', return_value=cent):
            r = _concorrencia([4303004], ped, ['DAGOBERTO BARCELLOS S/A'])
        self.assertEqual(r[4303004], [0, 2, 2, 2, 2])

    def test_revenda_espalha_pelo_raio(self):
        from datetime import date as d
        from .views import _redistribuir_canal
        Produtor.objects.create(nome='Coop', tipo='COOPERATIVA', cliente_sga=77, raio_atuacao_km=100)
        AreaPlantada.objects.create(ano=2025, municipio_ibge=1, municipio='A', cultura='Soja', hectares=300)
        AreaPlantada.objects.create(ano=2025, municipio_ibge=2, municipio='B', cultura='Soja', hectares=100)
        AreaPlantada.objects.create(ano=2025, municipio_ibge=3, municipio='Longe', cultura='Soja', hectares=900)
        cent = {1: (-30.0, -53.0), 2: (-30.3, -53.0), 3: (-25.0, -50.0)}
        vendas = {1: {'clientes': 3, 'toneladas': 1000.0, 'valor': 0}}
        with mock.patch('comercialAgro.geo.centroides_municipios', return_value=cent), \
             mock.patch('comercialAgro.erp_agro.vendas_por_cliente', return_value={77: {'ibge': 1, 'toneladas': 400.0}}):
            v, canal = _redistribuir_canal(vendas, d(2025, 1, 1), d(2026, 1, 1), None, 2025)
        self.assertEqual((round(v[1]['toneladas']), round(v[2]['toneladas']), 3 in v), (900, 100, False))
        self.assertEqual({k: round(x) for k, x in canal.items()}, {1: 300, 2: 100})
        self.assertEqual(vendas[1]['toneladas'], 1000.0)  # não mexe no dict do cache

    def test_territorio_um_municipio_um_vendedor(self):
        a = VendedorAgro.objects.create(user=User.objects.create_user('a'), repcods=[1], municipios=[4303004, 4300034])
        b = VendedorAgro.objects.create(user=User.objects.create_user('b'), repcods=[2])
        r = self.c.post(f'/comercialAgro/vendedores/{b.id}/territorio/', {'adicionar': [4303004]}, format='json')
        self.assertEqual(r.data['municipios'], [4303004])
        a.refresh_from_db()
        self.assertEqual(a.municipios, [4300034])

    def test_cenario_estendido(self):
        novo = {'t_ha': 0.25, 'dose_t_ha': 2, 'ciclo_anos': 4, 'culturas': ['Soja', 'Milho 2ª safra', 'Pastagem degradada'],
                'sem_duplo': True, 'crescimento_pct': 10, 'por_uf': {'51': {'dose': 3, 'ciclo': 3, 'consumo_t': 13710700}},
                'calibrar': True, 'conc_raio_km': 150, 'conc_reducao_pct': 12, 'conc_piso_pct': 30,
                'titulares_db': ['DAGOBERTO BARCELLOS S/A'], 'capacidade_mes_t': 90000}
        r = self.c.put('/comercialAgro/mercado/cenario/', novo, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['por_uf']['51']['ciclo'], r.data['conc_raio_km'], r.data['capacidade_mes_t']), (3, 150, 90000.0))
        r = self.c.put('/comercialAgro/mercado/cenario/', {**novo, 'conc_raio_km': 77, 'por_uf': {'99': {}}}, format='json')
        self.assertEqual(set(r.data), {'conc_raio_km', 'por_uf'})
