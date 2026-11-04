"""
Ficha de avaliação do treinamento no Programa Jovem Aprendiz.

É a ficha da UNIDB (mod. novo: 5 fechadas + 2 abertas), com o fluxo de envio da
autoavaliação: o RH gera um link por jovem e manda por WhatsApp, QR ou copiando; o
jovem responde pelo celular, sem login.

ANÔNIMA (decisão do usuário, 04/11/2026): o convite guarda quem foi chamado e quando
respondeu — para a faixa "Links enviados" mostrar quem falta —, mas a resposta é gravada
sem nome e sem apontar para o convite.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AvaliacaoTreinamentoJovem as Ficha, ConviteTreinamentoJovem
from .permissions import IsRHAcompanhamento

# Ordem e texto do papel — os mesmos da UNIDB (unidb/convites.py).
PERGUNTAS = [
    ('avaliacao_geral', 'Como você avalia o treinamento de forma geral?', Ficha.QUALIDADE),
    ('conteudo_atendeu', 'O conteúdo abordado atendeu às suas expectativas?', Ficha.SIM),
    ('didatica_instrutor', 'A didática do(a) instrutor(a) foi:', Ficha.QUALIDADE),
    ('material_apoio', 'O material de apoio foi claro e útil?', Ficha.SIM),
    ('tempo_duracao', 'O tempo de duração foi:', Ficha.TEMPO),
]
ABERTAS = [
    ('pontos_positivos', 'Quais foram os pontos mais positivos?'),
    ('pontos_melhoria', 'O que poderia ser melhorado?'),
]
CAMPOS_FECHADOS = [c for c, _, _ in PERGUNTAS]


def formulario() -> dict:
    return {
        'perguntas': [{'campo': c, 'texto': t, 'opcoes': [{'valor': v, 'rotulo': r} for v, r in esc]}
                      for c, t, esc in PERGUNTAS],
        'abertas': [{'campo': c, 'texto': t} for c, t in ABERTAS],
    }


class FichaSerializer(serializers.ModelSerializer):
    criado_por_nome = serializers.CharField(source='criado_por.username', read_only=True, default=None)

    class Meta:
        model = Ficha
        fields = ['id', 'treinamento', 'instrutor', 'data', *CAMPOS_FECHADOS, 'pontos_positivos', 'pontos_melhoria',
                  'origem', 'criado_por_nome', 'criado_em']
        read_only_fields = ['origem', 'criado_em']

    def validate_treinamento(self, v):
        v = (v or '').strip()
        if not v:
            raise serializers.ValidationError('Informe o treinamento avaliado.')
        return v[:255]

    def validate(self, dados):
        if not any(dados.get(c) for c in CAMPOS_FECHADOS) and self.instance is None:
            raise serializers.ValidationError('Marque pelo menos uma resposta.')
        return dados


class FichaTreinamentoViewSet(viewsets.ModelViewSet):
    """Fichas do treinamento do Programa Jovem Aprendiz (digitadas pelo RH ou vindas do link)."""
    permission_classes = [IsRHAcompanhamento]
    serializer_class = FichaSerializer

    def get_queryset(self):
        return Ficha.objects.select_related('criado_por')

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user, origem='DIGITADA')

    @action(detail=False, methods=['get'])
    def formulario(self, request):
        return Response(formulario())


class ConviteTreinamentoSerializer(serializers.ModelSerializer):
    situacao = serializers.CharField(read_only=True)

    class Meta:
        model = ConviteTreinamentoJovem
        fields = ['id', 'token', 'treinamento', 'instrutor', 'data_treinamento', 'colaborador', 'nome', 'setor', 'telefone',
                  'expira_em', 'cancelado', 'respondido_em', 'situacao', 'criado_em']
        read_only_fields = ['token', 'expira_em', 'cancelado', 'respondido_em', 'criado_em']

    def validate_nome(self, v):
        v = (v or '').strip()
        if not v:
            raise serializers.ValidationError('Informe o nome do jovem.')
        return v[:150]

    def validate_treinamento(self, v):
        v = (v or '').strip()
        if not v:
            raise serializers.ValidationError('Informe o treinamento avaliado.')
        return v[:255]

    def validate_telefone(self, v):
        return ''.join(ch for ch in (v or '') if ch.isdigit())[:20]


class ConviteTreinamentoViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """RH gera o link da ficha do treinamento para o jovem responder pelo celular."""
    permission_classes = [IsRHAcompanhamento]
    serializer_class = ConviteTreinamentoSerializer
    queryset = ConviteTreinamentoJovem.objects.all()

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        c = self.get_object()
        if c.respondido_em:
            return Response({'detail': 'Este link já foi respondido.'}, status=status.HTTP_400_BAD_REQUEST)
        c.cancelado = True
        c.save(update_fields=['cancelado'])
        return Response(self.get_serializer(c).data)


class FichaTreinamentoPublicaView(APIView):
    """
    A ficha aberta pelo link: ``GET`` entrega treinamento e perguntas; ``POST`` grava a resposta
    sem nome. ``authentication_classes = []`` para um JWT vencido no navegador não derrubar a
    requisição com 401 (mesmo padrão da autoavaliação).
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    MENSAGENS = {
        'RESPONDIDO': 'Esta avaliação já foi respondida. Obrigado!',
        'CANCELADO': 'Este link foi cancelado. Peça um novo ao RH.',
        'VENCIDO': 'Este link venceu. Peça um novo ao RH.',
    }

    def get_throttles(self):
        # O mesmo limite por IP da autoavaliação (import tardio: evita ciclo com views.py).
        from .views import LimiteRespostaPublica
        return [LimiteRespostaPublica()]

    @staticmethod
    def _dados(c):
        return {'curso': c.treinamento, 'modulo': None, 'instrutor': c.instrutor or None,
                'data': c.data_treinamento.isoformat() if c.data_treinamento else None}

    def get(self, request, token):
        c = ConviteTreinamentoJovem.objects.filter(token=token).first()
        if not c:
            return Response({'detail': 'Link não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        if c.situacao != 'ABERTO':
            return Response({**self._dados(c), 'fechado': True, 'situacao': c.situacao, 'detail': self.MENSAGENS[c.situacao]})
        return Response({**self._dados(c), 'fechado': False, **formulario()})

    @transaction.atomic
    def post(self, request, token):
        c = ConviteTreinamentoJovem.objects.select_for_update().filter(token=token).first()
        if not c:
            return Response({'detail': 'Link não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        if c.situacao != 'ABERTO':
            return Response({'detail': self.MENSAGENS[c.situacao]}, status=status.HTTP_400_BAD_REQUEST)
        d = request.data
        dados, faltando = {}, 0
        for campo, _, escala in PERGUNTAS:
            valor = str(d.get(campo) or '').strip().upper()
            if valor not in {v for v, _ in escala}:
                faltando += 1
            dados[campo] = valor
        if faltando:
            return Response({'detail': f'Responda todas as perguntas ({faltando} em branco).'}, status=status.HTTP_400_BAD_REQUEST)
        for campo, _ in ABERTAS:
            dados[campo] = str(d.get(campo) or '').strip()[:4000]
        Ficha.objects.create(treinamento=c.treinamento, instrutor=c.instrutor, data=c.data_treinamento,
                             origem='LINK', **dados)
        c.respondido_em = timezone.now()
        c.save(update_fields=['respondido_em'])
        return Response({'ok': True}, status=status.HTTP_201_CREATED)
