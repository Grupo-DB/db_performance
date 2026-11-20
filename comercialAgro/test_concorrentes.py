import csv
import tempfile

from django.test import SimpleTestCase

from . import concorrentes as cc

CAB = ['Ano', 'Mês', 'Processo', 'AnoDoProcesso', 'Tipo_PF_PJ', 'CPF_CNPJ', 'Substância', 'UF', 'CodigoMunicipio', 'Município',
       'QuantidadeComercializada', 'UnidadeDeMedida', 'ValorRecolhido', 'DataCriacao']


def _csv(linhas):
    f = tempfile.NamedTemporaryFile('w', suffix='.csv', encoding='latin-1', newline='', delete=False)
    w = csv.writer(f, quoting=csv.QUOTE_ALL)
    w.writerow(CAB)
    w.writerows(linhas)
    f.close()
    return f.name


class CfemTests(SimpleTestCase):
    def test_le_limpa_e_monta(self):
        linhas = []
        for mes in range(1, 13):  # empresa A: 1.000 t/mês a R$ 0,50/t; uma linha com tonelagem digitada errada
            q = '9999999999' if mes == 6 else '1000'
            linhas.append(['2025', str(mes), '810095', '1987', 'PJ', '111', 'CALCÁRIO', 'RS', '4302808', 'CAÇAPAVA DO SUL',
                           q, 't ', '500,00', '2025-01-01'])
        linhas.append(linhas[0])  # repetida idêntica (exportação): sai
        linhas.append(['2025', '3', '1', '2000', 'PJ', '222', 'BASALTO', 'RS', '4302808', 'X', '5', 't', '1', ''])  # outra substância
        linhas.append(['2025', '3', '2', '2000', 'PJ', '111', 'CALCÁRIO DOLOMÍTICO', 'RS', '4302808', 'X', '2000000', 'kg', '1000', ''])
        rows = cc.limpar(cc.ler_cfem(_csv(linhas), 2024))
        self.assertEqual(len(rows), 13)
        self.assertAlmostEqual(next(r for r in rows if r['mes'] == 6)['t'], 1000, places=0)  # corrigida pelo valor
        proc = {(810095, 1987): {'nome': 'IRMAOS CIOCCARI', 'uso': 'Brita'}, (9, 2010): {'nome': 'IRMAOS CIOCCARI', 'uso': 'Corretivo de solo'}}
        ped = [{'titular': 'IRMAOS CIOCCARI', 'latitude': -30.53, 'longitude': -53.41}]
        u = cc.montar_unidades(rows, proc, ['DAGOBERTO'], ped, {4302808: (-30.51, -53.49)})
        self.assertEqual(len(u), 1)
        self.assertTrue(u[0]['agro'])  # paga CFEM como brita, mas tem lavra de corretivo perto
        self.assertEqual((u[0]['ate'], round(u[0]['t_12m'])), ('2025-12', 14000))
        longe = cc.montar_unidades(rows, proc, [], ped, {4302808: (-25.0, -49.0)})
        self.assertFalse(longe[0]['agro'])  # mina da empresa longe da lavra de corretivo: não é agro

    def test_ultimo_mes_completo_ignora_meses_pela_metade(self):
        u = [{'mensal': {f'2025-{m:02d}': 100.0 for m in range(1, 13)} | {'2026-01': 30.0}}]
        self.assertEqual(cc.ultimo_mes_completo(u), '2025-12')

    def test_abastecimento_conserva_volume_e_respeita_raio(self):
        cent = {1: (-30.0, -53.0), 2: (-30.5, -53.0), 3: (-20.0, -45.0)}
        ha = {1: 100.0, 2: 100.0, 3: 10_000.0}
        u = [{'cnpj': 'A', 'municipio_ibge': 1, 't_12m': 1000.0}]
        r = cc.abastecimento(u, cent, ha)
        self.assertNotIn(3, r)  # fora dos 500 km
        self.assertAlmostEqual(r[1]['A'] + r[2]['A'], 1000.0, places=3)
        self.assertGreater(r[1]['A'], r[2]['A'])  # mais perto da mina leva mais
