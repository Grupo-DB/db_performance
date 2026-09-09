"""
Testes da numeração de amostra — o caso que existia em produção: duas amostras
gravadas com "cal 00.0440".

O número era escolhido pelo navegador (prévia do formulário) e nada no banco
impedia repetição. Agora quem numera é o servidor, dentro da transação do INSERT
(ver numeracao.py e AmostraViewSet.perform_create). Estes testes fixam as três
garantias que essa mudança precisa manter:

1. o número do POST é ignorado — vem outro, o próximo livre;
2. a sequência continua de onde a numeração legada parou;
3. na EDIÇÃO, apontar para um número de outra amostra é 400, não duplicata.

E as da duplicata/reanálise (09/2026): a derivada recebe '.1', '.2' na mesma
família e NÃO desloca o sequencial do prefixo.

    venv/bin/python manage.py test controleQualidade.amostra.tests \
        --settings=db_performance.settings_teste_projeto

(o --settings é obrigatório: sem ele o test runner cria banco de teste no
MySQL de PRODUÇÃO — ver db_performance/settings_teste_projeto.py)
"""
import copy
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from controleQualidade.ordem.models import OrdemExpressa

from .models import Amostra
from .numeracao import (formatar_numero, normalizar_prefixo, numeros_duplicados,
                        proximo_numero_derivada, separar_derivada, sequencial_de)


class NumeracaoHelpersTests(TestCase):
    def test_normalizar_prefixo_igual_ao_front(self):
        self.assertEqual(normalizar_prefixo(' Calcário '), 'calcario')
        self.assertEqual(normalizar_prefixo('CAL'), 'cal')
        self.assertEqual(normalizar_prefixo(None), '')

    def test_formato_do_numero(self):
        self.assertEqual(formatar_numero('cal', 440), 'cal 00.0440')
        self.assertEqual(formatar_numero('argamassa', 7), 'argamassa 00.0007')

    def test_sequencial_de_le_formato_legado(self):
        self.assertEqual(sequencial_de('cal 00.0440'), 440)
        self.assertEqual(sequencial_de('Calcário 08.392'), 8392)   # numeração antiga
        self.assertIsNone(sequencial_de('cal'))
        self.assertIsNone(sequencial_de(''))

    def test_separar_derivada(self):
        self.assertEqual(separar_derivada('calcario 00.0526.1'), ('calcario 00.0526', 1))
        self.assertEqual(separar_derivada('calcario 00.0526.12'), ('calcario 00.0526', 12))
        # Número normal e legado não são derivadas: têm um grupo de dígitos só.
        self.assertEqual(separar_derivada('calcario 00.0526'), ('calcario 00.0526', None))
        self.assertEqual(separar_derivada('Calcário 08.392'), ('Calcário 08.392', None))

    def test_derivada_nao_desloca_o_sequencial_do_prefixo(self):
        """O estrago que o sufixo faria: '00.0526.1' lido como 5.261."""
        self.assertEqual(sequencial_de('calcario 00.0526.1'), 526)


class NumeracaoNaApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def payload(self, **extra):
        dados = {
            'laboratorio': 'Matriz',
            'material': 'Cal',
            'numero': 'cal 00.0440',      # prévia que a tela mandaria
            'finalidade': 'Controle de Qualidade',
        }
        dados.update(extra)
        return dados

    def test_dois_posts_com_o_mesmo_numero_nao_duplicam(self):
        """O caso do bug: a tela manda 'cal 00.0440' duas vezes."""
        primeira = self.client.post('/amostra/amostra/', self.payload(), format='json')
        segunda = self.client.post('/amostra/amostra/', self.payload(), format='json')

        self.assertEqual(primeira.status_code, 201, primeira.data)
        self.assertEqual(segunda.status_code, 201, segunda.data)
        self.assertEqual(primeira.data['numero'], 'cal 00.0001')   # banco vazio no teste
        self.assertEqual(segunda.data['numero'], 'cal 00.0002')
        self.assertEqual(Amostra.objects.filter(numero='cal 00.0001').count(), 1)

    def test_continua_a_sequencia_existente(self):
        Amostra.objects.create(laboratorio='Matriz', material='Cal', numero='cal 00.0440')

        resposta = self.client.post('/amostra/amostra/', self.payload(), format='json')

        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data['numero'], 'cal 00.0441')

    def test_prefixo_vem_do_material(self):
        resposta = self.client.post(
            '/amostra/amostra/', self.payload(material='Calcário'), format='json')

        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data['numero'], 'calcario 00.0001')

    def test_duplicata_nao_repete_o_numero_da_original(self):
        """`duplicata()` das telas de Ordem/Arquivo manda o número em branco."""
        original = Amostra.objects.create(
            laboratorio='Matriz', material='Cal', numero='cal 00.0440')

        resposta = self.client.post(
            '/amostra/amostra/', self.payload(numero=''), format='json')

        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertNotEqual(resposta.data['numero'], original.numero)
        self.assertEqual(resposta.data['numero'], 'cal 00.0441')

    def test_duplicata_recebe_indice_na_familia_da_original(self):
        original = Amostra.objects.create(
            laboratorio='Matriz', material='Calcário', numero='calcario 00.0526')

        primeira = self.client.post('/amostra/amostra/', self.payload(
            material='Calcário', finalidade='Duplicata', amostra_origem=original.id,
        ), format='json')
        segunda = self.client.post('/amostra/amostra/', self.payload(
            material='Calcário', finalidade='Reanálise', amostra_origem=original.id,
        ), format='json')

        self.assertEqual(primeira.status_code, 201, primeira.data)
        self.assertEqual(primeira.data['numero'], 'calcario 00.0526.1')
        self.assertEqual(segunda.data['numero'], 'calcario 00.0526.2')

    def test_derivada_nao_consome_sequencial_do_material(self):
        """Depois de duas duplicatas, a próxima amostra comum ainda é a 0527."""
        original = Amostra.objects.create(
            laboratorio='Matriz', material='Calcário', numero='calcario 00.0526')
        for _ in range(2):
            self.client.post('/amostra/amostra/', self.payload(
                material='Calcário', finalidade='Duplicata', amostra_origem=original.id,
            ), format='json')

        nova = self.client.post(
            '/amostra/amostra/', self.payload(material='Calcário'), format='json')

        self.assertEqual(nova.data['numero'], 'calcario 00.0527')

    def test_duplicata_de_derivada_vira_irma(self):
        """`.1.1` não existe: pedir a partir da .1 devolve a .2."""
        original = Amostra.objects.create(
            laboratorio='Matriz', material='Calcário', numero='calcario 00.0526')
        derivada = Amostra.objects.create(
            laboratorio='Matriz', material='Calcário', numero='calcario 00.0526.1',
            amostra_origem=original)

        resposta = self.client.post('/amostra/amostra/', self.payload(
            material='Calcário', finalidade='Duplicata', amostra_origem=derivada.id,
        ), format='json')

        self.assertEqual(resposta.data['numero'], 'calcario 00.0526.2')

    def test_familia_vizinha_nao_entra_na_contagem(self):
        """'calcario 00.05261' começa com o mesmo texto mas é outra amostra."""
        original = Amostra.objects.create(
            laboratorio='Matriz', material='Calcário', numero='calcario 00.0526')
        Amostra.objects.create(
            laboratorio='Matriz', material='Calcário', numero='calcario 00.05261')

        self.assertEqual(proximo_numero_derivada(original), 'calcario 00.0526.1')

    def test_busca_filtra_por_material_nas_duas_grafias(self):
        """A base tem 'Calcario' e 'Calcário'; escolher um material pega os dois."""
        Amostra.objects.create(laboratorio='Matriz', material='Calcário', numero='calcario 00.0001')
        Amostra.objects.create(laboratorio='Matriz', material='Calcario', numero='calcario 00.0002')
        Amostra.objects.create(laboratorio='Matriz', material='Cal', numero='cal 00.0001')

        resposta = self.client.get('/amostra/amostra/buscar/?material=Calcário')

        numeros = sorted(a['numero'] for a in resposta.data)
        self.assertEqual(numeros, ['calcario 00.0001', 'calcario 00.0002'])

    def test_previa_do_numero_da_derivada(self):
        original = Amostra.objects.create(
            laboratorio='Matriz', material='Calcário', numero='calcario 00.0526')

        resposta = self.client.get(
            f'/amostra/amostra/{original.id}/proximo-numero-derivada/')

        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data['numero'], 'calcario 00.0526.1')

    def test_serializer_liga_os_dois_lados(self):
        original = Amostra.objects.create(
            laboratorio='Matriz', material='Calcário', numero='calcario 00.0526')
        criada = self.client.post('/amostra/amostra/', self.payload(
            material='Calcário', finalidade='Duplicata', amostra_origem=original.id,
        ), format='json').data

        self.assertEqual(criada['amostra_origem_detalhes']['numero'], 'calcario 00.0526')

        vista_da_original = self.client.get(f'/amostra/amostra/{original.id}/').data
        numeros = [d['numero'] for d in vista_da_original['derivadas_detalhes']]
        self.assertEqual(numeros, ['calcario 00.0526.1'])

    def test_amostra_nao_pode_ser_duplicata_dela_mesma(self):
        amostra = Amostra.objects.create(
            laboratorio='Matriz', material='Calcário', numero='calcario 00.0526')

        resposta = self.client.patch(
            f'/amostra/amostra/{amostra.id}/', {'amostra_origem': amostra.id}, format='json')

        self.assertEqual(resposta.status_code, 400, resposta.data)

    def test_sem_material_recusa(self):
        resposta = self.client.post(
            '/amostra/amostra/', {'laboratorio': 'Matriz', 'numero': ''}, format='json')

        self.assertEqual(resposta.status_code, 400, resposta.data)

    def test_edicao_para_numero_de_outra_amostra_e_recusada(self):
        Amostra.objects.create(laboratorio='Matriz', material='Cal', numero='cal 00.0440')
        outra = Amostra.objects.create(laboratorio='Matriz', material='Cal', numero='cal 00.0441')

        resposta = self.client.patch(
            f'/amostra/amostra/{outra.id}/', {'numero': 'cal 00.0440'}, format='json')

        self.assertEqual(resposta.status_code, 400, resposta.data)
        outra.refresh_from_db()
        self.assertEqual(outra.numero, 'cal 00.0441')


