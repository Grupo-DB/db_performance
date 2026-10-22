"""venv/bin/python manage.py test aprendizes.tests uniformes.tests --settings=db_performance.test_settings"""
from datetime import date, datetime

from django.contrib.auth.models import Group, User
from django.utils import timezone
from rest_framework.test import APITestCase

from avaliacoes.management.models import Ambiente, Area, Cargo, Colaborador, Empresa, Filial, Setor

from .models import Acompanhamento, Etapa
from .regras import checklist_do_texto, situacao_da_planilha, tipo_da_planilha


def criar_colaborador(nome, admissao=None, cargo_nome='Operador', genero='M'):
    empresa = Empresa.objects.create(nome='DB', cnpj='1', endereco='r', cidade='c', estado='RS', codigo='01')
    filial = Filial.objects.create(empresa=empresa, nome='Matriz', cnpj='1', endereco='r', cidade='c', estado='RS', codigo='01')
    area = Area.objects.create(empresa=empresa, filial=filial, nome='Op')
    setor = Setor.objects.create(empresa=empresa, filial=filial, area=area, nome='Expedição')
    ambiente = Ambiente.objects.create(empresa=empresa, filial=filial, area=area, setor=setor, nome='Pátio')
    cargo = Cargo.objects.create(empresa=empresa, filial=filial, area=area, setor=setor, ambiente=ambiente, nome=cargo_nome)
    return Colaborador.objects.create(
        nome=nome, empresa=empresa, filial=filial, setor=setor, area=area, cargo=cargo, ambiente=ambiente,
        situacao=True, genero=genero,
        data_admissao=timezone.make_aware(datetime.combine(admissao, datetime.min.time())) if admissao else None,
    )


