from datetime import date

import pandas as pd
from django.test import SimpleTestCase

from catalogos import almox_indicadores as ind
from catalogos import almoxarifado as a
from catalogos.test_almoxarifado import GRUPOS, item

HOJE = date(2026, 11, 18)


def base(linhas, fotos=(), consumo12=None, ultima=None):
    df = a.preparar_itens(pd.DataFrame(linhas), GRUPOS)
    a.juntar_compras(df, {})
    a.juntar_fotos(df, set(fotos))
    return ind.juntar_extras(df, consumo12 or {}, ultima or {}, HOJE)


class IndicadoresTests(SimpleTestCase):
    def test_percentuais_por_grupo(self):
        # 4 com saldo; 3 com mínimo, 1 abaixo; 1 sem foto entre os com saldo; item 5 sem saldo não conta foto.
        df = base([item(1, 12, 5, 10), item(2, 12, 20, 10), item(3, 11, 20, 10), item(4, 10, 3, 0), item(5, 10, 0, 0)],
                  fotos=[1, 2, 3])
        g, = ind.por_grupo(df)
        self.assertEqual(g['nome'], 'FERRAMENTAS')
        self.assertEqual((g['abaixo_minimo'], g['com_minimo'], g['pct_abaixo']), (1, 3, 33.3))
        self.assertEqual((g['sem_foto'], g['com_saldo'], g['pct_sem_foto']), (1, 4, 25.0))
        self.assertEqual(g['pct_sem_minimo'], 25.0)

    def test_parados(self):
        # 1 saiu há 17 dias, 2 há quase 2 anos, 3 nunca saiu; 4 sem saldo não conta.
        df = base([item(1, 12, 1, 0, 100), item(2, 12, 1, 0, 50), item(3, 12, 1, 0, 10), item(4, 12, 0, 0)],
                  ultima={1: date(2026, 11, 1), 2: date(2025, 1, 1)})
        self.assertEqual(sorted(df[df.PARADO].ESTQCOD), [2, 3])

    def test_movimentos_por_grupo(self):
        df = base([item(1, 12, 5, 0), item(2, 10, 5, 0)])
        mov = pd.DataFrame([
            {'DATA': pd.Timestamp('2026-11-18 10:00'), 'TIPO': 2, 'ESTQ': 1, 'QUANT': -2, 'VALOR': -30.0, 'FIL': 0},
            {'DATA': pd.Timestamp('2026-11-18 09:00'), 'TIPO': 1, 'ESTQ': 2, 'QUANT': 5, 'VALOR': 100.0, 'FIL': 0},
            {'DATA': pd.Timestamp('2026-11-17 09:00'), 'TIPO': 2, 'ESTQ': 1, 'QUANT': -1, 'VALOR': -3e151, 'FIL': 0},
            {'DATA': pd.Timestamp('2026-11-17 09:00'), 'TIPO': 2, 'ESTQ': 99, 'QUANT': -1, 'VALOR': -7.0, 'FIL': 0},
        ])
        m = ind.movimentos(mov, df, HOJE)
        self.assertEqual(len(m['dias']), 30)
        self.assertEqual(m['dias'][-1], '2026-11-18')
        raiz1, raiz2 = (str(int(df[df.ESTQCOD == c].RAIZ.iloc[0])) for c in (1, 2))
        self.assertEqual(m['grupos'][raiz1]['saidas'][-1], 30.0)
        self.assertEqual(m['grupos'][raiz1]['saidas'][-2], 0.0)  # custo lixo cortado
        self.assertEqual(m['grupos'][raiz2]['entradas'][-1], 100.0)
        self.assertEqual([u['codigo'] for u in m['ultimas']], [1, 2, 1])  # item 99 fora do recorte
        self.assertEqual(m['ultimas'][0]['grupo_codigo'], int(raiz1))

    def test_montar_totais(self):
        df = base([item(1, 12, 10, 5, 10), item(2, 12, 1, 5, 10)], fotos=[1], consumo12={1: 400},
                  ultima={1: HOJE})
        r = ind.montar(df, pd.DataFrame(), HOJE)
        t = r['totais']
        self.assertEqual(t['valor'], 110.0)
        self.assertEqual(t['giro'], 3.64)
        self.assertEqual(t['parados'], 1)
        self.assertEqual(r['top_valor'][0]['codigo'], 1)
        self.assertEqual(r['top_parados'][0]['dias_parado'], None)


class SituacaoCompraTests(SimpleTestCase):
    def test_classifica_pela_situacao_mais_critica(self):
        req = {'etapa': 'requisicao'}
        col = {'etapa': 'coleta'}
        ordem = {'etapa': 'ordem', 'atrasada': False}
        atras = {'etapa': 'ordem', 'atrasada': True}
        nota = {'etapa': 'ordem', 'atrasada': True, 'nota_pendente': {'numero': 1, 'quantidade': 2}}
        self.assertEqual([ind.situacao_compra(x) for x in (None, [], [req], [col, req], [ordem], [ordem, atras], [nota])],
                         [None, None, 'requisicao', 'coleta', 'ordem', 'atrasada', 'nota'])

    def test_contagem_e_por_grupo(self):
        # 1 abaixo em ordem; 2 abaixo SEM compra; 3 ok em coleta; 4 ok sem compra (não conta)
        df = a.preparar_itens(pd.DataFrame([item(1, 12, 1, 10), item(2, 12, 0, 10), item(3, 11, 50, 10), item(4, 10, 50, 10)]), GRUPOS)
        a.juntar_compras(df, {1: [{'etapa': 'ordem', 'atrasada': False}], 3: [{'etapa': 'coleta'}]})
        a.juntar_fotos(df, set())
        c = ind.compras(df)
        por = {s['chave']: (s['itens'], s['abaixo']) for s in c['situacoes']}
        self.assertEqual((por['ordem'], por['coleta'], por['requisicao']), ((1, 1), (1, 0), (0, 0)))
        self.assertEqual((c['em_compra'], c['abaixo'], c['abaixo_em_compra'], c['abaixo_sem_compra']), (2, 2, 1, 1))
        g, = c['grupos']
        self.assertEqual((g['total'], g['sem_compra'], g['ordem'], g['coleta']), (2, 1, 1, 1))
