from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient


class AcessoBiComercialTests(TestCase):
    """Módulo BI separado dos pedidos (24/11/2026): só Admin, Master e comercialBI."""

    def cliente(self, grupo=None):
        u = User.objects.create_user(f'u_{grupo}', password='x')
        if grupo:
            u.groups.add(Group.objects.get_or_create(name=grupo)[0])
        c = APIClient()
        c.force_authenticate(u)
        return c

    @mock.patch('biComercial.comercial.painel', return_value={'ok': True})
    @mock.patch('biComercial.comercial.saldo', return_value={'ok': True})
    def test_grupos(self, _saldo, _painel):
        for grupo, esperado in (('comercialBI', 200), ('Master', 200), ('Admin', 200), ('vendasGestao', 403), (None, 403)):
            c = self.cliente(grupo)
            self.assertEqual(c.get('/bi/comercial/').status_code, esperado, grupo)
            self.assertEqual(c.get('/bi/comercial/saldo-pedidos/').status_code, esperado, grupo)
        self.assertEqual(APIClient().get('/bi/comercial/').status_code in (401, 403), True)


class MesDiarioTests(TestCase):
    """Mês a mês (25/11/2026): cada dia do mês e comparação com o mesmo período do mês anterior."""

    def _df(self):
        import pandas as pd
        from . import comercial as bi
        linhas = []
        for dia, valor, t in (('2026-10-03', 100.0, 1.0), ('2026-10-20', 500.0, 5.0), ('2026-11-03', 300.0, 2.0), ('2026-11-05', 200.0, 1.0)):
            linhas.append({'FILIAL': 'F1', 'DATA': pd.Timestamp(dia), 'NOTA': len(linhas) + 1, 'NFCOD': len(linhas) + 1, 'TIPO_NF': 'S',
                           'NATUREZA': 'N', 'CLIENTE': f'C{len(linhas)}', 'CLIENTE_COD': len(linhas), 'CNPJ': '', 'CIDADE': 'X',
                           'CIDADE_FAT': 'X-RS', 'UF_FAT': 'RS', 'REPRESENTANTE': 'R', 'PRODUTO': 'P', 'ESTOQUE': '', 'ESTOQUE_COD': 1,
                           'UNIDADE': 'TN', 'GRUPO': '', 'GRUPO_GESTAO': 'G', 'SEGMENTO': 'S', 'REGIAO': 'Rg', 'QTD': t, 'TN': t,
                           'VALOR': valor, 'FAT': True, 'CARR': True})
        df = pd.DataFrame(linhas)
        df['MES'] = df.DATA.dt.strftime('%Y-%m')
        return df

    def test_dias_e_comparacao(self):
        from datetime import date
        from . import comercial as bi
        with mock.patch.object(bi, 'ler_faturamento', return_value=self._df()) as ler:
            m = bi.mes_diario('2026-11', {}, hoje=date(2026, 11, 10))
            self.assertEqual(ler.call_args.args, (date(2026, 10, 1), date(2026, 11, 30)))
            self.assertEqual(len(m['dias']), 30)
            self.assertEqual((m['totais']['valor'], m['totais']['notas'], m['totais']['dias_com_venda']), (500.0, 2, 2))
            # mês corrente: outubro só até o dia 10
            self.assertEqual((m['anterior']['mesmo_periodo']['valor'], m['anterior']['mes_inteiro']['valor']), (100.0, 600.0))
            self.assertEqual((m['dias'][2]['valor'], m['dias'][2]['anterior_valor'], m['dias'][10]['futuro']), (300.0, 100.0, True))
            self.assertEqual(m['melhor_dia'], {'data': '2026-11-03', 'valor': 300.0})
            d = bi.dia_detalhe(date(2026, 11, 3), {})
            self.assertEqual((len(d['notas']), d['notas'][0]['cidade'], d['totais']['valor']), (1, 'X-RS', 300.0))
        with self.assertRaises(ValueError):
            bi.mes_diario('2026-13', {})
