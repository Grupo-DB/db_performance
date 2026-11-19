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


@mock.patch('comercialAgro.erp_agro.clientes_com_compra', return_value={4849})
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

    def test_prospeccao_cruza_produtores(self, *_):
        p = Produtor.objects.create(nome='Tiago', cliente_sga=4849, car_codigo='RS-B', cadastro='CADASTRADO')
        Produtor.objects.create(nome='Ernesto', car_codigo='RS-C')
        imoveis = [geo.imovel(feature(c, a)) for c, a in (('RS-A', 300), ('RS-B', 900), ('RS-C', 150))]
        with mock.patch('comercialAgro.geo.car_municipio', return_value=imoveis) as cm:
            r = self.cli(self.user).get('/comercialAgro/prospeccao/?municipio=4303004&min_ha=100')
            self.cli(self.user).get('/comercialAgro/prospeccao/?municipio=4303004&min_ha=100')
            self.assertEqual(cm.call_count, 1)  # segunda vez sai do banco
        self.assertEqual([(i['codigo'], i['situacao']) for i in r.data['imoveis']],
                         [('RS-A', 'livre'), ('RS-C', 'conhecido'), ('RS-B', 'cliente')])
        self.assertEqual(r.data['resumo'], {'livre': 1, 'conhecido': 1, 'contato': 0, 'cliente': 1})
        self.assertEqual(r.data['imoveis'][2]['produtor']['id'], p.id)

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
