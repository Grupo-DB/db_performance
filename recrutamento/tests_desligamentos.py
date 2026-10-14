"""Testes dos desligamentos (justificativa do gestor + entrevista do funcionário)."""
import csv
import json
import os
import tempfile
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.db import models as djm
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from avaliacoes.management import models as M
from recrutamento import desligamento as dsl
from recrutamento.models import Desligamento, FormularioDesligamento


def _criar(modelo, **fixos):
    """Cria com valores fictícios nos campos obrigatórios que o teste não usa."""
    dados = {}
    for f in modelo._meta.concrete_fields:
        if f.primary_key or f.name in fixos or f.null or f.has_default() or isinstance(f, djm.ForeignKey) \
                or getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False):
            continue
        if isinstance(f, (djm.CharField, djm.TextField)):
            dados[f.name] = 'x'
        elif isinstance(f, (djm.IntegerField, djm.DecimalField, djm.FloatField)):
            dados[f.name] = 0
        elif isinstance(f, djm.BooleanField):
            dados[f.name] = False
    dados.update(fixos)
    return modelo.objects.create(**dados)


class Cadastro:
    """Um mini cadastro de colaboradores com setor e cargo de verdade."""

    def __init__(self):
        self.emp = _criar(M.Empresa, nome='DB')
        self.fil = _criar(M.Filial, empresa=self.emp, nome='Matriz')
        self.area = _criar(M.Area, empresa=self.emp, filial=self.fil, nome='Geral')
        self.setor = _criar(M.Setor, empresa=self.emp, filial=self.fil, area=self.area, nome='MANUTENÇÃO')
        rel = {'Empresa': self.emp, 'Filial': self.fil, 'Area': self.area, 'Setor': self.setor}
        self.amb = _criar(M.Ambiente, nome='Oficina', **{f.name: rel[f.related_model.__name__]
                          for f in M.Ambiente._meta.concrete_fields
                          if isinstance(f, djm.ForeignKey) and f.related_model.__name__ in rel})
        rel['Ambiente'] = self.amb
        self.cargo = _criar(M.Cargo, nome='MECÂNICO', **{f.name: rel[f.related_model.__name__]
                            for f in M.Cargo._meta.concrete_fields
                            if isinstance(f, djm.ForeignKey) and f.related_model.__name__ in rel})

    def colaborador(self, nome, admissao=None):
        return _criar(M.Colaborador, empresa=self.emp, filial=self.fil, setor=self.setor, area=self.area,
                      cargo=self.cargo, ambiente=self.amb, nome=nome, situacao=False,
                      data_admissao=datetime(*admissao) if admissao else None)


class TextoLivreTests(SimpleTestCase):
    def test_tempo_de_casa_digitado(self):
        casos = {'1 ano e 3 meses': 15, ' 12 anos ': 144, '26 dias': 0, '2 meses e pouco': 2, '1 ANO E 1 MÊS': 13,
                 'dois anos': 24, '3 anos e meio': 42, 'sei lá': None}
        for texto, meses in casos.items():
            self.assertEqual(dsl.meses_de_texto(texto), meses, texto)

    def test_multipla_escolha_volta_para_a_grafia_do_formulario(self):
        opcoes = ['Corte de gastos', 'Salário']
        self.assertEqual(dsl.separar_multipla('CORTE DE GASTOS;salário; A filha está doente ', opcoes),
                         ['Corte de gastos', 'Salário', 'A filha está doente'])
        self.assertEqual(dsl.separar_multipla(' - ', opcoes), [])

    def test_resposta_vazia(self):
        for v in ('-', '----', ' . ', '', None, []):
            self.assertTrue(dsl.resposta_vazia(v), repr(v))
        self.assertFalse(dsl.resposta_vazia('Não'))

    def test_casar_colaborador(self):
        cadastro = [SimpleNamespace(nome=n) for n in ('CLEIBE AGLAER MARQUES LIMA', 'WESRLEY DA SILVA MACHADO',
                                                     'BRUNO ACOSTA FLORES', 'BRUNO FLORES DA SILVA')]
        self.assertEqual(dsl.casar_colaborador('Cleibe Aglaer', cadastro)[1], 'contido')
        self.assertEqual(dsl.casar_colaborador('Wersley da Silva Machado', cadastro)[1], 'aproximado')
        # "Bruno Flores" está contido nos dois — ambíguo não casa.
        self.assertEqual(dsl.casar_colaborador('Bruno Flores', cadastro), (None, ''))


