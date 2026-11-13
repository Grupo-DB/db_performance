from datetime import date

import pandas as pd
from django.test import SimpleTestCase

from catalogos import almoxarifado as a

GRUPOS = pd.DataFrame([
    {'GALMCOD': 10, 'GALMNOME': 'FERRAMENTAS', 'GALMGALMPAI': 0, 'GALMBLOQ': 'N'},
    {'GALMCOD': 11, 'GALMNOME': 'MANUAIS', 'GALMGALMPAI': 10, 'GALMBLOQ': 'N'},
    {'GALMCOD': 12, 'GALMNOME': 'CHAVES', 'GALMGALMPAI': 11, 'GALMBLOQ': 'N'},
    {'GALMCOD': 20, 'GALMNOME': 'PRODUTO (REVENDA)', 'GALMGALMPAI': 0, 'GALMBLOQ': 'N'},
    {'GALMCOD': 30, 'GALMNOME': 'BLOQUEADO', 'GALMGALMPAI': 0, 'GALMBLOQ': 'S'},
])


def item(cod, galm, saldo, minimo, custo=10.0, fil=0):
    return {'ESTQCOD': cod, 'ESTQNOME': f'Item {cod}', 'ESTQREF': '', 'ESTQGALM': galm, 'ESPSIGLA': 'UN',
            'FIL': fil, 'SALDO': saldo, 'MINIMO': minimo, 'MAXIMO': 0, 'CUSTO': custo}


class AlmoxarifadoTests(SimpleTestCase):
    def preparar(self, linhas):
        return a.preparar_itens(pd.DataFrame(linhas), GRUPOS)

    def test_raiz_e_subgrupo_de_primeiro_nivel(self):
        df = self.preparar([item(1, 12, 5, 0)])
        self.assertEqual(df.iloc[0].RAIZ_NOME, 'FERRAMENTAS')
        self.assertEqual(df.iloc[0].SUB_NOME, 'MANUAIS')  # neto cai no filho da raiz

    def test_raizes_fora_e_bloqueadas_saem(self):
        df = self.preparar([item(1, 20, 5, 0), item(2, 30, 5, 0), item(3, 10, 5, 0)])
        self.assertEqual(list(df.ESTQCOD), [3])

    def test_percentual_so_com_minimo(self):
        df = self.preparar([
            item(1, 11, 10, 5),   # no mínimo
            item(2, 11, 2, 5),    # abaixo
            item(3, 11, 0, 4),    # zerado (abaixo)
            item(4, 11, 7, 0),    # sem mínimo, com saldo
            item(5, 11, 0, 0),    # morto: não conta como pendência
        ])
        g = a.montar_grupos(df)[0]
        self.assertEqual((g['com_minimo'], g['no_minimo'], g['abaixo_minimo'], g['zerados'], g['sem_minimo']),
                         (3, 1, 2, 1, 1))
        self.assertEqual(g['percentual'], 33.3)
        self.assertEqual(g['situacao'], 'critico')
        # Crítico mais grave primeiro (zerado).
        self.assertEqual([i['codigo'] for i in g['itens_criticos']], [3, 2])
        self.assertEqual(g['itens_criticos'][0]['falta'], 4)

    def test_filiais_somadas_e_valor_sem_saldo_negativo(self):
        df = self.preparar([item(1, 11, 3, 2, fil=0), item(1, 11, 2, 2, fil=3), item(2, 11, -5, 0)])
        g = a.montar_grupos(df)[0]
        self.assertEqual(g['itens'], 2)
        self.assertEqual(g['no_minimo'], 1)       # 5 >= 4
        self.assertEqual(g['valor'], 50.0)        # saldo negativo não vira valor negativo

    def test_custo_absurdo_zerado(self):
        df = self.preparar([item(1, 11, 1, 0, custo=3e151)])
        self.assertEqual(a.montar_grupos(df)[0]['valor'], 0.0)

    def test_sem_minimo_no_grupo(self):
        df = self.preparar([item(1, 11, 3, 0)])
        g = a.montar_grupos(df)[0]
        self.assertIsNone(g['percentual'])
        self.assertEqual(g['situacao'], 'sem_minimo')

    def test_faixas(self):
        self.assertEqual(a.situacao(90)[0], 'excelente')
        self.assertEqual(a.situacao(89.9)[0], 'adequado')
        self.assertEqual(a.situacao(75)[0], 'adequado')
        self.assertEqual(a.situacao(50)[0], 'alerta')
        self.assertEqual(a.situacao(49.9)[0], 'critico')

    def test_movimentos_por_dia(self):
        df = self.preparar([item(1, 11, 3, 0)])
        hoje = date(2026, 11, 11)
        mov = pd.DataFrame([
            {'DATA': '2026-11-11', 'TIPO': 1, 'ESTQ': 1, 'QUANT': 5, 'VALOR': 50, 'FIL': 0},
            {'DATA': '2026-11-10', 'TIPO': 2, 'ESTQ': 1, 'QUANT': -2, 'VALOR': -20, 'FIL': 0},
            {'DATA': '2026-11-10', 'TIPO': 2, 'ESTQ': 999, 'QUANT': -2, 'VALOR': -20, 'FIL': 0},  # fora do recorte
        ])
        m = a.montar_movimentos(mov, df, hoje)
        self.assertEqual(len(m['dias']), a.DIAS_MOVIMENTO)
        self.assertEqual(m['entradas'][-1], 50.0)
        self.assertEqual(m['saidas'][-2], 20.0)
        self.assertEqual(len(m['ultimas']), 2)
        self.assertEqual(m['ultimas'][0]['tipo'], 'Entrada (nota)')


