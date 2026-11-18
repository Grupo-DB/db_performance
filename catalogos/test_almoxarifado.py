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

    def test_consumo_pelo_periodo_escolhido(self):
        # 90 un em 30 dias = 3/dia: saldo 15 dura 5 dias → atenção; em 90 dias seria 1/dia (15 d, ok).
        linhas = pd.DataFrame([item(1, 12, 15, 0)])
        df30 = a.preparar_itens(linhas, self.GRUPOS, consumo={1: 90.0}, dias_consumo=30, consumo_valor={1: 450.0})
        r = df30.iloc[0]
        self.assertEqual((r.CONSUMO, r.CONSUMO_DIA, r.COBERTURA_DIAS, bool(r.ATENCAO)), (90.0, 3.0, 5.0, True))
        it = a._item(next(df30.itertuples()))
        self.assertEqual((it['consumo'], it['consumo_valor'], it['consumo_dia']), (90.0, 450.0, 3.0))
        self.assertEqual(a._contas(df30)['consumo_valor'], 450.0)
        self.assertFalse(a.preparar_itens(linhas, self.GRUPOS, consumo={1: 90.0}).iloc[0].ATENCAO)

    def test_periodo_do_consumo(self):
        hoje = date(2026, 11, 17)
        self.assertEqual(a.periodo_consumo(hoje=hoje), (date(2026, 8, 20), hoje))      # 90 dias com hoje
        self.assertEqual(a.periodo_consumo(date(2026, 1, 1), date(2026, 3, 31), hoje),
                         (date(2026, 1, 1), date(2026, 3, 31)))
        for d, f in ((date(2026, 3, 1), date(2026, 2, 1)), (None, date(2026, 11, 18)), (date(2024, 1, 1), None)):
            with self.assertRaises(ValueError):
                a.periodo_consumo(d, f, hoje)

    def test_minimo_do_manager_substitui_o_do_sga_por_filial(self):
        linhas = pd.DataFrame([dict(item(1, 12, 5, 99), FIL=0), dict(item(1, 12, 5, 7), FIL=3),
                               dict(item(2, 12, 5, 8), FIL=0)])
        sga = a.preparar_itens(linhas, self.GRUPOS).set_index('ESTQCOD')
        self.assertEqual(sga.loc[1].MINIMO, 106)
        self.assertFalse(sga.loc[1].MIN_MANAGER)
        # Manager só tem o item 1 na matriz (10) e zera o item 2: filial 3 segue com o do SGA.
        man = a.preparar_itens(linhas, self.GRUPOS, minimos={(1, 0): 10, (2, 0): 0}).set_index('ESTQCOD')
        self.assertEqual(man.loc[1].MINIMO, 17)
        self.assertEqual(man.loc[1].MINIMO_SGA, 106)
        self.assertTrue(man.loc[1].MIN_MANAGER)
        self.assertTrue(man.loc[1].ABAIXO)
        self.assertFalse(man.loc[2].TEM_MIN)

    def test_listas_por_grupo(self):
        df = a.preparar_itens(pd.DataFrame([item(1, 12, 1, 5), item(2, 12, 9, 5), item(3, 11, 2, 0), item(4, 11, 0, 0)]),
                              self.GRUPOS, consumo={3: 90.0})
        self.assertEqual(list(a.filtrar_itens(df, self.GRUPOS, 11, 'abaixo').ESTQCOD), [1])  # neto entra
        self.assertEqual(list(a.filtrar_itens(df, self.GRUPOS, None, 'atencao').ESTQCOD), [3])
        self.assertEqual(sorted(a.filtrar_itens(df, self.GRUPOS, 10, 'todos').ESTQCOD), [1, 2, 3])  # 4 é morto
        self.assertEqual(a._item(next(a.filtrar_itens(df, self.GRUPOS, None, 'atencao').itertuples()))['situacao'], 'atencao')


