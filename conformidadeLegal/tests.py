import shutil
import tempfile
from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from kanban.models import KanbanBoard, KanbanColumn, KanbanTask

from .models import Norma, PlanoAcao, Requisito, Verificacao

# Anexos dos testes vão para uma pasta descartável, não para o media/ do projeto.
MEDIA_TESTE = tempfile.mkdtemp(prefix='conformidade-testes-')


def tearDownModule():
    shutil.rmtree(MEDIA_TESTE, ignore_errors=True)


@override_settings(MEDIA_ROOT=MEDIA_TESTE)
class ConformidadeLegalTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('sgi', password='x')
        self.user.groups.add(Group.objects.create(name='ConformidadeLegal'))
        self.client.force_authenticate(self.user)
        r = self.client.post('/conformidadeLegal/normas/', {
            'tipo': 'RESOLUCAO', 'orgao': 'CONAMA', 'numero': '430', 'ano': 2011,
            'esfera': 'FEDERAL', 'tema': 'AMBIENTAL', 'ementa': 'Condições e padrões de lançamento de efluentes.',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['identificacao'], 'Resolução CONAMA nº 430/2011')
        self.norma = Norma.objects.get(pk=r.data['id'])

    def _requisito(self, **extra):
        r = self.client.post('/conformidadeLegal/requisitos/', {
            'norma': self.norma.id, 'referencia': 'Art. 16', 'descricao': 'Monitorar o efluente.',
            'tema': 'AMBIENTAL', 'aplicabilidade': 'APLICAVEL', 'periodicidade_meses': 6, **extra,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return Requisito.objects.get(pk=r.data['id'])

    def test_sem_grupo_nao_entra(self):
        self.client.force_authenticate(User.objects.create_user('outro', password='x'))
        self.assertEqual(self.client.get('/conformidadeLegal/requisitos/').status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/conformidadeLegal/normas/').status_code, 401)

    def test_verificacao_atualiza_situacao_e_proxima_data(self):
        req = self._requisito()
        self.assertEqual(req.situacao, 'NAO_AVALIADO')
        arquivo = SimpleUploadedFile('laudo.pdf', b'%PDF-1.4 teste', content_type='application/pdf')
        r = self.client.post(f'/conformidadeLegal/requisitos/{req.id}/verificar/', {
            'resultado': 'ATENDIDO', 'data': '2026-10-01', 'evidencia': 'Laudo do laboratório.',
            'arquivos': [arquivo],
        }, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data['verificacao']['anexos']), 1)
        req.refresh_from_db()
        self.assertEqual((req.situacao, req.ultima_verificacao, req.proxima_verificacao),
                         ('ATENDIDO', date(2026, 10, 1), date(2027, 4, 1)))

        # Apagar a VCL devolve o requisito ao estado anterior.
        vcl = Verificacao.objects.get(requisito=req)
        self.assertEqual(self.client.delete(f'/conformidadeLegal/verificacoes/{vcl.id}/').status_code, 204)
        req.refresh_from_db()
        self.assertEqual((req.situacao, req.proxima_verificacao), ('NAO_AVALIADO', None))

    def test_nao_atendido_exige_plano_e_gera_tarefa_no_kanban(self):
        req = self._requisito()
        url = f'/conformidadeLegal/requisitos/{req.id}/verificar/'
        r = self.client.post(url, {'resultado': 'NAO_ATENDIDO'}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertIn('plano_descricao', r.data)

        quadro = KanbanBoard.objects.create(nome='SGI', criado_por=self.user)
        coluna = KanbanColumn.objects.create(quadro=quadro, titulo='A fazer')
        prazo = (date.today() + timedelta(days=20)).isoformat()
        r = self.client.post(url, {
            'resultado': 'NAO_ATENDIDO', 'plano_descricao': 'Instalar caixa separadora.',
            'plano_prazo': prazo, 'coluna_id': coluna.id,
        }, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        tarefa = KanbanTask.objects.get()
        self.assertEqual((tarefa.coluna_id, tarefa.prioridade, str(tarefa.prazo)), (coluna.id, 'alta', prazo))
        self.assertEqual(r.data['plano']['tarefa'], tarefa.id)
        self.assertEqual(r.data['requisito']['planos_abertos'], 1)

        # Concluir a tarefa no Kanban conclui o plano.
        from django.utils import timezone
        tarefa.concluido_em = timezone.now()
        tarefa.save()
        self.assertEqual(PlanoAcao.objects.get().status, 'CONCLUIDO')
        r = self.client.get('/conformidadeLegal/requisitos/resumo/')
        self.assertEqual(r.data['planos_abertos'], 0)

    def test_quadro_alheio_e_recusado(self):
        req = self._requisito()
        dono = User.objects.create_user('dono', password='x')
        coluna = KanbanColumn.objects.create(quadro=KanbanBoard.objects.create(nome='X', criado_por=dono), titulo='A')
        plano = PlanoAcao.objects.create(requisito=req, descricao='Algo')
        r = self.client.post(f'/conformidadeLegal/planos-acao/{plano.id}/gerar-tarefa/', {'coluna_id': coluna.id},
                             format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(KanbanTask.objects.exists())

    def test_resumo_conta_so_aplicaveis_e_validade_de_licenca(self):
        a = self._requisito()
        self._requisito(aplicabilidade='EM_ANALISE')
        self._requisito(aplicabilidade='NAO_APLICAVEL')
        self.client.post(f'/conformidadeLegal/requisitos/{a.id}/verificar/', {'resultado': 'PARCIAL',
                         'plano_descricao': 'Completar.'}, format='multipart')
        Norma.objects.create(tipo='LICENCA', orgao='FEPAM', numero='123', ementa='LO da mina',
                             validade=date.today() + timedelta(days=60))
        r = self.client.get('/conformidadeLegal/requisitos/resumo/')
        self.assertEqual((r.data['aplicaveis'], r.data['em_analise'], r.data['nao_aplicaveis']), (1, 1, 1))
        self.assertEqual(r.data['por_situacao']['PARCIAL'], 1)
        self.assertEqual(r.data['indice_conformidade'], 50.0)
        self.assertEqual([v['dias'] for v in r.data['validades']], [60])

    def test_norma_com_requisito_nao_se_apaga(self):
        self._requisito()
        r = self.client.delete(f'/conformidadeLegal/normas/{self.norma.id}/')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Norma.objects.filter(pk=self.norma.id).exists())

    def test_criar_lote(self):
        r = self.client.post('/conformidadeLegal/requisitos/criar-lote/', {'norma': self.norma.id, 'itens': [
            {'descricao': 'A', 'referencia': 'Art. 1', 'origem': 'IA', 'trecho_fonte': 'texto', 'prazo_legal': '2027-03-31'},
            {'descricao': 'B'},
        ]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Requisito.objects.filter(norma=self.norma).count(), 2)
        self.assertEqual(str(Requisito.objects.get(descricao='A').proxima_verificacao), '2027-03-31')


class _RespostaFalsa:
    def __init__(self, texto, stop_reason='end_turn'):
        bloco = type('B', (), {'type': 'text', 'text': texto})()
        self.content = [bloco]
        self.stop_reason = stop_reason
        self.usage = type('U', (), {'input_tokens': 1200, 'output_tokens': 300})()


class _ClienteFalso:
    """Imita AnthropicFoundry.messages.stream(...) e guarda os argumentos."""

    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = []
        self.messages = self

    def stream(self, **kwargs):
        self.chamadas.append(kwargs)
        resposta = self.resposta

        class _Ctx:
            def __enter__(self_inner):
                return type('S', (), {'get_final_message': lambda _s: resposta})()

            def __exit__(self_inner, *a):
                return False
        return _Ctx()


@override_settings(MEDIA_ROOT=MEDIA_TESTE)
class ExtracaoIATests(APITestCase):
    def setUp(self):
        from unittest.mock import patch
        self.patch = patch
        self.user = User.objects.create_user('sgi', password='x')
        self.user.groups.add(Group.objects.create(name='ConformidadeLegal'))
        self.client.force_authenticate(self.user)
        self.norma = Norma.objects.create(tipo='LICENCA', orgao='FEPAM', numero='1', ementa='LO',
                                          arquivo=SimpleUploadedFile('lo.pdf', b'%PDF-1.4 conteudo'))
        self.url = f'/conformidadeLegal/normas/{self.norma.id}/extracao-ia/'

    def _rodar(self, cliente, dados=None):
        from django.test import override_settings
        from . import views
        with override_settings(CONFORMIDADE_IA_FOUNDRY_RESOURCE='grupodb', CONFORMIDADE_IA_FOUNDRY_KEY='k'), \
                self.patch('conformidadeLegal.ia._cliente', return_value=cliente), \
                self.patch.object(views.extrair_requisitos, 'delay', side_effect=lambda i: views.extrair_requisitos(i)), \
                self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url, dados or {}, format='json')
        self.assertEqual(r.status_code, 202, r.data)
        return self.client.get(self.url).data

    # Configuração vazia forçada: o .env de quem roda o teste pode ter a chave de verdade.
    @override_settings(CONFORMIDADE_IA_FOUNDRY_RESOURCE='', CONFORMIDADE_IA_FOUNDRY_KEY='')
    def test_sem_configuracao_responde_503(self):
        r = self.client.post(self.url)
        self.assertEqual(r.status_code, 503)
        self.assertFalse(self.client.get(self.url).data['configurada'])

    def test_extracao_grava_sugestoes_normalizadas(self):
        import json
        texto = json.dumps({'resumo': 'LO com 2 condicionantes.', 'itens': [
            {'referencia': 'Condicionante 7', 'descricao': 'Enviar relatório anual', 'tema': 'AMBIENTAL',
             'periodicidade_meses': 12, 'prazo_legal': '2027-03-31', 'trecho': '7. ...até 31 de março', 'pagina': 4,
             'observacao': ''},
            {'referencia': 'x', 'descricao': 'Algo', 'tema': 'INVENTADO', 'periodicidade_meses': 5,
             'prazo_legal': '31/03', 'trecho': 't', 'pagina': 0, 'observacao': ''},
            {'referencia': '', 'descricao': '  ', 'tema': 'SST', 'periodicidade_meses': 0, 'prazo_legal': '',
             'trecho': '', 'pagina': 1, 'observacao': ''},
        ]})
        cliente = _ClienteFalso(_RespostaFalsa(texto))
        dados = self._rodar(cliente)['extracao']
        self.assertEqual(dados['status'], 'CONCLUIDA')
        self.assertEqual(len(dados['itens']), 2)  # o de descrição vazia some
        self.assertEqual(dados['itens'][0]['prazo_legal'], '2027-03-31')
        self.assertEqual((dados['itens'][1]['tema'], dados['itens'][1]['periodicidade_meses'],
                          dados['itens'][1]['prazo_legal'], dados['itens'][1]['pagina']), ('OUTRO', 12, None, None))
        # O PDF vai como documento e a saída é forçada ao esquema.
        chamada = cliente.chamadas[0]
        self.assertEqual(chamada['messages'][0]['content'][0]['type'], 'document')
        self.assertEqual(chamada['output_config']['format']['type'], 'json_schema')

    def test_paginas_recortam_o_pdf_e_voltam_na_numeracao_original(self):
        import base64
        import json
        self.norma.arquivo = SimpleUploadedFile('dt.pdf', _pdf_com_paginas(6))
        self.norma.save()
        # A IA cita a posição no RECORTE: 2ª página do recorte = 4ª do original; 9 não existe.
        texto = json.dumps({'resumo': 'r', 'itens': [
            {'referencia': '4.8', 'descricao': 'Medir', 'tema': 'AMBIENTAL', 'periodicidade_meses': 12,
             'prazo_legal': '', 'trecho': 't', 'pagina': 2, 'observacao': ''},
            {'referencia': '4.9', 'descricao': 'Relatar', 'tema': 'AMBIENTAL', 'periodicidade_meses': 12,
             'prazo_legal': '', 'trecho': 't', 'pagina': 9, 'observacao': ''},
        ]})
        cliente = _ClienteFalso(_RespostaFalsa(texto))
        resposta = self._rodar(cliente, {'paginas': '5, 2;4 - 4'})
        dados = resposta['extracao']
        self.assertEqual(resposta['total_paginas'], 6)
        self.assertEqual(dados['paginas'], '2, 4-5')
        self.assertEqual([i['pagina'] for i in dados['itens']], [4, None])
        # Foi só o recorte, e a instrução avisa que é recorte.
        conteudo = cliente.chamadas[0]['messages'][0]['content']
        enviado = base64.b64decode(conteudo[0]['source']['data'])
        from . import ia
        self.assertEqual(ia.contar_paginas(enviado), 3)
        self.assertIn('RECORTE', conteudo[1]['text'])

    def test_paginas_fora_do_documento_voltam_400(self):
        self.norma.arquivo = SimpleUploadedFile('dt.pdf', _pdf_com_paginas(3))
        self.norma.save()
        with override_settings(CONFORMIDADE_IA_FOUNDRY_RESOURCE='r', CONFORMIDADE_IA_FOUNDRY_KEY='k'):
            r = self.client.post(self.url, {'paginas': '2-7'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('3 página', str(r.data['paginas']))
        self.assertFalse(self.norma.extracoes.exists())

    def test_recusa_vira_erro_legivel(self):
        dados = self._rodar(_ClienteFalso(_RespostaFalsa('', stop_reason='refusal')))['extracao']
        self.assertEqual(dados['status'], 'ERRO')
        self.assertIn('recusou', dados['erro'])

    def test_sem_pdf_e_recusado(self):
        from django.test import override_settings
        self.norma.arquivo = None
        self.norma.save()
        with override_settings(CONFORMIDADE_IA_FOUNDRY_RESOURCE='r', CONFORMIDADE_IA_FOUNDRY_KEY='k'):
            r = self.client.post(self.url)
        self.assertEqual(r.status_code, 400)


def _pdf_com_paginas(n: int) -> bytes:
    """PDF de verdade com n páginas, cada uma escrita "Página k"."""
    import io
    from reportlab.pdfgen import canvas
    saida = io.BytesIO()
    c = canvas.Canvas(saida)
    for k in range(1, n + 1):
        c.drawString(100, 750, f'Pagina {k}')
        c.showPage()
    c.save()
    return saida.getvalue()


class PaginasTests(SimpleTestCase):
    def test_interpreta_intervalos_e_listas(self):
        from .ia import interpretar_paginas
        self.assertEqual(interpretar_paginas('20-21, 24-26', 39), [20, 21, 24, 25, 26])
        self.assertEqual(interpretar_paginas('3; 1 – 2, 3', 5), [1, 2, 3])
        self.assertEqual(interpretar_paginas('  ', 5), [])

    def test_recusa_o_que_nao_da_para_usar(self):
        from .ia import PaginasInvalidas, interpretar_paginas
        for texto in ('a-3', '5-2', '0', '4-6', '2,,x'):
            with self.subTest(texto=texto), self.assertRaises(PaginasInvalidas):
                interpretar_paginas(texto, 5)

    def test_descreve_de_forma_compacta(self):
        from .ia import descrever_paginas
        self.assertEqual(descrever_paginas([1, 2, 3, 7, 9, 10]), '1-3, 7, 9-10')

    def test_recorte_mantem_as_paginas_pedidas_na_ordem(self):
        import io
        from pypdf import PdfReader
        from .ia import recortar_pdf
        recorte = PdfReader(io.BytesIO(recortar_pdf(_pdf_com_paginas(5), [2, 4])))
        self.assertEqual([p.extract_text().strip() for p in recorte.pages], ['Pagina 2', 'Pagina 4'])