class ArvoreSubgruposTests(SimpleTestCase):
    GRUPOS = pd.concat([GRUPOS, pd.DataFrame([
        {'GALMCOD': 13, 'GALMNOME': 'ELETRICAS', 'GALMGALMPAI': 10, 'GALMBLOQ': 'N'},   # vazio: entra
        {'GALMCOD': 14, 'GALMNOME': 'VELHAS', 'GALMGALMPAI': 10, 'GALMBLOQ': 'S'},      # bloqueado vazio: sai
    ])], ignore_index=True)

    def test_arvore_com_netos_soma_descendentes(self):
        df = a.preparar_itens(pd.DataFrame([item(1, 12, 2, 5), item(2, 11, 9, 5)]), self.GRUPOS)
        g = a.montar_grupos(df, self.GRUPOS)[0]
        nomes = [n['nome'] for n in g['arvore']]
        self.assertEqual(nomes, ['ELETRICAS', 'MANUAIS'])
        manuais = g['arvore'][1]
        self.assertEqual((manuais['com_minimo'], manuais['abaixo_minimo']), (2, 1))
        self.assertEqual([n['nome'] for n in manuais['filhos']], ['CHAVES'])
        self.assertEqual(manuais['filhos'][0]['abaixo_minimo'], 1)
        self.assertEqual(g['arvore'][0]['itens'], 0)