def _csv(caminho, cabecalho, linhas):
    with open(caminho, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(cabecalho)
        w.writerows(linhas)


class ImportacaoTests(APITestCase):
    def setUp(self):
        self.cad = Cadastro()
        self.joao = self.cad.colaborador('JOAO DA SILVA PEREIRA', admissao=(2023, 1, 10))
        self.gestor = self.cad.colaborador('MAGNO DIAS PAZ')
        self.pasta = tempfile.mkdtemp()
        g_cab = ['Carimbo', 'Nome', 'Cargo', 'Departamento', 'Gestor', 'Data', 'Tipo'] + \
                [p['texto'] for p in dsl.PERGUNTAS['GESTOR']]
        f_cab = ['Carimbo', 'Nome', 'Cargo', 'Departamento', 'Tempo', 'Data', 'Tipo'] + \
                [p['texto'] for p in dsl.PERGUNTAS['FUNCIONARIO']]
        self.g = os.path.join(self.pasta, 'g.csv')
        self.f = os.path.join(self.pasta, 'f.csv')
        _csv(self.g, g_cab, [
            ['2025/06/06 8:52:30 AM GMT-3', 'Joao da Silva', 'Mecânico', 'Manut. industrial', 'Magno Paz', '2025-06-06',
             'Acordo mútuo', 'Cortes orçamentários;Faltas'] + ['-'] * 11,
        ])
        _csv(self.f, f_cab, [
            ['2025/06/09 8:56:15 AM GMT-3', 'JOÃO DA SILVA', 'MECANICO', 'Manutenção', '2 anos e 5 meses', '2025-06-06',
             'Voluntário', 'Salário;CORTE DE GASTOS'] + ['Acredita que sim.'] * 13,
            ['2025/07/01 10:00:00 AM GMT-3', 'Fulano Sem Cadastro', 'Auxiliar', 'Expedição', '8 meses', '2025-07-01',
             'Involuntário', 'Corte de gastos'] + ['-'] * 13,
        ])

    def test_importa_junta_os_dois_lados_e_e_idempotente(self):
        call_command('importar_desligamentos', gestor=self.g, funcionario=self.f, stdout=open(os.devnull, 'w'))
        self.assertEqual(Desligamento.objects.count(), 2)
        d = Desligamento.objects.get(colaborador=self.joao)
        self.assertEqual(d.formularios.count(), 2)
        # O tipo é o do gestor; o do funcionário fica no formulário dele (divergência).
        self.assertEqual(d.tipo, 'ACORDO')
        self.assertEqual(d.formularios.get(formulario='FUNCIONARIO').tipo_informado, 'VOLUNTARIO')
        self.assertEqual((d.setor, d.cargo, d.data_admissao), ('MANUTENÇÃO', 'MECÂNICO', date(2023, 1, 10)))
        self.assertEqual((d.gestor_id, d.gestor_nome), (self.gestor.id, 'MAGNO DIAS PAZ'))
        self.assertEqual(d.tempo_casa_meses, 28)  # pela admissão do cadastro, não pelo texto
        self.assertIn('Manut. industrial', d.observacao)
        g = d.formularios.get(formulario='GESTOR')
        self.assertEqual(g.respostas['fatores'], ['Cortes orçamentários', 'Faltas'])
        self.assertNotIn('ciencia_melhoria', g.respostas)  # "-" é não respondido
        f = d.formularios.get(formulario='FUNCIONARIO')
        self.assertEqual(f.respostas['motivos'], ['Salário', 'Corte de gastos'])
        self.assertEqual(f.data_preenchimento, date(2025, 6, 9))
        sem = Desligamento.objects.get(colaborador__isnull=True)
        self.assertEqual((sem.nome, sem.setor, sem.tempo_casa_meses), ('FULANO SEM CADASTRO', 'Expedição', 8))

        call_command('importar_desligamentos', gestor=self.g, funcionario=self.f, stdout=open(os.devnull, 'w'))
        self.assertEqual(FormularioDesligamento.objects.count(), 3)

    def test_indicadores(self):
        call_command('importar_desligamentos', gestor=self.g, funcionario=self.f, stdout=open(os.devnull, 'w'))
        for f in FormularioDesligamento.objects.filter(formulario='FUNCIONARIO'):
            f.classificacao = {'motivos': 'Salário', 'valorizado': 'SIM', 'recomendaria': 'NAO'} \
                if f.desligamento.colaborador_id else {'motivos': 'Corte de gastos', 'valorizado': 'SEM_RESPOSTA',
                                                       'recomendaria': 'SIM'}
            f.save()
        i = dsl.indicadores(Desligamento.objects.prefetch_related('formularios'))
        self.assertEqual((i['total'], i['por_tipo']['ACORDO'], i['por_tipo']['INVOLUNTARIO']), (2, 1, 1))
        self.assertEqual(i['cobertura'], {'gestor': 1, 'funcionario': 2, 'ambos': 1})
        self.assertEqual(i['pct_recomendaria'], 50.0)
        valorizado = next(p for p in i['percepcoes_funcionario'] if p['chave'] == 'valorizado')
        self.assertEqual((valorizado['respondidas'], valorizado['contagem']['SIM']), (1, 1))  # sem resposta não conta
        self.assertEqual({m['rotulo'] for m in i['motivo_principal']}, {'Salário', 'Corte de gastos'})
        self.assertEqual(i['pct_menos_1_ano'], 50.0)  # 28 meses e 8 meses
        self.assertEqual(i['divergencias_tipo'][0]['funcionario'], 'Voluntário')


@override_settings(CONFORMIDADE_IA_FOUNDRY_RESOURCE='r', CONFORMIDADE_IA_FOUNDRY_KEY='k')
class ApiDesligamentoTests(APITestCase):
    def setUp(self):
        self.cad = Cadastro()
        self.maria = self.cad.colaborador('MARIA SOUZA', admissao=(2024, 3, 1))
        rh = User.objects.create_user('rh', password='x')
        rh.groups.add(Group.objects.create(name='RHGestor'))
        self.client.force_authenticate(rh)

    def test_so_rh(self):
        self.client.force_authenticate(User.objects.create_user('outro', password='x'))
        self.assertEqual(self.client.get('/recrutamento/desligamentos/').status_code, 403)

    def test_busca_e_cria_a_partir_do_cadastro(self):
        r = self.client.get('/recrutamento/desligamentos/colaboradores/?q=maria sou')
        self.assertEqual([c['nome'] for c in r.data], ['MARIA SOUZA'])
        self.assertEqual(r.data[0]['setor'], 'MANUTENÇÃO')
        r = self.client.post('/recrutamento/desligamentos/', {'colaborador': self.maria.id,
                                                              'data_desligamento': '2026-10-01'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data['nome'], r.data['setor'], r.data['cargo'], r.data['data_admissao'],
                          r.data['tempo_casa_meses']), ('MARIA SOUZA', 'MANUTENÇÃO', 'MECÂNICO', '2024-03-01', 31))

    def test_perguntas(self):
        r = self.client.get('/recrutamento/desligamentos/perguntas/')
        self.assertEqual(len(r.data['perguntas']['GESTOR']), 12)
        self.assertEqual(len(r.data['perguntas']['FUNCIONARIO']), 14)
        self.assertIn('sim_nao', r.data['classes'])

    def test_formulario_classifica_em_segundo_plano_e_revisao_trava_a_ia(self):
        d = Desligamento.objects.create(nome='X', data_desligamento=date(2026, 10, 1))
        with patch('recrutamento.tasks.classificar_formulario_desligamento.delay') as fila, \
                self.captureOnCommitCallbacks(execute=True):
            r = self.client.post('/recrutamento/desligamentos-formularios/', {
                'desligamento': d.id, 'formulario': 'FUNCIONARIO', 'tipo_informado': 'VOLUNTARIO',
                'respostas': {'valorizado': 'Acredita que sim', 'inventada': 'x'}, 'data_preenchimento': '2026-10-02',
            }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['respostas'], {'valorizado': 'Acredita que sim'})  # chave desconhecida some
        fila.assert_called_once()
        d.refresh_from_db()
        self.assertEqual(d.tipo, 'VOLUNTARIO')
        fid = r.data['id']

        # A IA classifica (síncrono, "Classificar agora").
        resposta = SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(
            type='text', text=json.dumps({p['chave']: 'SIM' if p['classe'] == 'sim_nao' else
                                         ('POSITIVA' if p['classe'] == 'avaliacao' else 'Salário')
                                         for p in dsl.perguntas_classificadas('FUNCIONARIO')}))])
        cliente = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: resposta))
        with patch('conformidadeLegal.ia._cliente', return_value=cliente):
            r = self.client.post(f'/recrutamento/desligamentos-formularios/{fid}/classificar/')
        self.assertEqual((r.status_code, r.data['classificacao']['valorizado']), (200, 'SIM'))

        # O RH corrige: vira revisada, valor inválido é descartado, e a IA não refaz sem forcar.
        with patch('recrutamento.tasks.classificar_formulario_desligamento.delay') as fila:
            r = self.client.patch(f'/recrutamento/desligamentos-formularios/{fid}/', {
                'formulario': 'FUNCIONARIO', 'classificacao': {'valorizado': 'PARCIAL', 'recomendaria': 'TALVEZ'},
            }, format='json')
        self.assertEqual((r.data['classificacao_revisada'], r.data['classificacao']), (True, {'valorizado': 'PARCIAL'}))
        fila.assert_not_called()
        self.assertEqual(self.client.post(f'/recrutamento/desligamentos-formularios/{fid}/classificar/').status_code, 409)