class CompraEmAndamentoTests(SimpleTestCase):
    """Requisição/processo de compra em aberto aparece no item, com a etapa."""

    @staticmethod
    def linha(estq, req, sit, **kw):
        base = {'ESTQ': estq, 'FIL': 0, 'REQ': req, 'DATA_REQ': pd.Timestamp('2026-11-01'), 'QUANT': 10.0,
                'SIT': sit, 'PRIORIDADE': 0, 'REQUISITANTE': 'FULANO ', 'COMPRADOR': '',
                'ORDEM': float('nan'), 'DATA_ORDEM': pd.NaT, 'APROV_ORDEM': float('nan'), 'FORNECEDOR': '',
                'QUANT_ORDEM': float('nan'), 'QUANT_RECEBIDA': float('nan'), 'QUANT_CANCELADA': float('nan'),
                'PREVISAO': pd.NaT, 'COLETAS': 0}
        base.update(kw)
        return base

    def test_etapas_e_resumo(self):
        df = pd.DataFrame([
            self.linha(1, 100, 0),
            self.linha(1, 101, 2, ORDEM=500.0, DATA_ORDEM=pd.Timestamp('2026-11-02'), APROV_ORDEM=0.0,
                       FORNECEDOR='ACME', QUANT_ORDEM=10.0, QUANT_RECEBIDA=4.0, QUANT_CANCELADA=0.0,
                       PREVISAO=pd.Timestamp('2026-11-10')),
            self.linha(2, 102, 1, COLETAS=3, PRIORIDADE=1),
            # Ordem já recebida por inteiro: não está mais em andamento.
            self.linha(3, 103, 2, ORDEM=501.0, APROV_ORDEM=1.0, QUANT_ORDEM=5.0, QUANT_RECEBIDA=5.0,
                       QUANT_CANCELADA=0.0, PREVISAO=pd.Timestamp('2026-11-05')),
            self.linha(4, 104, 4),      # cancelado não entra
        ])
        c = a.montar_compras(df, date(2026, 11, 16))
        self.assertEqual(sorted(c), [1, 2])
        ordem, req = c[1]                                  # mais adiantada primeiro
        self.assertEqual((ordem['etapa'], ordem['ordem'], ordem['quantidade']), ('ordem', 500, 6.0))
        self.assertEqual(ordem['detalhe'], 'aguardando aprovação, entrega parcial, entrega atrasada')
        self.assertTrue(ordem['atrasada'])
        self.assertEqual((req['etapa'], req['ordem'], req['requisitante']), ('requisicao', None, 'FULANO'))
        self.assertEqual((c[2][0]['etapa'], c[2][0]['detalhe'], c[2][0]['urgente']), ('coleta', '3 cotações', True))

        r = a.resumo_compra(c[1])
        self.assertEqual((r['compra_etapa'], r['em_compra']), ('ordem', 16.0))
        self.assertEqual(r['compra_texto'], 'Ordem de compra 500 — aguardando aprovação, entrega parcial, entrega atrasada (+1)')
        self.assertEqual(a.resumo_compra(None)['compra_etapa'], None)

    def test_nota_so_pre_lancada_nao_conta_como_recebida(self):
        # OC 143002: 70 de 70 "faturados" no SGA, mas a nota 239917 está pendente.
        df = pd.DataFrame([
            self.linha(5, 76022, 2, ORDEM=143002.0, APROV_ORDEM=1.0, QUANT_ORDEM=70.0, QUANT_RECEBIDA=70.0,
                       QUANT_CANCELADA=0.0, QUANT_NF_PENDENTE=70.0, NF_PENDENTE=239917.0),
            # Metade registrada, metade em nota pendente: falta só a pendente.
            self.linha(6, 76023, 2, ORDEM=143003.0, APROV_ORDEM=1.0, QUANT_ORDEM=10.0, QUANT_RECEBIDA=10.0,
                       QUANT_CANCELADA=0.0, QUANT_NF_PENDENTE=5.0, NF_PENDENTE=240000.0),
        ])
        c = a.montar_compras(df, date(2026, 11, 17))
        self.assertEqual((c[5][0]['quantidade'], c[5][0]['recebido'], c[5][0]['detalhe']), (70.0, 0.0, ''))
        self.assertEqual(c[5][0]['nota_pendente'], {'numero': 239917, 'quantidade': 70.0})
        self.assertEqual((c[6][0]['quantidade'], c[6][0]['detalhe'], c[6][0]['nota_pendente']['quantidade']),
                         (5.0, 'entrega parcial', 5.0))
        r = a.resumo_compra(c[5])
        self.assertEqual((r['nota_pendente']['numero'], r['compra_texto']),
                         (239917, 'Ordem de compra 143002 — nota 239917 pendente de registro'))
        self.assertIsNone(a.resumo_compra(None)['nota_pendente'])

    def test_lista_e_contas(self):
        df = a.preparar_itens(pd.DataFrame([item(1, 12, 1, 5), item(2, 12, 9, 5)]), GRUPOS)
        a.juntar_compras(df, a.montar_compras(pd.DataFrame([self.linha(1, 100, 0)]), date(2026, 11, 16)))
        self.assertEqual(list(a.filtrar_itens(df, GRUPOS, None, 'em_compra').ESTQCOD), [1])
        contas = a._contas(df)
        self.assertEqual((contas['em_compra'], contas['abaixo_em_compra']), (1, 1))
        self.assertEqual(a._item(next(df[df.ESTQCOD == 1].itertuples()))['compra_etapa'], 'requisicao')

    def test_cotacoes_da_coleta(self):
        def cot(proc, forn, unit, pcooc=0, prazo=float('nan')):
            return {'IPCOM': 900, 'PROCESSO': proc, 'DATA': pd.Timestamp('2026-11-16'), 'FORNECEDOR': forn + ' ',
                    'QUANT': 2.0, 'UNIT': unit, 'TOTAL': unit * 2, 'DESCONTO': 0.0, 'PRAZO': prazo,
                    'PAGAMENTO': 'A VISTA', 'TIPO_FRETE': 2, 'FRETE': 0.0, 'PCOOC': pcooc}
        cots = a.montar_cotacoes(pd.DataFrame([
            cot(10, 'SEM RESPOSTA', 0.0),
            cot(11, 'CARO', 150.0, prazo=5.0),
            cot(12, 'BARATO', 96.0),
            cot(13, 'DESCLASSIFICADO', 50.0, pcooc=12),
        ]))
        lista = cots[900]
        self.assertEqual([c['fornecedor'] for c in lista], ['BARATO', 'CARO', 'DESCLASSIFICADO', 'SEM RESPOSTA'])
        self.assertEqual([c['melhor'] for c in lista], [True, False, False, False])
        self.assertEqual((lista[0]['total'], lista[1]['prazo_dias'], lista[0]['frete']), (192.0, 5, 'CIF (fornecedor)'))
        self.assertEqual((lista[3]['unitario'], lista[3]['respondida']), (None, False))

        df = pd.DataFrame([self.linha(2, 102, 1, IPCOM=900, COLETAS=4)])
        coleta = a.montar_compras(df, date(2026, 11, 16), cots)[2][0]
        self.assertEqual(len(coleta['cotacoes']), 4)
        self.assertEqual(coleta['detalhe'], '4 cotações, 3 respondidas')


