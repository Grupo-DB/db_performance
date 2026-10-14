import shutil
import tempfile
from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from kanban.models import KanbanBoard, KanbanColumn, KanbanTask

from .models import EvidenciaAnexo, Norma, PlanoAcao, Requisito, Verificacao

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

    def test_edicao_em_lote_muda_so_os_campos_enviados(self):
        a = self._requisito(aplicabilidade='EM_ANALISE', unidade='Mina')
        b = self._requisito(aplicabilidade='EM_ANALISE', unidade='Britagem')
        r = self.client.post('/conformidadeLegal/requisitos/editar-lote/', {
            'ids': [a.id, b.id],
            'campos': {'aplicabilidade': 'NAO_APLICAVEL', 'justificativa': 'Sem caldeira.', 'norma': 999},
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        for req, unidade in ((a, 'Mina'), (b, 'Britagem')):
            req.refresh_from_db()
            # `norma` não é campo de lote e é ignorado; a unidade de cada um fica.
            self.assertEqual((req.aplicabilidade, req.justificativa, req.unidade, req.norma_id),
                             ('NAO_APLICAVEL', 'Sem caldeira.', unidade, self.norma.id))

    def test_edicao_em_lote_e_tudo_ou_nada(self):
        a = self._requisito()
        r = self.client.post('/conformidadeLegal/requisitos/editar-lote/',
                             {'ids': [a.id, 987654], 'campos': {'unidade': 'X'}}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post('/conformidadeLegal/requisitos/editar-lote/',
                             {'ids': [a.id], 'campos': {'aplicabilidade': 'TALVEZ'}}, format='json')
        self.assertEqual(r.status_code, 400)
        a.refresh_from_db()
        self.assertEqual((a.unidade, a.aplicabilidade), ('', 'APLICAVEL'))

    def test_verificacao_em_lote_compartilha_o_anexo(self):
        import os
        a, b, c = self._requisito(), self._requisito(), self._requisito()
        laudo = SimpleUploadedFile('laudo_chamine.pdf', b'%PDF-1.4 laudo', content_type='application/pdf')
        r = self.client.post('/conformidadeLegal/requisitos/verificar-lote/', {
            'ids': [a.id, b.id, c.id], 'resultado': 'ATENDIDO', 'data': '2026-10-01',
            'evidencia': 'Laudo de amostragem 2026.', 'arquivos': [laudo],
        }, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data['verificacoes'], r.data['planos']), (3, 0))
        anexos = list(EvidenciaAnexo.objects.order_by('id'))
        self.assertEqual(len(anexos), 3)
        self.assertEqual(len({x.arquivo.name for x in anexos}), 1)  # gravado uma vez só
        caminho = anexos[0].arquivo.path
        for req in (a, b, c):
            req.refresh_from_db()
            self.assertEqual((req.situacao, req.proxima_verificacao), ('ATENDIDO', date(2027, 4, 1)))

        # Apagar uma das verificações não pode levar o arquivo das outras.
        self.client.delete(f'/conformidadeLegal/verificacoes/{anexos[0].verificacao_id}/')
        self.assertTrue(os.path.exists(caminho))
        for x in anexos[1:]:
            self.client.delete(f'/conformidadeLegal/verificacoes/{x.verificacao_id}/')
        self.assertFalse(os.path.exists(caminho))

    def test_verificacao_em_lote_regras(self):
        a, b = self._requisito(), self._requisito()
        em_analise = self._requisito(aplicabilidade='EM_ANALISE')
        url = '/conformidadeLegal/requisitos/verificar-lote/'
        r = self.client.post(url, {'ids': [a.id, em_analise.id], 'resultado': 'ATENDIDO'}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertIn('Aplicável', str(r.data['ids']))
        # Não atendido sem plano é recusado; com plano, cada um ganha o seu.
        r = self.client.post(url, {'ids': [a.id, b.id], 'resultado': 'NAO_ATENDIDO'}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertIn('plano_descricao', r.data)
        r = self.client.post(url, {'ids': [a.id, b.id], 'resultado': 'NAO_ATENDIDO',
                                   'plano_descricao': 'Contratar amostragem.'}, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['planos'], 2)
        # De novo: os dois já têm plano aberto, então nada de plano duplicado.
        r = self.client.post(url, {'ids': [a.id, b.id], 'resultado': 'PARCIAL',
                                   'plano_descricao': 'Outro.'}, format='multipart')
        self.assertEqual((r.status_code, r.data['planos']), (201, 0))
        self.assertEqual(PlanoAcao.objects.count(), 2)
        self.assertFalse(Verificacao.objects.filter(requisito=em_analise).exists())

    def test_responsaveis_traz_ativos_com_o_nome_mais_humano_que_houver(self):
        User.objects.create_user('jsilva', first_name='João', last_name='Silva', password='x')
        User.objects.create_user('inativo', password='x', is_active=False)
        r = self.client.get('/conformidadeLegal/responsaveis/')
        self.assertEqual(r.status_code, 200)
        nomes = {u['login']: u['nome'] for u in r.data}
        self.assertEqual(nomes['jsilva'], 'João Silva')  # sem colaborador ligado: nome do usuário
        self.assertEqual(nomes['sgi'], 'sgi')            # sem nome nenhum: o login
        self.assertNotIn('inativo', nomes)

    def test_nome_do_colaborador_vence_o_do_usuario(self):
        from types import SimpleNamespace
        from .serializers import nome_usuario
        usuario = SimpleNamespace(username='jsilva', get_full_name=lambda: 'J Silva',
                                  colaborador=SimpleNamespace(nome='João da Silva'))
        self.assertEqual(nome_usuario(usuario), 'João da Silva')
        usuario.colaborador = SimpleNamespace(nome='  ')
        self.assertEqual(nome_usuario(usuario), 'J Silva')

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


class _SessaoDoeFalsa:
    """Imita a API do DOE-RS: busca paginada por dia + detalhe da matéria."""

    def __init__(self, materias, falhar=False):
        self.materias = materias  # {id: dict do detalhe}, com chave extra '_consulta'
        self.falhar = falhar
        self.pedidos = []

    def get(self, url, params=None, headers=None, timeout=None):
        from types import SimpleNamespace
        self.pedidos.append((url, params))
        if self.falhar:
            return SimpleNamespace(status_code=503, json=lambda: {})
        if url.endswith('/materias'):
            chave = params.get('entidade') or params.get('tipoMateria')
            itens = [{'procergs': {'id': i, 'tipo': m['tipoMateria'], 'data': '13/10/2026', 'conteudo': ''}}
                     for i, m in self.materias.items() if m['_consulta'] == chave]
            pagina = itens[(params['page'] - 1) * 10: params['page'] * 10]
            return SimpleNamespace(status_code=200, json=lambda: {'collection': pagina, 'pageSize': 10,
                                                                  'collectionSize': len(itens)})
        i = int(url.rsplit('/', 1)[1])
        return SimpleNamespace(status_code=200, json=lambda: self.materias[i])


def _materia(consulta, tipo, html, orgao='Fundação Estadual de Proteção Ambiental Henrique Luiz Roessler'):
    return {'_consulta': consulta, 'tipoMateria': tipo, 'conteudo': html, 'orgao': orgao,
            'data': '2026-10-13', 'pagina': 99}


@override_settings(MEDIA_ROOT=MEDIA_TESTE)
class MonitorDiariosTests(APITestCase):
    FEPAM = 'Fundação Estadual de Proteção Ambiental'
    SEMA = 'Secretaria do Meio Ambiente e Infraestrutura'

    def setUp(self):
        from unittest.mock import patch
        self.patch = patch
        self.user = User.objects.create_user('sgi', password='x')
        self.user.groups.add(Group.objects.create(name='ConformidadeLegal'))
        self.client.force_authenticate(self.user)
        patch('conformidadeLegal.monitor.PAUSA', 0).start()
        patch('conformidadeLegal.monitor.time.sleep').start()
        self.addCleanup(patch.stopall)

    def _sessao(self):
        return _SessaoDoeFalsa({
            1: _materia(self.FEPAM, 'Atos Administrativos', '<p><b>RESOLUÇÃO Nº 48/2026</b></p><p>Custos do licenciamento corretivo.</p>'),
            2: _materia(self.FEPAM, 'Contratos', '<p>Contrato de limpeza.</p>'),
            3: _materia(self.FEPAM, 'Atos Administrativos', '<p>SÚMULA DE CONTRATO</p><p>Partes: FEPAM e empresa X.</p>'),
            4: _materia(self.SEMA, 'Atos Administrativos', '<p>PORTARIA SEMA Nº 175</p><p>Nomeia servidor.</p>',
                        orgao=self.SEMA),
            5: _materia(self.SEMA, 'Atos Administrativos',
                        '<p>INSTRUÇÃO NORMATIVA SEMA Nº 07/2026</p><p>Áreas de lavra de calcário e emissões atmosféricas.</p>',
                        orgao=self.SEMA),
        })

    def test_coleta_filtra_por_tipo_titulo_e_palavra_e_nao_repete(self):
        from datetime import date
        from . import monitor
        from .models import PublicacaoMonitorada
        sessao = self._sessao()
        execucao = monitor.coletar_doe_rs(date(2026, 10, 13), sessao=sessao)
        self.assertTrue(execucao.ok, execucao.erro)
        # FEPAM entra inteira, menos contrato (tipo) e súmula (título); da SEMA, só o que tem palavra-chave.
        pubs = {p.id_externo: p for p in PublicacaoMonitorada.objects.all()}
        self.assertEqual(set(pubs), {'1', '5'})
        self.assertEqual(pubs['1'].titulo, 'RESOLUÇÃO Nº 48/2026')
        self.assertIn('licenciamento', pubs['1'].palavras)
        self.assertEqual(set(pubs['5'].palavras) >= {'calcário', 'lavra', 'emissões atmosféricas'}, True)
        self.assertEqual(pubs['5'].link, 'https://www.diariooficial.rs.gov.br/materia?id=5')
        # Rodar de novo no mesmo dia não duplica nada.
        self.assertEqual(monitor.coletar_doe_rs(date(2026, 10, 13), sessao=self._sessao()).novas, 0)
        self.assertEqual(PublicacaoMonitorada.objects.count(), 2)

    def test_fonte_fora_do_ar_vira_execucao_com_erro_e_aparece_na_situacao(self):
        from datetime import date
        from . import monitor
        execucao = monitor.coletar_doe_rs(date(2026, 10, 13), sessao=_SessaoDoeFalsa({}, falhar=True))
        self.assertFalse(execucao.ok)
        self.assertIn('HTTP 503', execucao.erro)
        r = self.client.get('/conformidadeLegal/novidades/situacao/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['fontes'][0]['ok'], r.data['fontes'][0]['falhas_seguidas']), (False, 1))

    def test_dias_a_coletar_recupera_o_que_ficou_para_tras(self):
        from datetime import date
        from . import monitor
        from .models import ExecucaoMonitor
        hoje = date(2026, 10, 13)
        self.assertEqual(monitor.dias_a_coletar('DOE_RS', hoje), [hoje])
        ExecucaoMonitor.objects.create(fonte='DOE_RS', data_referencia=date(2026, 10, 9), ok=True)
        ExecucaoMonitor.objects.create(fonte='DOE_RS', data_referencia=date(2026, 10, 10), ok=False)
        self.assertEqual(monitor.dias_a_coletar('DOE_RS', hoje),
                         [date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12), hoje])
        ExecucaoMonitor.objects.create(fonte='DOE_RS', data_referencia=date(2026, 8, 1), ok=True)
        ExecucaoMonitor.objects.filter(data_referencia=date(2026, 10, 9)).delete()
        self.assertEqual(len(monitor.dias_a_coletar('DOE_RS', hoje)), 8)  # no máximo uma semana para trás

    def test_cadastrar_como_norma_preenche_e_anexa_pdf(self):
        from datetime import date
        from .models import PublicacaoMonitorada
        pub = PublicacaoMonitorada.objects.create(
            fonte='DOE_RS', id_externo='1491479', data_publicacao=date(2026, 10, 13),
            orgao='Fundação Estadual de Proteção Ambiental Henrique Luiz Roessler', tipo='Atos Administrativos',
            titulo='PORTARIA FEPAM Nº 634/2026', texto='PORTARIA FEPAM Nº 634/2026\nDispõe sobre o licenciamento.',
            link='https://www.diariooficial.rs.gov.br/materia?id=1491479', pagina=99, tema_sugerido='AMBIENTAL')
        r = self.client.post(f'/conformidadeLegal/novidades/{pub.id}/cadastrar-norma/')
        self.assertEqual(r.status_code, 201, r.data)
        norma = Norma.objects.get(pk=r.data['norma']['id'])
        self.assertEqual((norma.tipo, norma.orgao, norma.numero, norma.ano, norma.esfera),
                         ('PORTARIA', 'FEPAM', '634', 2026, 'ESTADUAL'))
        self.assertEqual(norma.identificacao, 'Portaria FEPAM nº 634/2026')
        with norma.arquivo.open('rb') as f:
            self.assertTrue(f.read(5).startswith(b'%PDF'))
        pub.refresh_from_db()
        self.assertEqual((pub.status, pub.norma_id, pub.avaliado_por_id), ('CADASTRADA', norma.id, self.user.id))
        self.assertEqual(self.client.post(f'/conformidadeLegal/novidades/{pub.id}/cadastrar-norma/').status_code, 400)
        self.assertEqual(self.client.post(f'/conformidadeLegal/novidades/{pub.id}/reabrir/').status_code, 400)

    def test_descartar_e_reabrir(self):
        from datetime import date
        from .models import PublicacaoMonitorada
        pub = PublicacaoMonitorada.objects.create(fonte='DOE_RS', id_externo='9', data_publicacao=date(2026, 10, 13))
        r = self.client.post(f'/conformidadeLegal/novidades/{pub.id}/descartar/', {'motivo': 'Ato interno.'}, format='json')
        self.assertEqual((r.status_code, r.data['status'], r.data['motivo_descarte']), (200, 'DESCARTADA', 'Ato interno.'))
        self.assertEqual(self.client.get('/conformidadeLegal/novidades/?status=NOVA').data, [])
        r = self.client.post(f'/conformidadeLegal/novidades/{pub.id}/reabrir/')
        self.assertEqual((r.data['status'], r.data['avaliado_por_nome']), ('NOVA', None))

    def test_triagem_grava_relevancia_e_motivo(self):
        import json
        from datetime import date
        from . import tasks
        from .models import PublicacaoMonitorada
        pub = PublicacaoMonitorada.objects.create(fonte='DOE_RS', id_externo='5', data_publicacao=date(2026, 10, 13),
                                                  titulo='INSTRUÇÃO NORMATIVA SEMA Nº 07/2026', texto='lavra de calcário')
        resposta = _RespostaFalsa(json.dumps({'relevancia': 'ALTA', 'motivo': 'Muda o licenciamento de lavra.', 'tema': 'MINERARIO'}))
        cliente = type('C', (), {'messages': type('M', (), {'create': lambda _s, **kw: resposta})()})()
        with override_settings(CONFORMIDADE_IA_FOUNDRY_RESOURCE='r', CONFORMIDADE_IA_FOUNDRY_KEY='k'), \
                self.patch('conformidadeLegal.ia._cliente', return_value=cliente):
            tasks.triar_publicacoes()
        pub.refresh_from_db()
        self.assertEqual((pub.relevancia, pub.tema_sugerido, pub.analise), ('ALTA', 'MINERARIO', 'Muda o licenciamento de lavra.'))
        self.assertIsNotNone(pub.analisada_em)


class PalavrasChaveTests(SimpleTestCase):
    def test_casa_sem_acento_e_como_palavra_inteira(self):
        from .monitor import palavras_encontradas
        self.assertEqual(palavras_encontradas('Extração de CALCARIO e emissão atmosférica'), ['calcário', 'emissões atmosféricas'])
        # "cal" solto e "fiscal" não disparam; "brita" sim.
        self.assertEqual(palavras_encontradas('Auditoria fiscal da Cal. Silva'), [])
        self.assertIn('britagem', palavras_encontradas('usina de brita'))
