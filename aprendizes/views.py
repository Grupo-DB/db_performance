from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework.response import Response

from avaliacoes.management.models import Colaborador

from . import jovem_aprendiz
from .models import Acompanhamento, AvaliacaoJovemAprendiz, ConviteAutoavaliacao, Etapa
from .permissions import IsRHAcompanhamento
from .importacao import _dados_do_colaborador, importar_linhas
from .regras import vencimentos
from .serializers import AcompanhamentoSerializer, AvaliacaoJovemAprendizSerializer, EtapaSerializer


class AcompanhamentoViewSet(viewsets.ModelViewSet):
    """Uma pessoa no período de experiência, com as etapas dela."""

    permission_classes = [IsRHAcompanhamento]
    serializer_class = AcompanhamentoSerializer

    def get_queryset(self):
        qs = Acompanhamento.objects.prefetch_related(
            Prefetch('etapas', queryset=Etapa.objects.select_related('concluido_por__colaborador'))
        )
        situacao = self.request.query_params.get('situacao')
        if situacao:
            qs = qs.filter(situacao=situacao)
        return qs

    def perform_create(self, serializer):
        """Com data de admissão, as duas etapas do contrato já nascem com o vencimento."""
        dados = {}
        colaborador = serializer.validated_data.get('colaborador')
        if colaborador:
            base = _dados_do_colaborador(colaborador)
            dados = {k: v for k, v in base.items() if not serializer.validated_data.get(k)}
        with transaction.atomic():
            acompanhamento = serializer.save(**dados)
            if acompanhamento.data_admissao:
                for tipo, venc in vencimentos(acompanhamento.data_admissao).items():
                    Etapa.objects.create(acompanhamento=acompanhamento, tipo=tipo, vencimento=venc)

    @action(detail=False, methods=['get'])
    def candidatos(self, request):
        """
        Colaboradores ativos para começar um acompanhamento: admitidos nos últimos
        ``dias`` (padrão 120) e ainda sem acompanhamento. ``q`` procura em todos.
        """
        q = (request.query_params.get('q') or '').strip()
        qs = Colaborador.objects.filter(situacao=True).select_related('setor', 'cargo')
        if q:
            qs = qs.filter(nome__icontains=q)
        else:
            dias = int(request.query_params.get('dias') or 120)
            # Intervalo de datetime, não ``__date``: no MySQL da VM (sem tabelas de fuso) o __date vira
            # CONVERT_TZ = NULL e a lista vinha vazia.
            desde = timezone.localdate() - timedelta(days=dias)
            qs = qs.filter(data_admissao__gte=timezone.make_aware(datetime.combine(desde, datetime.min.time())))
        ja = set(Acompanhamento.objects.exclude(colaborador=None).values_list('colaborador_id', flat=True))
        lista = []
        for c in qs.order_by('-data_admissao', 'nome')[:80]:
            d = _dados_do_colaborador(c)
            lista.append({
                'id': c.id, 'nome': d['nome'], 'setor': d['setor'], 'cargo': d['cargo'],
                'data_admissao': d['data_admissao'], 'ja_acompanhado': c.id in ja,
            })
        return Response(lista)

    @action(detail=False, methods=['post'])
    def importar(self, request):
        """
        Linhas da planilha antiga, lidas no navegador: ``{aba, nome, setor, cargo, tipo,
        vencimento, situacao, observacao}``. Agrupa por pessoa (nome sem acento), liga ao
        cadastro de colaboradores pelo nome e não duplica numa reimportação.
        """
        linhas = request.data.get('linhas') or []
        if not isinstance(linhas, list):
            return Response({'detail': 'Envie "linhas" como lista.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(importar_linhas(linhas))


class EtapaViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin,
                   mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    Lista do mês (``?mes=AAAA-MM``) ou de um intervalo (``?de=&ate=``), como as abas
    da planilha; ``?atrasadas=1`` traz as pendentes vencidas de qualquer mês.
    """

    permission_classes = [IsRHAcompanhamento]
    serializer_class = EtapaSerializer

    def get_queryset(self):
        qs = Etapa.objects.select_related('acompanhamento', 'concluido_por__colaborador')
        p = self.request.query_params
        if self.action != 'list':
            return qs
        if p.get('atrasadas'):
            return qs.filter(situacao=Etapa.PENDENTE, vencimento__lt=timezone.localdate())
        mes = p.get('mes')
        if mes:
            ano, m = (int(x) for x in mes.split('-'))
            qs = qs.filter(vencimento__year=ano, vencimento__month=m)
        if p.get('de'):
            qs = qs.filter(vencimento__gte=p['de'])
        if p.get('ate'):
            qs = qs.filter(vencimento__lte=p['ate'])
        if p.get('q'):
            qs = qs.filter(Q(acompanhamento__nome__icontains=p['q']) | Q(acompanhamento__setor__icontains=p['q']))
        return qs

    def _registrar_conclusao(self, etapa):
        if etapa.situacao == Etapa.CONCLUIDO and not etapa.concluido_em:
            etapa.concluido_em = timezone.now()
            etapa.concluido_por = self.request.user
            etapa.save(update_fields=['concluido_em', 'concluido_por'])
        elif etapa.situacao != Etapa.CONCLUIDO and etapa.concluido_em:
            etapa.concluido_em = None
            etapa.concluido_por = None
            etapa.save(update_fields=['concluido_em', 'concluido_por'])
        etapa.acompanhamento.atualizar_situacao()

    def perform_create(self, serializer):
        self._registrar_conclusao(serializer.save())

    def perform_update(self, serializer):
        self._registrar_conclusao(serializer.save())

    def perform_destroy(self, instance):
        acompanhamento = instance.acompanhamento
        instance.delete()
        acompanhamento.atualizar_situacao()


class AvaliacaoJovemAprendizViewSet(viewsets.ModelViewSet):
    """
    Programa Jovem Aprendiz: avaliação do instrutor e autoavaliação (``?tipo=INSTRUTOR|AUTO``).
    ``formularios/`` devolve o texto dos dois documentos; ``comparativo/`` põe lado a lado a última
    avaliação do instrutor e a última autoavaliação do mesmo jovem.
    """
    permission_classes = [IsRHAcompanhamento]
    serializer_class = AvaliacaoJovemAprendizSerializer

    def get_queryset(self):
        qs = AvaliacaoJovemAprendiz.objects.select_related('criado_por')
        p = self.request.query_params
        if p.get('tipo'):
            qs = qs.filter(tipo=p['tipo'])
        if p.get('colaborador'):
            qs = qs.filter(colaborador_id=p['colaborador'])
        if p.get('nome'):
            qs = qs.filter(nome__iexact=p['nome'].strip())
        return qs

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    @action(detail=False, methods=['get'])
    def formularios(self, request):
        return Response({t: jovem_aprendiz.formulario(t) for t in ('INSTRUTOR', 'AUTO')})

    @action(detail=False, methods=['get'])
    def jovens(self, request):
        """Colaboradores ativos para escolher (``?q=``); os que já têm avaliação vêm marcados."""
        q = (request.query_params.get('q') or '').strip()
        qs = Colaborador.objects.filter(situacao=True).select_related('setor', 'cargo')
        if q:
            qs = qs.filter(nome__icontains=q)
        avaliados = set(AvaliacaoJovemAprendiz.objects.exclude(colaborador=None).values_list('colaborador_id', flat=True))
        lista = []
        for c in qs.order_by('nome')[:60]:
            d = _dados_do_colaborador(c)
            lista.append({'id': c.id, 'nome': d['nome'], 'setor': d['setor'], 'cargo': d['cargo'], 'ja_avaliado': c.id in avaliados})
        return Response(lista)

    @action(detail=False, methods=['get'])
    def comparativo(self, request):
        """Última do instrutor × última autoavaliação de um jovem (``?colaborador=`` ou ``?nome=``)."""
        qs = self.get_queryset()
        if not (request.query_params.get('colaborador') or request.query_params.get('nome')):
            return Response({'detail': 'Informe o jovem.'}, status=status.HTTP_400_BAD_REQUEST)
        inst = qs.filter(tipo=AvaliacaoJovemAprendiz.INSTRUTOR).first()
        auto = qs.filter(tipo=AvaliacaoJovemAprendiz.AUTO).first()
        nomes = jovem_aprendiz.formulario('INSTRUTOR')['competencias']
        linhas = [{'chave': c['chave'], 'nome': c['nome'],
                   'instrutor': (inst.notas or {}).get(c['chave']) if inst else None,
                   'auto': (auto.notas or {}).get(c['chave']) if auto else None} for c in nomes]
        for l in linhas:
            l['diferenca'] = l['auto'] - l['instrutor'] if l['auto'] and l['instrutor'] else None
        ser = self.get_serializer
        return Response({
            'instrutor': ser(inst).data if inst else None, 'auto': ser(auto).data if auto else None, 'linhas': linhas,
            # Onde o jovem se vê bem acima do que o instrutor vê (>= 2 pontos): conversa de feedback.
            'atencao': [l['nome'] for l in linhas if l['diferenca'] is not None and l['diferenca'] >= 2],
        })

    @action(detail=False, methods=['get'])
    def resumo(self, request):
        """Média de cada competência (por tipo) entre todas as avaliações — o retrato da turma."""
        saida = {}
        for tipo in ('INSTRUTOR', 'AUTO'):
            avs = list(AvaliacaoJovemAprendiz.objects.filter(tipo=tipo).values_list('notas', flat=True))
            saida[tipo] = {
                'total': len(avs),
                'medias': {c: (round(sum(a.get(c, 0) for a in avs) / len(avs), 2) if avs else None) for c in jovem_aprendiz.CHAVES},
            }
        return Response(saida)


class ConviteSerializer(serializers.ModelSerializer):
    situacao = serializers.CharField(read_only=True)
    avaliacao_id = serializers.IntegerField(source='avaliacao.id', read_only=True, default=None)

    class Meta:
        model = ConviteAutoavaliacao
        fields = ['id', 'token', 'colaborador', 'nome', 'setor', 'telefone', 'expira_em', 'cancelado', 'respondido_em',
                  'situacao', 'avaliacao_id', 'criado_em']
        read_only_fields = ['token', 'expira_em', 'cancelado', 'respondido_em', 'criado_em']

    def validate_nome(self, v):
        v = (v or '').strip()
        if not v:
            raise serializers.ValidationError('Informe o nome do jovem.')
        return v[:150]

    def validate_telefone(self, v):
        return ''.join(ch for ch in (v or '') if ch.isdigit())[:20]


class ConviteAutoavaliacaoViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """RH gera o link da autoavaliação para o jovem responder pelo celular."""
    permission_classes = [IsRHAcompanhamento]
    serializer_class = ConviteSerializer
    queryset = ConviteAutoavaliacao.objects.select_related('avaliacao')

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        c = self.get_object()
        if c.respondido_em:
            return Response({'detail': 'Já respondido: exclua a autoavaliação se precisar.'}, status=status.HTTP_400_BAD_REQUEST)
        c.cancelado = True
        c.save(update_fields=['cancelado'])
        return Response(self.get_serializer(c).data)


class LimiteRespostaPublica(SimpleRateThrottle):
    """Por IP: o link é público; uma pessoa responde uma vez, 30/min sobra e corta abuso."""
    scope = 'aprendizes_publico'
    rate = '30/min'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class AutoavaliacaoPublicaView(APIView):
    """
    A autoavaliação aberta, pelo link do convite: ``GET`` entrega o formulário e o nome do jovem;
    ``POST`` grava. Sem login por definição — ``authentication_classes = []`` evita que um JWT
    vencido no navegador derrube a requisição com 401 (mesmo padrão das Pesquisas).
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LimiteRespostaPublica]

    MENSAGENS = {
        'RESPONDIDO': 'Esta autoavaliação já foi respondida. Obrigado!',
        'CANCELADO': 'Este link foi cancelado. Peça um novo ao RH.',
        'VENCIDO': 'Este link venceu. Peça um novo ao RH.',
    }

    def get(self, request, token):
        c = ConviteAutoavaliacao.objects.filter(token=token).first()
        if not c:
            return Response({'detail': 'Link não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        if c.situacao != 'ABERTO':
            return Response({'fechado': True, 'situacao': c.situacao, 'detail': self.MENSAGENS[c.situacao], 'nome': c.nome.split(' ')[0]})
        return Response({'fechado': False, 'nome': c.nome, 'setor': c.setor, 'formulario': jovem_aprendiz.formulario('AUTO')})

    @transaction.atomic
    def post(self, request, token):
        c = ConviteAutoavaliacao.objects.select_for_update().filter(token=token).first()
        if not c:
            return Response({'detail': 'Link não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        if c.situacao != 'ABERTO':
            return Response({'detail': self.MENSAGENS[c.situacao]}, status=status.HTTP_400_BAD_REQUEST)
        ser = AvaliacaoJovemAprendizSerializer(data={
            'tipo': AvaliacaoJovemAprendiz.AUTO, 'colaborador': c.colaborador_id, 'nome': c.nome, 'setor': c.setor,
            'data': timezone.localdate().isoformat(), 'notas': request.data.get('notas') or {},
            'respostas': request.data.get('respostas') or {}, 'avaliador': 'Respondida pelo jovem (link)',
        })
        ser.is_valid(raise_exception=True)
        av = ser.save()
        c.avaliacao, c.respondido_em = av, timezone.now()
        c.save(update_fields=['avaliacao', 'respondido_em'])
        return Response({'ok': True, 'nome': c.nome.split(' ')[0]}, status=status.HTTP_201_CREATED)
