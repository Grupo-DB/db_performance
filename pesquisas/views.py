from collections import Counter, defaultdict
from datetime import date

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from recrutamento.permissions import IsRH

from .models import Pergunta, Pesquisa, Resposta, RespostaItem
from .serializers import (
    PesquisaPublicaSerializer,
    PesquisaSerializer,
    RespostaSerializer,
)


class PesquisaViewSet(viewsets.ModelViewSet):
    """Gestão das pesquisas — restrita ao RH, como o resto do módulo."""

    queryset = Pesquisa.objects.all().prefetch_related('perguntas')
    serializer_class = PesquisaSerializer
    permission_classes = [IsRH]

    def perform_create(self, serializer):
        serializer.save(criada_por=self.request.user)

    def update(self, request, *args, **kwargs):
        pesquisa = self.get_object()
        # Trocar as perguntas de uma pesquisa que já tem resposta destruiria o
        # que foi respondido (o serializer recria as perguntas). Os demais campos
        # — título, mensagens, status, período — continuam editáveis.
        if 'perguntas' in request.data and pesquisa.respostas.exists():
            return Response(
                {'detail': 'Esta pesquisa já tem respostas: as perguntas não podem mais ser alteradas. '
                           'Duplique-a para criar uma versão nova.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def duplicar(self, request, pk=None):
        """Cópia em rascunho, com token novo — o caminho para a edição de uma pesquisa já respondida."""
        origem = self.get_object()
        perguntas = list(origem.perguntas.all())

        origem.pk = None
        origem.token = Pesquisa._meta.get_field('token').get_default()
        origem.status = Pesquisa.RASCUNHO
        origem.titulo = f'{origem.titulo} (cópia)'
        origem.criada_por = request.user
        origem.save()

        for pergunta in perguntas:
            pergunta.pk = None
            pergunta.pesquisa = origem
            pergunta.save()

        return Response(self.get_serializer(origem).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='novo-token')
    def novo_token(self, request, pk=None):
        """Invalida o link antigo. Útil quando o endereço vazou para fora da empresa."""
        pesquisa = self.get_object()
        pesquisa.token = Pesquisa._meta.get_field('token').get_default()
        pesquisa.save(update_fields=['token'])
        return Response(self.get_serializer(pesquisa).data)

    @action(detail=True, methods=['get'])
    def resultados(self, request, pk=None):
        """
        Estatísticas da pesquisa.

        Por pergunta: quantas responderam, e conforme o tipo a média com a
        distribuição (escala/número), a contagem por opção (escolha/sim-não) ou
        a lista de textos. Aceita `?setor=` para recortar.
        """
        pesquisa = self.get_object()
        respostas = pesquisa.respostas.all()
        setor = request.query_params.get('setor')
        if setor:
            respostas = respostas.filter(setor=setor)

        ids = list(respostas.values_list('id', flat=True))
        itens = RespostaItem.objects.filter(resposta_id__in=ids)

        por_pergunta = defaultdict(list)
        for item in itens:
            por_pergunta[item.pergunta_id].append(item)

        perguntas = []
        for pergunta in pesquisa.perguntas.all():
            lista = por_pergunta.get(pergunta.id, [])
            bloco = {
                'id': pergunta.id,
                'ordem': pergunta.ordem,
                'secao': pergunta.secao,
                'enunciado': pergunta.enunciado,
                'tipo': pergunta.tipo,
                'respondidas': len(lista),
            }

            if pergunta.tipo in Pergunta.TIPOS_NUMERICOS:
                numeros = [i.valor_numero for i in lista if i.valor_numero is not None]
                bloco['media'] = round(sum(numeros) / len(numeros), 2) if numeros else None
                # Distribuição na escala inteira, inclusive os pontos sem nenhuma
                # marcação: um 1 que ninguém marcou é informação, e sumindo da
                # lista o gráfico mudaria de forma entre perguntas.
                contagem = Counter(int(n) for n in numeros)
                bloco['distribuicao'] = [
                    {'valor': v, 'quantidade': contagem.get(v, 0)}
                    for v in range(pergunta.escala_min, pergunta.escala_max + 1)
                ] if pergunta.tipo == Pergunta.ESCALA else []
            elif pergunta.tipo in (Pergunta.ESCOLHA_UNICA, Pergunta.ESCOLHA_MULTIPLA, Pergunta.SIM_NAO):
                contagem = Counter()
                for item in lista:
                    for opcao in (item.valor_opcoes or []):
                        contagem[str(opcao)] += 1
                    if item.valor_texto:
                        contagem[item.valor_texto] += 1
                base = pergunta.opcoes or list(contagem.keys())
                if pergunta.tipo == Pergunta.SIM_NAO:
                    base = ['Sim', 'Não']
                bloco['opcoes'] = [{'opcao': o, 'quantidade': contagem.get(o, 0)} for o in base]
            else:
                bloco['textos'] = [i.valor_texto for i in lista if (i.valor_texto or '').strip()]

            perguntas.append(bloco)

        # Média por setor só faz sentido sobre as perguntas de escala, que são as
        # comparáveis entre si (todas na mesma régua).
        por_setor = defaultdict(list)
        escala_ids = {p.id for p in pesquisa.perguntas.all() if p.tipo == Pergunta.ESCALA}
        setor_da_resposta = dict(respostas.values_list('id', 'setor'))
        for item in itens:
            if item.pergunta_id in escala_ids and item.valor_numero is not None:
                por_setor[setor_da_resposta.get(item.resposta_id) or 'Não informado'].append(item.valor_numero)

        return Response({
            'pesquisa': {'id': pesquisa.id, 'titulo': pesquisa.titulo, 'status': pesquisa.status},
            'total_respostas': respostas.count(),
            'setores': sorted({s for s in pesquisa.respostas.values_list('setor', flat=True) if s}),
            'media_geral': round(
                sum(sum(v) for v in por_setor.values()) / sum(len(v) for v in por_setor.values()), 2
            ) if por_setor else None,
            'por_setor': [
                {'setor': s, 'media': round(sum(v) / len(v), 2), 'respostas_escala': len(v)}
                for s, v in sorted(por_setor.items())
            ],
            'perguntas': perguntas,
        })


class PesquisaPublicaView(APIView):
    """
    O formulário aberto: `GET` entrega as perguntas, `POST` grava a resposta.

    Sem autenticação por definição — o link é distribuído a quem vai responder e
    a pesquisa é anônima. `authentication_classes = []` precisa estar aqui junto
    do `AllowAny`: sem isso o JWT ainda tenta autenticar e um token vencido no
    navegador derruba a requisição com 401.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        pesquisa = Pesquisa.objects.filter(token=token).prefetch_related('perguntas').first()
        if not pesquisa:
            return Response({'detail': 'Pesquisa não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        situacao = self._situacao(pesquisa)
        if situacao:
            return Response({'detail': situacao, 'fechada': True}, status=status.HTTP_200_OK)

        return Response(PesquisaPublicaSerializer(pesquisa).data)

    @transaction.atomic
    def post(self, request, token):
        pesquisa = Pesquisa.objects.filter(token=token).prefetch_related('perguntas').first()
        if not pesquisa:
            return Response({'detail': 'Pesquisa não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        situacao = self._situacao(pesquisa)
        if situacao:
            return Response({'detail': situacao}, status=status.HTTP_400_BAD_REQUEST)

        perguntas = {p.id: p for p in pesquisa.perguntas.all()}
        enviados = request.data.get('itens') or []
        setor = (request.data.get('setor') or '').strip()

        if pesquisa.setor_obrigatorio and not setor:
            return Response({'detail': 'Informe o setor.'}, status=status.HTTP_400_BAD_REQUEST)

        # Obrigatórias precisam vir preenchidas. A checagem é aqui e não só na
        # tela: o POST é público e qualquer um pode chamá-lo direto.
        respondidas = {
            int(i['pergunta']) for i in enviados
            if i.get('pergunta') is not None and self._tem_conteudo(i)
        }
        faltando = [p.enunciado for p in perguntas.values() if p.obrigatoria and p.id not in respondidas]
        if faltando:
            return Response(
                {'detail': 'Responda as perguntas obrigatórias.', 'perguntas': faltando},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resposta = Resposta.objects.create(
            pesquisa=pesquisa,
            setor=setor,
            impressao=str(request.data.get('impressao') or '')[:64],
        )

        for item in enviados:
            pergunta = perguntas.get(int(item['pergunta'])) if item.get('pergunta') is not None else None
            # Pergunta de outra pesquisa (ou id inventado) é descartada em silêncio:
            # o POST é público e não vale derrubar a resposta inteira por isso.
            if not pergunta or not self._tem_conteudo(item):
                continue
            RespostaItem.objects.create(
                resposta=resposta,
                pergunta=pergunta,
                valor_numero=item.get('valor_numero'),
                valor_texto=(item.get('valor_texto') or '')[:5000],
                valor_opcoes=item.get('valor_opcoes') or [],
            )

        return Response(
            {'detail': 'Resposta registrada.', 'mensagem': pesquisa.mensagem_encerramento},
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _tem_conteudo(item) -> bool:
        return (
            item.get('valor_numero') is not None
            or bool((item.get('valor_texto') or '').strip())
            or bool(item.get('valor_opcoes'))
        )

    @staticmethod
    def _situacao(pesquisa) -> str:
        """Devolve o motivo de o formulário não aceitar resposta, ou string vazia."""
        if pesquisa.status == Pesquisa.RASCUNHO:
            return 'Esta pesquisa ainda não foi publicada.'
        if pesquisa.status == Pesquisa.ENCERRADA:
            return 'Esta pesquisa está encerrada. Obrigado pelo interesse!'
        hoje = date.today()
        if pesquisa.data_inicio and hoje < pesquisa.data_inicio:
            return f'Esta pesquisa abre em {pesquisa.data_inicio.strftime("%d/%m/%Y")}.'
        if pesquisa.data_fim and hoje > pesquisa.data_fim:
            return 'O prazo para responder esta pesquisa terminou. Obrigado pelo interesse!'
        return ''