class ComandoNumerosAmostraTests(TransactionTestCase):
    """Ensaia o conserto que vai rodar na produção, onde as duplicatas já existem.

    O banco de teste nasce do model, ou seja, JÁ com o índice único — nele nem dá
    para gravar duplicata. Então o teste primeiro derruba a restrição (é o estado
    do MySQL de produção hoje), sujeita o banco às duas amostras com o mesmo
    número e só aí chama o comando.

    TransactionTestCase, e não TestCase, porque mexer no esquema do SQLite exige
    ficar fora da transação do teste e com a checagem de FK desligada.
    """

    def setUp(self):
        self.campo_unico = Amostra._meta.get_field('numero')
        self.campo_livre = copy.deepcopy(self.campo_unico)
        self.campo_livre._unique = False
        self.alterar_campo(self.campo_unico, self.campo_livre)

    def tearDown(self):
        # Devolve o índice único: TransactionTestCase limpa as linhas, não o esquema,
        # e as outras classes de teste contam com a restrição no lugar.
        try:
            self.alterar_campo(self.campo_livre, self.campo_unico)
        except Exception:
            pass

    def alterar_campo(self, de_campo, para_campo):
        with connection.constraint_checks_disabled():
            with connection.schema_editor() as editor:
                editor.alter_field(Amostra, de_campo, para_campo)

    def test_corrige_duplicata_e_cria_indice(self):
        primeira = Amostra.objects.create(
            laboratorio='Matriz', material='Cal', numero='cal 00.0440', local_coleta='Saco')
        segunda = Amostra.objects.create(
            laboratorio='Matriz', material='Cal', numero='cal 00.0440', local_coleta='Silo 06')

        self.assertEqual(list(numeros_duplicados()), ['cal 00.0440'])

        saida = StringIO()
        call_command('numeros_amostra', corrigir=True, criar_indice=True, stdout=saida)
        relatorio = saida.getvalue()

        primeira.refresh_from_db()
        segunda.refresh_from_db()
        # A mais antiga mantém o número; a outra recebe o próximo livre.
        self.assertEqual(primeira.numero, 'cal 00.0440')
        self.assertEqual(segunda.numero, 'cal 00.0441')
        self.assertEqual(numeros_duplicados(), {})
        self.assertIn('renumerada', relatorio)
        self.assertIn('Índice único', relatorio)

        # Com o índice no lugar, o banco passa a recusar a repetição.
        with connection.cursor() as cursor:
            indices = connection.introspection.get_constraints(cursor, Amostra._meta.db_table)
        self.assertTrue(any(d.get('columns') == ['numero'] and d.get('unique')
                            for d in indices.values()))

    def test_quem_tem_os_fica_com_o_numero_mesmo_sendo_a_mais_nova(self):
        """Renumerar a amostra em uso seria o pior conserto: o número dela circulou.

        Caso real de produção (`cal 00.0317`): a órfã era a MAIS ANTIGA e a que
        tinha OS era a mais nova.
        """
        expressa = OrdemExpressa.objects.create(data='2026-08-05', numero='EXP-1')
        orfa = Amostra.objects.create(
            laboratorio='Matriz', material='Cal', numero='cal 00.0317')
        com_os = Amostra.objects.create(
            laboratorio='Matriz', material='Cal', numero='cal 00.0317', expressa=expressa)
        self.assertLess(orfa.id, com_os.id)

        saida = StringIO()
        call_command('numeros_amostra', corrigir=True, stdout=saida)

        orfa.refresh_from_db()
        com_os.refresh_from_db()
        self.assertEqual(com_os.numero, 'cal 00.0317')      # em uso: não mexe
        self.assertEqual(orfa.numero, 'cal 00.0318')        # órfã: renumerada
        self.assertIn('tem OS/análise', saida.getvalue())

    def test_indice_nao_e_criado_com_duplicata_na_tabela(self):
        Amostra.objects.create(laboratorio='Matriz', material='Cal', numero='cal 00.0440')
        Amostra.objects.create(laboratorio='Matriz', material='Cal', numero='cal 00.0440')

        saida = StringIO()
        call_command('numeros_amostra', criar_indice=True, stdout=saida)

        self.assertIn('Índice NÃO criado', saida.getvalue())
        self.assertEqual(list(numeros_duplicados()), ['cal 00.0440'])
