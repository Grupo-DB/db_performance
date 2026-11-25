from datetime import date

import pandas as pd
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient
from unittest import mock

from catalogos import almox_insumos as ins
from catalogos import almoxarifado as a
from catalogos.test_almoxarifado import GRUPOS, item

HOJE = date(2026, 11, 17)


def mov(*linhas):
    """(item, 'AAAA-MM-DD', tipo, quantidade com sinal, valor com sinal)."""
    return pd.DataFrame([{'ESTQ': e, 'DIA': pd.Timestamp(d), 'TIPO': t, 'QUANT': q, 'VALOR': v}
                         for e, d, t, q, v in linhas])


class InsumosPainelTests(SimpleTestCase):
    def setUp(self):
        df = a.preparar_itens(pd.DataFrame([
            item(1, 12, 30, 0, custo=2.0),     # chave: grupo 12 (mais fundo que o 10)
            item(2, 11, 0, 5),                 # sem saldo e abaixo do mínimo
            item(3, 11, 0, 0),                 # morto: não aparece
            item(4, 12, 10, 0),                # monitorado como item avulso
        ]), GRUPOS)
        a.juntar_compras(df, {})
        a.juntar_fotos(df, set())
        self.df = df
        self.monit = [{'id': 1, 'tipo': 'grupo', 'codigo': 10}, {'id': 2, 'tipo': 'grupo', 'codigo': 12},
                      {'id': 3, 'tipo': 'item', 'codigo': 4}]

    def painel(self, m, dias=30):
        return ins.montar_painel(self.df, GRUPOS, m, self.monit, HOJE, dias)

    def test_distribui_no_mais_especifico(self):
        chaves, info = ins.distribuir(self.df, GRUPOS, self.monit)
        self.assertEqual(dict(zip(self.df.ESTQCOD, chaves)), {1: 'g12', 2: 'g10', 3: 'g10', 4: 'i4'})
        self.assertEqual([(d['nome'], d['caminho']) for d in info],
                         [('FERRAMENTAS', ''), ('CHAVES', 'FERRAMENTAS › MANUAIS'), ('Item 4', '')])

    def test_consumo_liquido_cobertura_e_comparacao(self):
        p = self.painel(mov(
            (1, '2026-11-10', 2, -40, -80),     # requisição
            (1, '2026-11-12', 2, 10, 20),       # devolução
            (1, '2026-11-01', 1, 50, 100),      # entrada
            (1, '2026-10-01', 2, -15, -30),     # período anterior (30 dias antes)
        ))
        i1 = next(i for i in p['itens'] if i['codigo'] == 1)
        self.assertEqual((i1['consumo'], i1['consumo_valor'], i1['entrada']), (30.0, 60.0, 50.0))
        self.assertEqual((i1['consumo_dia'], i1['cobertura_dias'], i1['variacao']), (1.0, 30.0, 100.0))
        self.assertEqual(i1['situacao'], 'ok')
        self.assertEqual(sum(i1['serie']), 30.0)
        self.assertEqual(sorted(i['codigo'] for i in p['itens']), [1, 2, 4])
        self.assertEqual(next(i for i in p['itens'] if i['codigo'] == 2)['situacao'], 'abaixo')
        self.assertEqual(next(i for i in p['itens'] if i['codigo'] == 4)['situacao'], 'sem_consumo')
        g12 = next(c for c in p['monitorados'] if c['chave'] == 'g12')
        self.assertEqual((g12['consumo_valor'], g12['consumo_valor_anterior'], g12['unidade']), (60.0, 30.0, 'UN'))
        self.assertEqual(g12['mensal'][-2:], [30.0, 60.0])
        self.assertEqual(p['entradas_mensal'][-1], 100.0)
        self.assertEqual(p['totais']['abaixo'], 1)

    def test_atencao_pela_cobertura(self):
        p = self.painel(mov((1, '2026-11-10', 2, -150, -300)))   # 5/dia, saldo 30 → 6 dias ≤ prazo 7
        self.assertEqual(next(i for i in p['itens'] if i['codigo'] == 1)['situacao'], 'atencao')

    def test_foto_do_cartao_automatica_e_escolhida(self):
        df = a.preparar_itens(pd.DataFrame([
            item(5, 11, 10, 0, custo=1.0),
            item(6, 11, 10, 0, custo=1.0),
            item(7, 11, 10, 0, custo=1.0),
        ]), GRUPOS)
        a.juntar_compras(df, {})
        a.juntar_fotos(df, {5, 6})                       # o 7 não tem foto
        consumo = mov((5, '2026-11-10', 2, -1, -10), (6, '2026-11-10', 2, -1, -50), (7, '2026-11-10', 2, -1, -90))

        def cartao(foto_item):
            m = [{'id': 1, 'tipo': 'grupo', 'codigo': 10, 'foto_item': foto_item}]
            return ins.montar_painel(df, GRUPOS, consumo, m, HOJE, 30)['monitorados'][0]

        auto = cartao(None)                              # maior consumo COM foto: o 6 (o 7 consome mais, sem foto)
        self.assertEqual((auto['foto_codigo'], auto['foto_escolhida']), (6, False))
        self.assertEqual([o['codigo'] for o in auto['fotos_opcoes']], [6, 5])
        self.assertEqual((cartao(5)['foto_codigo'], cartao(5)['foto_escolhida']), (5, True))
        self.assertEqual((cartao(7)['foto_codigo'], cartao(7)['foto_escolhida']), (6, False))   # sem foto: volta à automática

    def test_passo_da_serie(self):
        self.assertEqual([ins.passo_serie(d) for d in (30, 90, 180, 365)], [1, 7, 14, 30])
        self.assertEqual(len(self.painel(mov(), 90)['monitorados'][0]['serie']), 13)

    def test_serie_anual_em_meses_de_calendario(self):
        # 1 ano: 12 meses inteiros, dez/2025 a nov/2026 (o atual vai até hoje), e não blocos de 30 dias.
        p = self.painel(mov((1, '2025-12-01', 2, -4, -8), (1, '2026-10-31', 2, -1, -2), (1, '2026-11-01', 2, -3, -6)), 365)
        self.assertEqual(p['meses_serie'][0], '2025-12')
        self.assertEqual(p['meses_serie'][-1], '2026-11')
        self.assertEqual(len(p['meses_serie']), 12)
        self.assertEqual(p['inicio_serie'], '2025-12-01')
        i1 = next(i for i in p['itens'] if i['codigo'] == 1)
        self.assertEqual((i1['serie'][0], i1['serie'][-2], i1['serie'][-1]), (4.0, 1.0, 3.0))
        self.assertIsNone(self.painel(mov(), 90)['meses_serie'])


class InsumosEdicaoTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group, User
        self.gestor = User.objects.create(username='g')
        self.gestor.groups.add(Group.objects.create(name='comprasGestor'))
        self.leitor = User.objects.create(username='l')
        self.leitor.groups.add(Group.objects.create(name='comprasCliente'))

    def cli(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c

    def test_gestor_inclui_reordena_e_remove(self):
        from catalogos.models import InsumoMonitorado
        url = '/catalogos/erp/almoxarifado/insumos/monitorados/'
        InsumoMonitorado.objects.all().delete()
        c = self.cli(self.gestor)
        r1 = c.post(url, {'tipo': 'grupo', 'codigo': 1702}, format='json')
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(c.post(url, {'tipo': 'grupo', 'codigo': 1702}, format='json').status_code, 200)
        r2 = c.post(url, {'tipo': 'item', 'codigo': 251}, format='json')
        self.assertEqual(c.post(url, {'tipo': 'x', 'codigo': 1}, format='json').status_code, 400)
        c.put(url, {'ids': [r2.data['id'], r1.data['id']]}, format='json')
        self.assertEqual(list(InsumoMonitorado.objects.values_list('codigo', flat=True)), [251, 1702])
        self.assertEqual(c.delete(f"{url}{r1.data['id']}/").status_code, 204)
        self.assertEqual(InsumoMonitorado.objects.count(), 1)

    def test_selecao_separada_por_filial(self):
        from catalogos.models import InsumoMonitorado
        url = '/catalogos/erp/almoxarifado/insumos/monitorados/'
        InsumoMonitorado.objects.all().delete()
        c = self.cli(self.gestor)
        self.assertEqual(c.post(url, {'tipo': 'grupo', 'codigo': 1702, 'filial': 3}, format='json').status_code, 201)
        self.assertEqual(c.post(url, {'tipo': 'grupo', 'codigo': 1702, 'filial': 0}, format='json').status_code, 201)
        self.assertEqual(c.post(url, {'tipo': 'item', 'codigo': 9, 'filial': 'todas'}, format='json').status_code, 201)
        self.assertEqual(c.post(url, {'tipo': 'item', 'codigo': 9, 'filial': 'todas'}, format='json').status_code, 200)
        self.assertEqual([m['codigo'] for m in ins.monitorados_app(3)], [1702])
        self.assertEqual([m['codigo'] for m in ins.monitorados_app(None)], [9])
        self.assertEqual(ins.monitorados_app(5), [])
        r = c.delete(f"{url}{InsumoMonitorado.objects.get(filial=3).id}/")
        self.assertEqual(r.status_code, 204)
        self.assertEqual([m['codigo'] for m in ins.monitorados_app(0)], [1702])   # a matriz não perdeu nada

    def test_escolhe_e_limpa_a_foto(self):
        from catalogos.models import InsumoMonitorado
        m = InsumoMonitorado.objects.create(tipo='grupo', codigo=55, filial=0)
        url = f'/catalogos/erp/almoxarifado/insumos/monitorados/{m.id}/'
        c = self.cli(self.gestor)
        self.assertEqual(c.patch(url, {'foto_item': 123}, format='json').status_code, 200)
        self.assertEqual(InsumoMonitorado.objects.get(pk=m.id).foto_item, 123)
        self.assertEqual(c.patch(url, {'foto_item': None}, format='json').status_code, 200)
        self.assertIsNone(InsumoMonitorado.objects.get(pk=m.id).foto_item)
        self.assertEqual(c.patch(url, {'foto_item': 'x'}, format='json').status_code, 400)
        self.assertEqual(self.cli(self.leitor).patch(url, {'foto_item': 1}, format='json').status_code, 403)

    def test_migracao_copia_a_selecao_para_as_filiais(self):
        import importlib
        from django.apps import apps
        from catalogos.models import InsumoMonitorado
        mig = importlib.import_module('catalogos.migrations.0012_insumomonitorado_filial_foto')
        InsumoMonitorado.objects.all().delete()
        InsumoMonitorado.objects.create(tipo='grupo', codigo=1702, ordem=0)
        InsumoMonitorado.objects.create(tipo='item', codigo=9, ordem=1, foto_item=9)
        mig.copiar_para_filiais(apps, None)
        mig.copiar_para_filiais(apps, None)                       # rodar de novo não duplica
        for f in mig.FILIAIS:
            self.assertEqual([(m['tipo'], m['codigo'], m['foto_item']) for m in ins.monitorados_app(f)],
                             [('grupo', 1702, None), ('item', 9, 9)])
        self.assertEqual(len(ins.monitorados_app(None)), 2)

    def test_painel_proprio_por_usuario(self):
        from django.contrib.auth.models import User
        from catalogos.models import InsumoMonitorado
        url = '/catalogos/erp/almoxarifado/insumos/monitorados/'
        InsumoMonitorado.objects.all().delete()
        p1 = InsumoMonitorado.objects.create(tipo='grupo', codigo=1702, filial=0, ordem=0)
        p2 = InsumoMonitorado.objects.create(tipo='grupo', codigo=1703, filial=0, ordem=1)
        outro = User.objects.create(username='o')
        codigos = lambda lst: [m['codigo'] for m in lst]

        # Sem personalizar, vê o padrão.
        self.assertEqual((codigos(ins.selecao_efetiva(0, self.leitor)[0]), ins.selecao_efetiva(0, self.leitor)[1]), ([1702, 1703], False))
        # O leitor (sem permissão no padrão) inclui no PRÓPRIO: nasce como cópia do padrão + o novo.
        c = self.cli(self.leitor)
        self.assertEqual(c.post(url, {'tipo': 'item', 'codigo': 9, 'filial': 0, 'painel': 'meu'}, format='json').status_code, 201)
        self.assertEqual(ins.selecao_efetiva(0, self.leitor), (ins.monitorados_app(0, self.leitor), True))
        self.assertEqual(codigos(ins.monitorados_app(0, self.leitor)), [1702, 1703, 9])
        self.assertEqual(codigos(ins.monitorados_app(0)), [1702, 1703])                    # padrão intacto
        self.assertEqual(codigos(ins.selecao_efetiva(0, outro)[0]), [1702, 1703])            # os outros não mudam
        self.assertEqual(ins.selecao_efetiva(3, self.leitor)[1], False)                       # outra filial: ainda o padrão

        # Ids do padrão em "meu" agem na cópia: tirar o 1703 e inverter a ordem.
        self.assertEqual(c.delete(f'{url}{p2.id}/?painel=meu').status_code, 204)
        meu = {m['codigo']: m['id'] for m in ins.monitorados_app(0, self.leitor)}
        c.put(url, {'ids': [meu[9], p1.id], 'painel': 'meu'}, format='json')
        self.assertEqual(codigos(ins.monitorados_app(0, self.leitor)), [9, 1702])
        self.assertEqual(c.patch(f'{url}{p1.id}/', {'foto_item': 77, 'painel': 'meu'}, format='json').status_code, 200)
        self.assertEqual({m['codigo']: m['foto_item'] for m in ins.monitorados_app(0, self.leitor)}[1702], 77)
        self.assertIsNone(InsumoMonitorado.objects.get(pk=p1.id).foto_item)
        self.assertEqual(codigos(ins.monitorados_app(0)), [1702, 1703])

        # Não mexe no painel de outra pessoa, nem no padrão sem ser gestor.
        self.assertEqual(self.cli(outro).delete(f'{url}{meu[9]}/?painel=meu').status_code, 403)   # sem grupo do almoxarifado
        self.assertEqual(c.delete(f'{url}{p1.id}/').status_code, 403)                              # padrão é do gestor

        # Voltar ao padrão apaga só o painel próprio daquela filial.
        r = c.delete(f'{url}?filial=0')
        self.assertEqual((r.status_code, r.data['removidos']), (200, 2))
        self.assertEqual(ins.selecao_efetiva(0, self.leitor)[1], False)
        self.assertEqual(codigos(ins.monitorados_app(0)), [1702, 1703])

    def test_leitor_nao_edita_mas_ve(self):
        self.assertEqual(self.cli(self.leitor).post('/catalogos/erp/almoxarifado/insumos/monitorados/',
                                                    {'tipo': 'grupo', 'codigo': 1}, format='json').status_code, 403)
        with mock.patch.object(ins, 'painel', return_value={'itens': []}), \
                mock.patch.object(a, 'filiais', return_value=[]):
            r = self.cli(self.leitor).get('/catalogos/erp/almoxarifado/insumos/', {'dias': 90})
            self.assertEqual((r.status_code, r.data['pode_editar']), (200, False))
            self.assertEqual(self.cli(self.leitor).get('/catalogos/erp/almoxarifado/insumos/', {'dias': 7}).status_code, 400)


class SerieItemTest(SimpleTestCase):
    """Série do detalhe do item por semana / mês / ano (25/11/2026)."""

    def _mov(self):
        return pd.DataFrame([
            {'ESTQ': 7, 'DIA': '2026-11-24', 'TIPO': 2, 'QUANT': -10, 'VALOR': -5},   # semana atual (seg 23/11)
            {'ESTQ': 7, 'DIA': '2026-11-20', 'TIPO': 2, 'QUANT': -4, 'VALOR': -2},    # semana anterior
            {'ESTQ': 7, 'DIA': '2026-10-05', 'TIPO': 2, 'QUANT': -1, 'VALOR': -1},
            {'ESTQ': 7, 'DIA': '2025-03-01', 'TIPO': 2, 'QUANT': -100, 'VALOR': -50},
            {'ESTQ': 7, 'DIA': '2026-11-24', 'TIPO': 1, 'QUANT': 999, 'VALOR': 999},  # entrada não conta
            {'ESTQ': 8, 'DIA': '2026-11-24', 'TIPO': 2, 'QUANT': -50, 'VALOR': -50},  # outro item
        ])

    def test_semana(self):
        r = ins.montar_serie_item(self._mov(), 7, 'semana', date(2026, 11, 25))
        b = r['barras']
        self.assertEqual(len(b), 12)
        self.assertEqual(b[-1]['inicio'], '2026-11-23')
        self.assertEqual(b[-1]['fim'], '2026-11-25')
        self.assertTrue(b[-1]['parcial'])
        self.assertEqual(b[-1]['quantidade'], 10)
        self.assertEqual(b[-2]['quantidade'], 4)

    def test_mes(self):
        b = ins.montar_serie_item(self._mov(), 7, 'mes', date(2026, 11, 25))['barras']
        self.assertEqual(len(b), 12)
        self.assertEqual(b[0]['inicio'], '2025-12-01')
        self.assertEqual(b[-1]['quantidade'], 14)
        self.assertEqual(b[-2]['quantidade'], 1)
        self.assertEqual(b[-1]['eixo'], 'nov/26')

    def test_ano(self):
        b = ins.montar_serie_item(self._mov(), 7, 'ano', date(2026, 11, 25))['barras']
        self.assertEqual([x['eixo'] for x in b], ['2022', '2023', '2024', '2025', '2026'])
        self.assertEqual(b[-2]['quantidade'], 100)
        self.assertEqual(b[-1]['quantidade'], 15)
        self.assertFalse(b[-2]['parcial'])
