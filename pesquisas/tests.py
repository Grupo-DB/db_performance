"""
Testes do fluxo inteiro: criar a pesquisa, responder pelo link público e ler as
estatísticas. O que se quer provar aqui é que o anônimo consegue responder sem
token, que o obrigatório é cobrado no servidor e que a média/distribuição batem.
"""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Pergunta, Pesquisa, Resposta


def criar_pesquisa(**extra):
    dados = dict(
        titulo='Pesquisa de satisfação de colaboradores 2025',
        codigo_formulario='F-099',
        status=Pesquisa.PUBLICADA,
        coleta_setor=True,
    )
    dados.update(extra)
    pesquisa = Pesquisa.objects.create(**dados)
    escala = Pergunta.objects.create(
        pesquisa=pesquisa, ordem=1, enunciado='As condições de trabalho são adequadas.',
        tipo=Pergunta.ESCALA, escala_min=1, escala_max=5, obrigatoria=True,
    )
    texto = Pergunta.objects.create(
        pesquisa=pesquisa, ordem=2, enunciado='O que você mais gosta na empresa?',
        tipo=Pergunta.TEXTO_LONGO,
    )
    return pesquisa, escala, texto


class PesquisaPublicaTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_get_publico_sem_autenticacao(self):
        pesquisa, _, _ = criar_pesquisa()
        r = self.client.get(f'/pesquisas/publica/{pesquisa.token}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['perguntas']), 2)
        # O token não pode voltar no payload público — ele já está na URL, mas
        # nada de gestão deve vazar para quem responde.
        self.assertNotIn('token', r.data)

    def test_rascunho_nao_aceita_resposta(self):
        pesquisa, escala, _ = criar_pesquisa(status=Pesquisa.RASCUNHO)
        r = self.client.get(f'/pesquisas/publica/{pesquisa.token}/')
        self.assertTrue(r.data.get('fechada'))
        r = self.client.post(
            f'/pesquisas/publica/{pesquisa.token}/',
            {'itens': [{'pergunta': escala.id, 'valor_numero': 5}]}, format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Resposta.objects.count(), 0)

    def test_fora_do_prazo_nao_aceita(self):
        ontem = date.today() - timedelta(days=1)
        pesquisa, escala, _ = criar_pesquisa(data_fim=ontem)
        r = self.client.post(
            f'/pesquisas/publica/{pesquisa.token}/',
            {'itens': [{'pergunta': escala.id, 'valor_numero': 5}]}, format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Resposta.objects.count(), 0)

    def test_obrigatoria_cobrada_no_servidor(self):
        pesquisa, _, texto = criar_pesquisa()
        r = self.client.post(
            f'/pesquisas/publica/{pesquisa.token}/',
            {'itens': [{'pergunta': texto.id, 'valor_texto': 'o pessoal'}]}, format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Resposta.objects.count(), 0)

    def test_resposta_gravada_sem_identificar_quem_respondeu(self):
        pesquisa, escala, texto = criar_pesquisa()
        r = self.client.post(
            f'/pesquisas/publica/{pesquisa.token}/',
            {
                'setor': 'Laboratório',
                'impressao': 'abc123',
                'itens': [
                    {'pergunta': escala.id, 'valor_numero': 4},
                    {'pergunta': texto.id, 'valor_texto': 'o time'},
                ],
            },
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        resposta = Resposta.objects.get()
        self.assertEqual(resposta.setor, 'Laboratório')
        self.assertEqual(resposta.itens.count(), 2)
        # Não existe campo de usuário na resposta: o anonimato é estrutural.
        self.assertFalse(any(f.name == 'usuario' for f in Resposta._meta.get_fields()))

    def test_pergunta_de_outra_pesquisa_e_ignorada(self):
        pesquisa, escala, _ = criar_pesquisa()
        outra, escala_outra, _ = criar_pesquisa()
        r = self.client.post(
            f'/pesquisas/publica/{pesquisa.token}/',
            {'itens': [
                {'pergunta': escala.id, 'valor_numero': 3},
                {'pergunta': escala_outra.id, 'valor_numero': 1},
            ]},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Resposta.objects.get(pesquisa=pesquisa).itens.count(), 1)

    def test_token_inexistente(self):
        r = self.client.get('/pesquisas/publica/naoexiste/')
        self.assertEqual(r.status_code, 404)


class ResultadosTests(TestCase):
    """As estatísticas. O ViewSet é IsRH, então o teste chama o método direto."""

    def setUp(self):
        self.client = APIClient()

    def _responder(self, pesquisa, escala, nota, setor):
        self.client.post(
            f'/pesquisas/publica/{pesquisa.token}/',
            {'setor': setor, 'itens': [{'pergunta': escala.id, 'valor_numero': nota}]},
            format='json',
        )

    def test_media_distribuicao_e_setor(self):
        from .views import PesquisaViewSet

        pesquisa, escala, texto = criar_pesquisa()
        for nota, setor in [(5, 'Laboratório'), (3, 'Laboratório'), (4, 'Produção')]:
            self._responder(pesquisa, escala, nota, setor)
        self.client.post(
            f'/pesquisas/publica/{pesquisa.token}/',
            {'setor': 'Produção', 'itens': [
                {'pergunta': escala.id, 'valor_numero': 2},
                {'pergunta': texto.id, 'valor_texto': 'o refeitório'},
            ]},
            format='json',
        )

        view = PesquisaViewSet()
        view.kwargs = {'pk': pesquisa.pk}
        view.format_kwarg = None
        view.request = type('R', (), {'query_params': {}, 'user': None})()
        dados = view.resultados(view.request, pk=pesquisa.pk).data

        self.assertEqual(dados['total_respostas'], 4)
        # (5 + 3 + 4 + 2) / 4
        self.assertEqual(dados['media_geral'], 3.5)

        bloco = next(p for p in dados['perguntas'] if p['id'] == escala.id)
        self.assertEqual(bloco['media'], 3.5)
        self.assertEqual(bloco['respondidas'], 4)
        # A escala inteira aparece, inclusive o 1 que ninguém marcou.
        self.assertEqual(
            bloco['distribuicao'],
            [{'valor': 1, 'quantidade': 0}, {'valor': 2, 'quantidade': 1},
             {'valor': 3, 'quantidade': 1}, {'valor': 4, 'quantidade': 1},
             {'valor': 5, 'quantidade': 1}],
        )

        por_setor = {s['setor']: s['media'] for s in dados['por_setor']}
        self.assertEqual(por_setor, {'Laboratório': 4.0, 'Produção': 3.0})

        aberta = next(p for p in dados['perguntas'] if p['id'] == texto.id)
        self.assertEqual(aberta['textos'], ['o refeitório'])
