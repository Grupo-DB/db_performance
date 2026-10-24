"""Histórico dos ensaios específicos (argamassa/colantes) — 23/10/2026.

    venv/bin/python manage.py test controleQualidade.analise.tests_historico_especifico \
        --settings=db_performance.settings_teste_projeto
"""
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from controleQualidade.amostra.models import Amostra, ProdutoAmostra
from controleQualidade.analise.models import Analise

URL = '/analise/analise/historico-especifico/'


class HistoricoEspecificoTests(TestCase):
    def setUp(self):
        self.prod = ProdutoAmostra.objects.create(nome='PRIMEX REVESTIMENTO', material='argamassa')
        outro = ProdutoAmostra.objects.create(nome='COLANTE AC-II', material='argamassa')

        def analise(n, dia, prod, **campos):
            am = Amostra.objects.create(laboratorio='Matriz', material='Argamassa', numero=f'argamassa 00.{n:04d}',
                                        data_entrada=date(2026, 10, dia), produto_amostra=prod)
            return Analise.objects.create(amostra=am, estado='PENDENTE', **campos)

        self.a1 = analise(1, 1, self.prod, substrato={'media': 0.31, 'linhas': []})
        self.a2 = analise(2, 5, self.prod, substrato={'media': 0.42, 'linhas': []}, flexao={'media_geral': 0.8})
        self.a3 = analise(3, 9, outro, substrato={'media': 0.25, 'linhas': []})
        self.vazia = analise(4, 12, self.prod, substrato={})           # {} não é resultado
        self.sem = analise(5, 15, self.prod)                           # nada gravado
        self.cli = APIClient()
        self.cli.force_authenticate(User.objects.create_user('lab', password='x'))

    def get(self, **q):
        r = self.cli.get(URL, q)
        self.assertEqual(r.status_code, 200, r.content)
        return r.data

    def test_mais_recente_primeiro_e_sem_vazios(self):
        d = self.get(campos='substrato')
        self.assertEqual([x['analise_id'] for x in d], [self.a3.id, self.a2.id, self.a1.id])
        self.assertEqual(d[0]['produto'], 'COLANTE AC-II')
        self.assertEqual(d[1]['substrato']['media'], 0.42)

    def test_filtros_produto_excluir_limite(self):
        d = self.get(campos='substrato', produto=self.prod.id, excluir=self.a2.id)
        self.assertEqual([x['analise_id'] for x in d], [self.a1.id])
        self.assertEqual(len(self.get(campos='substrato', limite=1)), 1)

    def test_varios_campos(self):
        d = self.get(campos='flexao,compressao')
        self.assertEqual([x['analise_id'] for x in d], [self.a2.id])
        self.assertIsNone(d[0]['compressao'])

    def test_campo_fora_da_lista_e_sem_login(self):
        self.assertEqual(self.cli.get(URL, {'campos': 'amostra__numero'}).status_code, 400)
        self.assertEqual(APIClient().get(URL, {'campos': 'substrato'}).status_code, 401)
