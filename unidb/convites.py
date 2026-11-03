"""
Ficha de avaliação do treinamento respondida pelo celular.

Mesmo fluxo da autoavaliação do Jovem Aprendiz (`aprendizes.views`): o RH gera um link,
manda por QR, WhatsApp ou copiando, e quem abre responde sem login. Como a ficha é
anônima, o link é da turma e aceita uma resposta por participante.
"""
from django.db import transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from .models import AvaliacaoTreinamento, ConviteAvaliacaoTreinamento

GRUPOS_RH = ('Admin', 'Master', 'RHGestor')

# As cinco perguntas fechadas, na ordem e com o texto do papel (mod. novo).
PERGUNTAS = [
    ('avaliacao_geral', 'Como você avalia o treinamento de forma geral?', AvaliacaoTreinamento.ESCALA_QUALIDADE),
    ('conteudo_atendeu', 'O conteúdo abordado atendeu às suas expectativas?', AvaliacaoTreinamento.ESCALA_SIM),
    ('didatica_instrutor', 'A didática do(a) instrutor(a) foi:', AvaliacaoTreinamento.ESCALA_QUALIDADE),
    ('material_apoio', 'O material de apoio foi claro e útil?', AvaliacaoTreinamento.ESCALA_SIM),
    ('tempo_duracao', 'O tempo de duração foi:', AvaliacaoTreinamento.ESCALA_TEMPO),
]
ABERTAS = [
    ('pontos_positivos', 'Quais foram os pontos mais positivos?'),
    ('pontos_melhoria', 'O que poderia ser melhorado?'),
]


class IsRH(BasePermission):
    """``DEFAULT_PERMISSION_CLASSES`` está vazio no projeto: sem isto a API ficaria aberta."""
    message = 'Acesso restrito ao RH.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return user.is_superuser or user.groups.filter(name__in=GRUPOS_RH).exists()


class ConviteAvaliacaoSerializer(serializers.ModelSerializer):
    situacao = serializers.CharField(read_only=True)
    curso_nome = serializers.CharField(source='turma.curso.nome', read_only=True)
    turma_codigo = serializers.CharField(source='turma.codigo', read_only=True, default=None)
    turma_data = serializers.DateField(source='turma.data_inicial', read_only=True, default=None)
    instrutor = serializers.CharField(source='turma.instrutor', read_only=True, default=None)
    respostas = serializers.SerializerMethodField()

    class Meta:
        model = ConviteAvaliacaoTreinamento
        fields = ['id', 'token', 'turma', 'curso_nome', 'turma_codigo', 'turma_data', 'instrutor',
                  'expira_em', 'cancelado', 'situacao', 'respostas', 'criado_em']
        read_only_fields = ['token', 'expira_em', 'cancelado', 'criado_em']

    def get_respostas(self, obj):
        n = getattr(obj, 'n_respostas', None)
        return n if n is not None else obj.respostas.count()


class ConviteAvaliacaoViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """RH gera o link da ficha de uma turma. ``?turma=`` filtra."""
    permission_classes = [IsRH]
    serializer_class = ConviteAvaliacaoSerializer

    def get_queryset(self):
        from django.db.models import Count
        qs = (ConviteAvaliacaoTreinamento.objects.select_related('turma', 'turma__curso')
              .annotate(n_respostas=Count('respostas')))
        turma = self.request.query_params.get('turma')
        if turma:
            qs = qs.filter(turma_id=turma)
        return qs

    def create(self, request, *args, **kwargs):
        # Uma turma tem um link aberto por vez: gerar de novo devolve o mesmo, para o QR
        # projetado na sala e o link mandado no grupo continuarem valendo juntos.
        turma = request.data.get('turma')
        aberto = next((c for c in self.get_queryset().filter(turma_id=turma, cancelado=False)
                       if c.situacao == 'ABERTO'), None) if turma else None
        if aberto:
            return Response(self.get_serializer(aberto).data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        c = self.get_object()
        c.cancelado = True
        c.save(update_fields=['cancelado'])
        return Response(self.get_serializer(c).data)


class LimiteRespostaPublica(SimpleRateThrottle):
    """
    Por IP. Mais folgado que o do Jovem Aprendiz: a turma inteira responde na sala, pelo
    mesmo Wi-Fi — todo mundo sai pelo mesmo IP no mesmo minuto.
    """
    scope = 'unidb_publico'
    rate = '120/min'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class AvaliacaoPublicaView(APIView):
    """
    A ficha aberta pelo link: ``GET`` entrega treinamento e perguntas; ``POST`` grava uma
    resposta anônima. ``authentication_classes = []`` para um JWT vencido no navegador não
    derrubar a requisição com 401 (mesmo padrão das Pesquisas e da autoavaliação).
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LimiteRespostaPublica]

    MENSAGENS = {
        'CANCELADO': 'Este link foi encerrado pelo RH.',
        'VENCIDO': 'O prazo para avaliar este treinamento terminou.',
    }

    def _convite(self, token, travar=False):
        qs = ConviteAvaliacaoTreinamento.objects.select_related('turma', 'turma__curso')
        if travar:
            qs = qs.select_for_update()
        return qs.filter(token=token).first()

    def get(self, request, token):
        c = self._convite(token)
        if not c:
            return Response({'detail': 'Link não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        t = c.turma
        dados = {
            'curso': t.curso.nome, 'modulo': t.modulo, 'instrutor': t.instrutor,
            'data': t.data_inicial.isoformat() if t.data_inicial else None,
        }
        if c.situacao != 'ABERTO':
            return Response({**dados, 'fechado': True, 'situacao': c.situacao, 'detail': self.MENSAGENS[c.situacao]})
        return Response({
            **dados, 'fechado': False,
            'perguntas': [{'campo': campo, 'texto': texto, 'opcoes': [{'valor': v, 'rotulo': r} for v, r in escala]}
                          for campo, texto, escala in PERGUNTAS],
            'abertas': [{'campo': campo, 'texto': texto} for campo, texto in ABERTAS],
        })

    @transaction.atomic
    def post(self, request, token):
        c = self._convite(token, travar=True)
        if not c:
            return Response({'detail': 'Link não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        if c.situacao != 'ABERTO':
            return Response({'detail': self.MENSAGENS[c.situacao]}, status=status.HTTP_400_BAD_REQUEST)

        d = request.data
        dados, faltando = {}, []
        for campo, texto, escala in PERGUNTAS:
            valor = str(d.get(campo) or '').strip().upper()
            if valor not in {v for v, _ in escala}:
                faltando.append(texto)
            dados[campo] = valor
        # No celular as cinco fechadas são obrigatórias (no papel não dava para exigir).
        if faltando:
            return Response({'detail': f'Responda todas as perguntas ({len(faltando)} em branco).'},
                            status=status.HTTP_400_BAD_REQUEST)
        for campo, _ in ABERTAS:
            dados[campo] = (str(d.get(campo) or '').strip()[:4000]) or None

        t = c.turma
        AvaliacaoTreinamento.objects.create(
            turma=t, convite=c, nome_treinamento=t.curso.nome, instrutor=t.instrutor,
            data_conclusao=t.data_final or t.data_inicial, **dados,
        )
        return Response({'ok': True}, status=status.HTTP_201_CREATED)