class FotoTests(SimpleTestCase):
    """Marca quem tem foto no SGA (ESTOQUEFOTO) e reduz a foto para a tela."""

    def test_marca_lista_e_contas(self):
        df = a.preparar_itens(pd.DataFrame([item(1, 12, 5, 0), item(2, 12, 5, 0), item(3, 12, 0, 0)]), GRUPOS)
        a.juntar_fotos(df, {1, 3})
        self.assertEqual([a._item(r)['tem_foto'] for r in df.sort_values('ESTQCOD').itertuples()], [True, False, True])
        self.assertEqual(list(a.filtrar_itens(df, GRUPOS, None, 'sem_foto').ESTQCOD), [2])
        c = a._contas(df)
        self.assertEqual((c['com_foto'], c['sem_foto']), (1, 1))     # o 3 não tem saldo: não conta

    def test_sem_leitura_nao_marca(self):
        df = a.preparar_itens(pd.DataFrame([item(1, 12, 5, 0)]), GRUPOS)
        a.juntar_fotos(df, None)
        self.assertNotIn('TEM_FOTO', df)
        self.assertEqual(a._contas(df)['sem_foto'], 0)

    def test_miniatura_bmp_vira_jpeg_pequeno(self):
        from io import BytesIO
        from PIL import Image
        buf = BytesIO()
        Image.new('RGB', (1200, 900), (200, 30, 30)).save(buf, format='BMP')
        jpg = a.miniatura(buf.getvalue(), 300)
        img = Image.open(BytesIO(jpg))
        self.assertEqual((img.format, max(img.size)), ('JPEG', 300))
        self.assertIsNone(a.miniatura(b'nao e imagem'))


from django.contrib.auth.models import User
from django.test import TestCase


class EdicaoTests(TestCase):
    def test_salvar_e_apagar_minimo(self):
        from catalogos.models import MinimoEstoque, PrazoAtencaoGrupo
        u = User.objects.create(username='almox')
        a.salvar_minimos(0, [{'codigo': 1, 'minimo': '10,5'.replace(',', '.')}, {'codigo': 2, 'minimo': 3}], u)
        a.salvar_minimos(3, [{'codigo': 1, 'minimo': 4}], u)
        self.assertEqual(a.minimos_app(0), {(1, 0): 10.5, (2, 0): 3.0})
        self.assertEqual(a.minimos_app(None), {(1, 0): 10.5, (2, 0): 3.0, (1, 3): 4.0})
        a.salvar_minimos(0, [{'codigo': 2, 'minimo': None}, {'codigo': 1, 'minimo': 0}], u)
        self.assertFalse(MinimoEstoque.objects.filter(item=2).exists())
        self.assertEqual(a.minimos_app(0), {(1, 0): 0.0})  # zero fica gravado: anula o do SGA
        with self.assertRaises(ValueError):
            a.salvar_minimos(0, [{'codigo': 1, 'minimo': -1}], u)
        a.salvar_prazo(1703, 45, u)
        self.assertEqual(a.prazos_app(), {1703: 45})
        a.salvar_prazo(1703, None, u)
        self.assertFalse(PrazoAtencaoGrupo.objects.exists())
        with self.assertRaises(ValueError):
            a.salvar_prazo(1, 0, u)


class FotoEndpointTests(TestCase):
    def test_foto_exige_acesso_e_devolve_data_url(self):
        from unittest import mock
        from rest_framework.test import APIClient
        self.client = APIClient()
        u = User.objects.create(username='almox-foto', is_superuser=True)
        self.client.force_authenticate(u)
        with mock.patch.object(a, 'foto_item', return_value=b'\xff\xd8jpg') as f:
            r = self.client.get('/catalogos/erp/almoxarifado/foto/747/?lado=200')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['imagem'].startswith('data:image/jpeg;base64,'))
        f.assert_called_once_with(747, 200)
        with mock.patch.object(a, 'foto_item', return_value=None):
            self.assertIsNone(self.client.get('/catalogos/erp/almoxarifado/foto/1/').json()['imagem'])
        self.client.force_authenticate(None)
        self.assertIn(self.client.get('/catalogos/erp/almoxarifado/foto/1/').status_code, (401, 403))
