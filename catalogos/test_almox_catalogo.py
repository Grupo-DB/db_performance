from datetime import date

import pandas as pd
from django.test import SimpleTestCase
from rest_framework.test import APIClient
from unittest import mock

from catalogos import almox_catalogo as c
from catalogos import almoxarifado as a
from catalogos.test_almoxarifado import GRUPOS, item


def baixas(*linhas):
    return pd.DataFrame([{'ESTQ': e, 'QUANT': q, 'CUSTO': q * 2, 'VEZES': v, 'ULTIMA': pd.Timestamp('2026-11-10'),
                          'N_CC': 1, 'N_EQP': 1, 'CC_TOPO': 'OPERACOES, MOAGEM', 'EQP_TOPO': 'MOINHO 01'}
                         for e, q, v in linhas])


class CatalogoListaTests(SimpleTestCase):
    def setUp(self):
        df = a.preparar_itens(pd.DataFrame([
            {**item(1, 12, 5, 0), 'ESTQNOME': 'Chave de fenda', 'ESTQREF': 'CF-10'},
            {**item(2, 12, 0, 0), 'ESTQNOME': 'Chave Allen'},        # sem saldo, mas baixado
            {**item(3, 11, 0, 0), 'ESTQNOME': 'Martelo'},            # morto
            {**item(4, 11, 1, 5), 'ESTQNOME': 'Alicate'},            # abaixo do mínimo
        ]), GRUPOS)
        a.juntar_fotos(df, {1})
        a.juntar_compras(df, {})
        self.df = c.juntar_baixas(df, baixas((2, 7.0, 3), (1, 1.0, 1)))

    def cods(self, **kw):
        return sorted(int(x) for x in c.filtrar(self.df, GRUPOS, **kw).ESTQCOD)

    def test_padrao_esconde_parados(self):
        self.assertEqual(self.cods(), [1, 2, 4])
        self.assertEqual(self.cods(parados=True), [1, 2, 3, 4])
        self.assertEqual(self.cods(q='martelo'), [3])                 # pesquisando aparece

    def test_busca_sem_acento_por_palavras_e_referencia(self):
        self.assertEqual(self.cods(q='CHAVE fenda'), [1])
        self.assertEqual(self.cods(q='cf-10'), [1])
        self.assertEqual(self.cods(q='chave'), [1, 2])
        self.assertEqual(self.cods(q='ferramentas allen'), [])        # nome do grupo-raiz não está no alvo
        self.assertEqual(self.cods(q='chaves allen'), [2])            # grupo do item está

    def test_busca_igual(self):
        self.assertEqual(self.cods(q='1', modo='igual'), [1])                  # igual: só o código 1
        self.assertEqual(self.cods(q='cf-10', modo='igual'), [1])              # referência inteira
        self.assertEqual(self.cods(q='CHAVE  allen', modo='igual'), [2])       # nome inteiro, sem caixa/espaço extra
        self.assertEqual(self.cods(q='chave', modo='igual'), [])               # parte do nome não basta

    def test_filtros(self):
        self.assertEqual(self.cods(grupo=12), [1, 2])
        self.assertEqual(self.cods(saldo='sem'), [2])
        self.assertEqual(self.cods(situacao='abaixo'), [4])
        self.assertEqual(self.cods(foto='com'), [1])
        self.assertEqual(self.cods(baixa='com'), [1, 2])
        self.assertEqual(self.cods(baixa='sem'), [4])
        self.assertEqual(self.cods(destino=True), [1, 2])

    def test_ordem_e_item(self):
        sel = c.ordenar(c.filtrar(self.df, GRUPOS), 'baixado')
        self.assertEqual(list(sel.ESTQCOD)[:2], [2, 1])
        d = c._item_catalogo(next(sel.itertuples()))
        self.assertEqual(d['baixa'], {'quantidade': 7.0, 'custo': 14.0, 'vezes': 3, 'ultima': '2026-11-10',
                                      'centros': 1, 'equipamentos': 1, 'centro_principal': 'OPERACOES, MOAGEM',
                                      'equipamento_principal': 'MOINHO 01'})
        self.assertNotIn('compras', d)

    def test_periodo(self):
        hoje = date(2026, 11, 17)
        self.assertEqual(c.periodo(None, None, hoje), (date(2026, 8, 20), hoje))
        self.assertEqual(c.periodo(date(2026, 11, 20), date(2026, 11, 1), hoje), (date(2026, 11, 1), date(2026, 11, 20)))
        self.assertEqual(c.periodo(date(2000, 1, 1), hoje, hoje)[0], hoje - pd.Timedelta(days=c.DIAS_MAX).to_pytimedelta())