class AtencaoTests(SimpleTestCase):
    """Atenção = não está abaixo do mínimo, mas a cobertura pelo consumo cabe no prazo do grupo."""
    GRUPOS = pd.concat([GRUPOS, pd.DataFrame([
        {'GALMCOD': 40, 'GALMNOME': 'MATERIA PRIMA / EMBALAGEM', 'GALMGALMPAI': 0, 'GALMBLOQ': 'N'},
        {'GALMCOD': 41, 'GALMNOME': 'EMBALAGEM', 'GALMGALMPAI': 40, 'GALMBLOQ': 'N'},
        {'GALMCOD': 42, 'GALMNOME': 'BIG BAG', 'GALMGALMPAI': 41, 'GALMBLOQ': 'N'},
        {'GALMCOD': 43, 'GALMNOME': 'MATERIA PRIMA', 'GALMGALMPAI': 40, 'GALMBLOQ': 'N'},
    ])], ignore_index=True)

    def test_prazo_padrao_embalagem_e_heranca(self):
        p = a.prazos_por_grupo(self.GRUPOS)
        self.assertEqual(p[12], (7, False))
        self.assertEqual(p[42], (45, False))          # neto de EMBALAGEM herda 45
        self.assertEqual(p[43], (7, False))           # matéria prima não é embalagem
        p = a.prazos_por_grupo(self.GRUPOS, {11: 20, 42: 60})
        self.assertEqual(p[12], (20, False))          # herdou do pai cadastrado
        self.assertEqual(p[11], (20, True))
        self.assertEqual(p[42], (60, True))

    def test_atencao_pela_cobertura(self):
        consumo = {1: 90.0, 2: 90.0, 3: 900.0, 4: 0.0}   # em 90 dias → 1/dia, 1/dia, 10/dia, 0
        df = a.preparar_itens(pd.DataFrame([
            item(1, 12, 5, 0),      # 5 dias de cobertura ≤ 7 → atenção (mesmo sem mínimo)
            item(2, 12, 30, 0),     # 30 dias → ok
            item(3, 42, 300, 10),   # 30 dias ≤ 45 (embalagem) → atenção
            item(4, 12, 1, 0),      # sem consumo → não projeta
            item(5, 12, 1, 5),      # abaixo do mínimo: não conta como atenção
            item(6, 12, 0, 0),      # zerado sem mínimo = compra sob demanda: não é atenção
        ]), self.GRUPOS, consumo={**consumo, 6: 90.0})
        at = dict(zip(df.ESTQCOD, df.ATENCAO))
        self.assertEqual(at, {1: True, 2: False, 3: True, 4: False, 5: False, 6: False})
        g = {x['codigo']: x for x in a.montar_grupos(df, self.GRUPOS)}
        self.assertEqual(g[10]['atencao'], 1)
        self.assertEqual(g[40]['atencao'], 1)
        self.assertEqual(g[40]['prazo'], 7)
        self.assertEqual(g[40]['arvore'][0]['prazo'], 45)

    def test_minimos_do_app_substituem_a_coluna(self):
        df = a.preparar_itens(pd.DataFrame([dict(item(1, 12, 5, 99), MINIMO=99)]), self.GRUPOS, minimos={1: 10})
        self.assertEqual(df.iloc[0].MINIMO, 10)
        self.assertTrue(df.iloc[0].ABAIXO)

    def test_listas_por_grupo(self):
        df = a.preparar_itens(pd.DataFrame([item(1, 12, 1, 5), item(2, 12, 9, 5), item(3, 11, 2, 0), item(4, 11, 0, 0)]),
                              self.GRUPOS, consumo={3: 90.0})
        self.assertEqual(list(a.filtrar_itens(df, self.GRUPOS, 11, 'abaixo').ESTQCOD), [1])  # neto entra
        self.assertEqual(list(a.filtrar_itens(df, self.GRUPOS, None, 'atencao').ESTQCOD), [3])
        self.assertEqual(sorted(a.filtrar_itens(df, self.GRUPOS, 10, 'todos').ESTQCOD), [1, 2, 3])  # 4 é morto
        self.assertEqual(a._item(next(a.filtrar_itens(df, self.GRUPOS, None, 'atencao').itertuples()))['situacao'], 'atencao')


from django.contrib.auth.models import User
from django.test import TestCase


class EdicaoTests(TestCase):
    def test_salvar_e_apagar_minimo(self):
        from catalogos.models import MinimoEstoque, PrazoAtencaoGrupo
        u = User.objects.create(username='almox')
        a.salvar_minimos(0, [{'codigo': 1, 'minimo': '10,5'.replace(',', '.')}, {'codigo': 2, 'minimo': 3}], u)
        a.salvar_minimos(3, [{'codigo': 1, 'minimo': 4}], u)
        self.assertEqual(a.minimos_app(0), {1: 10.5, 2: 3.0})
        self.assertEqual(a.minimos_app(None), {1: 14.5, 2: 3.0})
        a.salvar_minimos(0, [{'codigo': 2, 'minimo': None}], u)
        self.assertFalse(MinimoEstoque.objects.filter(item=2).exists())
        with self.assertRaises(ValueError):
            a.salvar_minimos(0, [{'codigo': 1, 'minimo': -1}], u)
        a.salvar_prazo(1703, 45, u)
        self.assertEqual(a.prazos_app(), {1703: 45})
        a.salvar_prazo(1703, None, u)
        self.assertFalse(PrazoAtencaoGrupo.objects.exists())
        with self.assertRaises(ValueError):
            a.salvar_prazo(1, 0, u)