class AcompanhamentoTests(APITestCase):
    def setUp(self):
        u = User.objects.create_user('rh', password='x')
        u.groups.add(Group.objects.create(name='RHGestor'))
        self.client.force_authenticate(u)

    def test_leitura_da_planilha(self):
        self.assertEqual(tipo_da_planilha('1º VENCIMENTO'), Etapa.PRIMEIRO_VENCIMENTO)
        self.assertEqual(tipo_da_planilha('1° vencimento'), Etapa.PRIMEIRO_VENCIMENTO)
        self.assertEqual(tipo_da_planilha('PRORROGAÇÃO'), Etapa.PRORROGACAO)
        self.assertEqual(situacao_da_planilha('CONCLUÍDO'), (Etapa.CONCLUIDO, ''))
        self.assertEqual(situacao_da_planilha('PENDENTE BRINDE'), (Etapa.PENDENTE, 'Brinde'))
        self.assertEqual(situacao_da_planilha('PEDIDO DE DEMISSÃO')[0], Etapa.DESLIGADO)
        self.assertEqual(checklist_do_texto('Feedback ok - Falta brinde'),
                         {'feedback_dado': True, 'brinde_entregue': False})
        self.assertEqual(checklist_do_texto('CAMISETA OK'), {'camiseta_entregue': True})
        self.assertEqual(checklist_do_texto('Passar feedback'), {'feedback_dado': False})

    def test_novo_pelo_colaborador_cria_as_duas_etapas(self):
        c = criar_colaborador('Ana Lima', admissao=date(2026, 9, 1))
        r = self.client.post('/aprendizes/acompanhamentos/', {'colaborador': c.id, 'nome': c.nome}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        a = Acompanhamento.objects.get()
        self.assertEqual((a.setor, a.cargo, a.data_admissao), ('Expedição', 'Operador', date(2026, 9, 1)))
        venc = {e.tipo: e.vencimento for e in a.etapas.all()}
        self.assertEqual(venc, {Etapa.PRIMEIRO_VENCIMENTO: date(2026, 9, 30), Etapa.PRORROGACAO: date(2026, 11, 29)})
        r = self.client.get('/aprendizes/acompanhamentos/candidatos/?q=ana')
        self.assertTrue(r.data[0]['ja_acompanhado'])

    def test_concluir_efetivacao_efetiva_e_registra_quem(self):
        a = Acompanhamento.objects.create(nome='B')
        e = Etapa.objects.create(acompanhamento=a, tipo=Etapa.EFETIVACAO, vencimento=date(2026, 10, 1))
        r = self.client.patch(f'/aprendizes/etapas/{e.id}/', {'situacao': 'CONCLUIDO', 'feedback_dado': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        e.refresh_from_db(); a.refresh_from_db()
        self.assertIsNotNone(e.concluido_em)
        self.assertEqual(a.situacao, Acompanhamento.EFETIVADO)
        self.client.patch(f'/aprendizes/etapas/{e.id}/', {'situacao': 'DISPENSADO'}, format='json')
        a.refresh_from_db()
        self.assertEqual(a.situacao, Acompanhamento.DESLIGADO)

    def test_lista_do_mes_e_atrasadas(self):
        a = Acompanhamento.objects.create(nome='C')
        Etapa.objects.create(acompanhamento=a, tipo=Etapa.PRIMEIRO_VENCIMENTO, vencimento=date(2025, 3, 5))
        Etapa.objects.create(acompanhamento=a, tipo=Etapa.PRORROGACAO, vencimento=date(2025, 5, 4), situacao=Etapa.CONCLUIDO)
        self.assertEqual(len(self.client.get('/aprendizes/etapas/?mes=2025-03').data), 1)
        self.assertEqual(len(self.client.get('/aprendizes/etapas/?atrasadas=1').data), 1)

    def test_importar_agrupa_pessoa_e_nao_duplica(self):
        criar_colaborador('Éder Silva da Silva', admissao=date(2025, 2, 4))
        linhas = [
            {'aba': '032025', 'nome': 'EDER SILVA DA SILVA', 'tipo': '1º VENCIMENTO', 'vencimento': '2025-03-05', 'situacao': 'FEITO'},
            {'aba': '052025', 'nome': 'EDER SILVA DA SILVA ', 'tipo': 'PRORROGAÇÃO', 'vencimento': '2025-05-04',
             'situacao': 'FEITO', 'observacao': 'Feedback ok - Falta brinde'},
            {'aba': '082025', 'nome': 'ALICE COLARES', 'tipo': 'PRORROGAÇÃO', 'vencimento': 'PEDIDO DE DEMISSÃO'},
            {'aba': '092025', 'nome': '', 'tipo': 'PRORROGAÇÃO', 'vencimento': '2025-09-01'},
        ]
        r = self.client.post('/aprendizes/acompanhamentos/importar/', {'linhas': linhas}, format='json')
        self.assertEqual((r.data['pessoas_criadas'], r.data['etapas_criadas'], len(r.data['ignoradas'])), (2, 3, 1))
        eder = Acompanhamento.objects.get(nome='Éder Silva da Silva')
        self.assertIsNotNone(eder.colaborador_id)
        pro = eder.etapas.get(tipo=Etapa.PRORROGACAO)
        self.assertTrue(pro.feedback_dado)
        self.assertFalse(pro.brinde_entregue)
        self.assertEqual(eder.situacao, Acompanhamento.EFETIVADO)  # prorrogação concluída
        alice = Acompanhamento.objects.get(nome='ALICE COLARES')
        self.assertEqual(alice.situacao, Acompanhamento.DESLIGADO)
        self.assertEqual(alice.etapas.get().vencimento, date(2025, 8, 1))

        r = self.client.post('/aprendizes/acompanhamentos/importar/', {'linhas': linhas}, format='json')
        self.assertEqual((r.data['pessoas_criadas'], r.data['etapas_criadas']), (0, 0))
        self.assertEqual(Etapa.objects.count(), 3)

    def test_sem_grupo_nao_acessa(self):
        self.client.force_authenticate(User.objects.create_user('x', password='x'))
        self.assertEqual(self.client.get('/aprendizes/acompanhamentos/').status_code, 403)


class ComandoImportarTests(APITestCase):
    """O comando lê o xlsx no servidor com as mesmas regras da tela."""

    def test_le_abas_com_colunas_diferentes(self):
        import os
        import tempfile

        import openpyxl
        from django.core.management import call_command

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '032025'
        ws.append([None, 'NOME ', 'TIPO', 'VENCIMENTO ', 'SITUAÇÃO', 'PLANO DE SAÚDE'])
        ws.append([None, 'EDER SILVA', '1º VENCIMENTO', datetime(2025, 3, 5), 'FEITO', 'INFORMADO'])
        ws2 = wb.create_sheet('092026')
        ws2.append([None, 3, 'TIPO', 'VENCIMENTO ', 'SITUAÇÃO', 'PENDÊNCIA'])  # cabeçalho sem "NOME"
        ws2.append([None, 'RAÍ DE BARCELLOS', 'EFETIVAÇÃO', datetime(2026, 9, 5), 'PENDENTE', 'MANDAR BRINDE'])
        caminho = os.path.join(tempfile.mkdtemp(), 'exp.xlsx')
        wb.save(caminho)

        call_command('importar_experiencia', caminho, '--simular', stdout=open(os.devnull, 'w'))
        self.assertEqual(Etapa.objects.count(), 0)
        call_command('importar_experiencia', caminho, stdout=open(os.devnull, 'w'))
        eder = Etapa.objects.get(acompanhamento__nome='EDER SILVA')
        self.assertTrue(eder.plano_saude_informado)
        rai = Etapa.objects.get(acompanhamento__nome='RAÍ DE BARCELLOS')
        self.assertEqual((rai.tipo, rai.situacao), (Etapa.EFETIVACAO, Etapa.PENDENTE))
        self.assertFalse(rai.brinde_entregue)


class JovemAprendizTests(APITestCase):
    """Programa Jovem Aprendiz (22/10/2026): avaliação do instrutor, autoavaliação e comparativo."""

    def setUp(self):
        u = User.objects.create_user('rh', password='x')
        u.groups.add(Group.objects.create(name='RHGestor'))
        self.client.force_authenticate(u)
        self.url = '/aprendizes/jovem-aprendiz/'

    def _notas(self, base):
        from .jovem_aprendiz import CHAVES
        return {c: base for c in CHAVES}

    def test_formularios_tem_o_texto_dos_documentos(self):
        f = self.client.get(self.url + 'formularios/').data
        self.assertEqual(len(f['INSTRUTOR']['competencias']), 10)
        self.assertEqual(f['AUTO']['competencias'][1]['nome'], 'Escuta')
        self.assertEqual(f['INSTRUTOR']['competencias'][1]['nome'], 'Escuta e receptividade')
        self.assertEqual(f['INSTRUTOR']['escala'][3]['rotulo'], 'Supera o esperado')
        self.assertEqual(len(f['AUTO']['perguntas']), 3)
        self.assertEqual(len(f['INSTRUTOR']['evolucoes']), 4)

    def test_exige_todas_as_notas_de_1_a_4(self):
        notas = self._notas(3)
        notas.pop('etica')
        r = self.client.post(self.url, {'tipo': 'INSTRUTOR', 'nome': 'Ana', 'data': '2026-10-22', 'notas': notas}, format='json')
        self.assertEqual(r.status_code, 400)
        notas = self._notas(5)
        r = self.client.post(self.url, {'tipo': 'INSTRUTOR', 'nome': 'Ana', 'data': '2026-10-22', 'notas': notas}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_salva_e_compara_instrutor_com_autoavaliacao(self):
        r = self.client.post(self.url, {'tipo': 'INSTRUTOR', 'nome': 'Ana Souza', 'setor': 'Laboratório', 'data': '2026-10-22',
                                        'notas': {**self._notas(3), 'pontualidade': 2}, 'evolucao': 'MODERADA',
                                        'competencia_prioritaria': 'pontualidade', 'respostas': {'ponto_forte': 'Comunicação', 'xx': 'some'},
                                        'avaliador': 'Instrutor Carlos'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['respostas'], {'ponto_forte': 'Comunicação'})   # pergunta de fora não grava
        self.assertEqual(r.data['media'], 2.9)
        r = self.client.post(self.url, {'tipo': 'AUTO', 'nome': 'Ana Souza', 'data': '2026-10-22', 'notas': {**self._notas(3), 'pontualidade': 4},
                                        'evolucao': 'MODERADA', 'respostas': {'quero_melhorar': 'Chegar no horário'}}, format='json')
        self.assertEqual((r.status_code, r.data['evolucao']), (201, ''))         # autoavaliação não tem evolução
        c = self.client.get(self.url + 'comparativo/?nome=ana souza').data
        linha = next(l for l in c['linhas'] if l['chave'] == 'pontualidade')
        self.assertEqual((linha['instrutor'], linha['auto'], linha['diferenca']), (2, 4, 2))
        self.assertEqual(c['atencao'], ['Pontualidade e assiduidade'])
        self.assertEqual(len(self.client.get(self.url + '?tipo=AUTO').data), 1)
        resumo = self.client.get(self.url + 'resumo/').data
        self.assertEqual(resumo['INSTRUTOR']['medias']['pontualidade'], 2)

    def test_so_o_rh(self):
        self.client.force_authenticate(User.objects.create_user('outro', password='x'))
        self.assertEqual(self.client.get(self.url).status_code, 403)


class AutoavaliacaoPeloCelularTests(APITestCase):
    """O jovem responde a autoavaliação pelo link do convite, sem login (22/10/2026)."""

    def setUp(self):
        self.rh = User.objects.create_user('rh', password='x')
        self.rh.groups.add(Group.objects.create(name='RHGestor'))

    def _convite(self):
        self.client.force_authenticate(self.rh)
        r = self.client.post('/aprendizes/jovem-aprendiz/convites/', {'nome': 'Carlos Eduardo', 'setor': 'Manutenção', 'telefone': '(55) 99999-1234'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['telefone'], '55999991234')
        self.client.force_authenticate(None)
        return r.data

    def _respostas(self):
        from .jovem_aprendiz import CHAVES
        return {'notas': {c: 3 for c in CHAVES}, 'respostas': {'quero_melhorar': 'Chegar no horário'}}

    def test_jovem_responde_sem_login_uma_vez_so(self):
        c = self._convite()
        url = f"/aprendizes/publico/autoavaliacao/{c['token']}/"
        g = self.client.get(url)
        self.assertEqual((g.status_code, g.data['fechado'], g.data['nome']), (200, False, 'Carlos Eduardo'))
        self.assertEqual(len(g.data['formulario']['competencias']), 10)
        incompleto = self._respostas()
        incompleto['notas'].pop('etica')
        self.assertEqual(self.client.post(url, incompleto, format='json').status_code, 400)
        r = self.client.post(url, self._respostas(), format='json')
        self.assertEqual(r.status_code, 201, r.data)
        from .models import AvaliacaoJovemAprendiz, ConviteAutoavaliacao
        av = AvaliacaoJovemAprendiz.objects.get()
        self.assertEqual((av.tipo, av.nome, av.setor), ('AUTO', 'Carlos Eduardo', 'Manutenção'))
        self.assertEqual(ConviteAutoavaliacao.objects.get().avaliacao_id, av.id)
        self.assertEqual(self.client.post(url, self._respostas(), format='json').status_code, 400)   # segunda vez não
        self.assertEqual(self.client.get(url).data['situacao'], 'RESPONDIDO')

    def test_cancelado_e_vencido_fecham_e_token_errado_some(self):
        from django.utils import timezone as tz
        from datetime import timedelta
        from .models import ConviteAutoavaliacao
        c = self._convite()
        self.client.force_authenticate(self.rh)
        self.client.post(f"/aprendizes/jovem-aprendiz/convites/{c['id']}/cancelar/")
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f"/aprendizes/publico/autoavaliacao/{c['token']}/").data['situacao'], 'CANCELADO')
        c2 = self._convite()
        ConviteAutoavaliacao.objects.filter(pk=c2['id']).update(expira_em=tz.now() - timedelta(minutes=1))
        self.assertEqual(self.client.post(f"/aprendizes/publico/autoavaliacao/{c2['token']}/", self._respostas(), format='json').status_code, 400)
        self.assertEqual(self.client.get('/aprendizes/publico/autoavaliacao/naoexiste/').status_code, 404)

    def test_convites_so_o_rh(self):
        self.assertEqual(self.client.get('/aprendizes/jovem-aprendiz/convites/').status_code, 401)