class CatalogoDetalheTests(SimpleTestCase):
    @staticmethod
    def linha(cod, sit, quant, cc=5, eqp=7, data='2026-11-10', **kw):
        base = {'COD': cod, 'REQ': 100 + cod, 'SIT': sit, 'DATA': pd.Timestamp(data), 'DATA_APL': pd.Timestamp(data),
                'FIL': 0, 'QUANT': quant, 'QUANT_DEV': 0.0, 'CUSTO': quant * 3, 'CUSTO_UNIT': 3.0, 'ORIGEM': 0,
                'CC': cc, 'CC_NOME': 'OPERACOES, MOINHO' if cc == 5 else 'ADM, ESCRITORIO',
                'EQP': eqp, 'EQP_NOME': 'MOINHO 01' if eqp else '', 'EQP_PLACA': '', 'PARTE': '', 'OS': 0,
                'REQUISITANTE': 'FULANO', 'ALMOXARIFE': 'BELTRANO', 'COLABORADOR': '', 'MOTIVO': 'OPERACIONAL', 'PLACA': ''}
        base.update(kw)
        return base

    def test_devolucao_desconta_e_agrupa(self):
        d = c.montar_detalhe(pd.DataFrame([
            self.linha(1, 8, 4.0, QUANT_DEV=1.0),
            self.linha(2, 10, 1.0),                              # devolução da 1
            self.linha(3, 8, 2.0, cc=9, eqp=0, data='2026-10-05'),
        ]))
        self.assertEqual(d['totais'], {'quantidade': 5.0, 'custo': 15.0, 'vezes': 2, 'devolvido': 1.0, 'limite': False})
        self.assertEqual([(g['nome'], g['quantidade'], g['vezes']) for g in d['por_centro']],
                         [('MOINHO', 3.0, 1), ('ESCRITORIO', 2.0, 1)])
        self.assertEqual([(g['nome'], g['quantidade']) for g in d['por_equipamento']], [('MOINHO 01', 3.0)])
        self.assertEqual([(m['mes'], m['quantidade']) for m in d['por_mes']], [('2026-10', 2.0), ('2026-11', 3.0)])
        self.assertEqual((d['baixas'][1]['quantidade'], d['baixas'][1]['devolucao']), (-1.0, True))

    def test_centros_trazem_os_pais(self):
        usados = pd.DataFrame([{'COD': 3, 'NOME': 'OPER, FABRICA, MOINHO', 'NIVEL': 3, 'CAMINHO': '+1+2+3+', 'N': 9}])
        todos = pd.DataFrame([
            {'COD': 1, 'NOME': 'OPER', 'NIVEL': 1, 'CAMINHO': '+1+'},
            {'COD': 2, 'NOME': 'OPER, FABRICA', 'NIVEL': 2, 'CAMINHO': '+1+2+'},
            {'COD': 3, 'NOME': 'OPER, FABRICA, MOINHO', 'NIVEL': 3, 'CAMINHO': '+1+2+3+'},
            {'COD': 4, 'NOME': 'OUTRO', 'NIVEL': 1, 'CAMINHO': '+4+'},
        ])
        self.assertEqual([(x['codigo'], x['nome'], x['nivel'], x['baixas']) for x in c.montar_centros(usados, todos)],
                         [(1, 'OPER', 1, 0), (2, 'FABRICA', 2, 0), (3, 'MOINHO', 3, 9)])

    def test_filtro_cc_pega_descendentes(self):
        join, filtros, p = c._filtros_sql(0, 4701, None, 12)
        self.assertIn('JOIN CENTROCUSTO CF', join)
        self.assertEqual(p, {'fil': 0, 'cc_caminho': '%+4701+%', 'req': 12})
        self.assertIn('CF.CCSTCOD LIKE', filtros)


class CatalogoEndpointTests(SimpleTestCase):
    databases = '__all__'

    def test_lista_valida_parametros(self):
        from django.contrib.auth.models import User
        u = User(username='x', is_superuser=True)
        u.save()
        cli = APIClient()
        cli.force_authenticate(u)
        with mock.patch.object(c, 'listar', return_value={'itens': []}) as m:
            r = cli.get('/catalogos/erp/almoxarifado/catalogo/', {'q': 'disco', 'desde': '2026-10-01', 'cc': '5', 'ordem': 'xx'})
            self.assertEqual(r.status_code, 200)
            kw = m.call_args.kwargs
            self.assertEqual((kw['q'], kw['desde'], kw['cc'], kw['ordem']), ('disco', date(2026, 10, 1), 5, 'nome'))
        r = cli.get('/catalogos/erp/almoxarifado/catalogo/', {'desde': 'ontem'})
        self.assertEqual(r.status_code, 400)
