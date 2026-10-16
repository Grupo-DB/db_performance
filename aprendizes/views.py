from datetime import timedelta

from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from avaliacoes.management.models import Colaborador

from .models import Acompanhamento, Etapa
from .permissions import IsRHAcompanhamento
from .importacao import _dados_do_colaborador, importar_linhas
from .regras import vencimentos
from .serializers import AcompanhamentoSerializer, EtapaSerializer


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
            qs = qs.filter(data_admissao__date__gte=timezone.localdate() - timedelta(days=dias))
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
