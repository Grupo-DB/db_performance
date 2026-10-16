from collections import defaultdict
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from avaliacoes.management.models import Colaborador

from .models import Acompanhamento, Etapa
from .permissions import IsRHAcompanhamento
from .regras import (
    checklist_do_texto, chave_nome, data_da_planilha, situacao_da_planilha, tipo_da_planilha, vencimentos,
)
from .serializers import AcompanhamentoSerializer, EtapaSerializer


def _dados_do_colaborador(c: Colaborador) -> dict:
    return {
        'colaborador': c,
        'nome': c.nome.strip(),
        'setor': getattr(c.setor, 'nome', '') or '',
        'cargo': getattr(c.cargo, 'nome', '') or '',
        'data_admissao': c.data_admissao.date() if c.data_admissao else None,
    }


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

        por_nome = {chave_nome(c.nome): c for c in Colaborador.objects.select_related('setor', 'cargo')}
        criados = atualizadas = etapas_criadas = 0
        ignoradas = []
        # Pessoa → acompanhamentos já existentes (a mesma pessoa pode ter voltado).
        existentes = defaultdict(list)
        for a in Acompanhamento.objects.prefetch_related('etapas'):
            existentes[chave_nome(a.nome)].append(a)

        linhas_ordenadas = sorted(
            [l for l in linhas if isinstance(l, dict)],
            key=lambda l: (data_da_planilha(l.get('vencimento')) or date.max),
        )
        with transaction.atomic():
            for i, linha in enumerate(linhas_ordenadas):
                nome = str(linha.get('nome') or '').strip()
                tipo = tipo_da_planilha(linha.get('tipo'))
                venc = data_da_planilha(linha.get('vencimento'))
                texto_tipo = chave_nome(linha.get('tipo'))
                if not nome or (not tipo and texto_tipo != 'DEMITIDO'):
                    ignoradas.append({'linha': linha.get('aba', ''), 'nome': nome, 'motivo': 'sem nome ou tipo desconhecido'})
                    continue
                situacao, pendencia = situacao_da_planilha(linha.get('situacao'))
                if texto_tipo == 'DEMITIDO':  # tipo "DEMITIDO": a pessoa saiu antes da etapa
                    tipo, situacao = Etapa.PRORROGACAO, Etapa.DESLIGADO
                if not venc:
                    # "PEDIDO DE DEMISSÃO" escrito no lugar da data: guarda a etapa no mês da aba.
                    aba = str(linha.get('aba') or '')
                    venc = date(int(aba[2:6]), int(aba[:2]), 1) if len(aba) == 6 and aba.isdigit() else None
                    situacao_texto, _ = situacao_da_planilha(linha.get('vencimento'))
                    if situacao_texto != Etapa.PENDENTE:
                        situacao = situacao_texto
                if not venc:
                    ignoradas.append({'linha': linha.get('aba', ''), 'nome': nome, 'motivo': 'sem vencimento'})
                    continue

                chave = chave_nome(nome)
                acompanhamento = next(
                    (a for a in existentes[chave]
                     if not any(e.tipo == tipo and e.vencimento != venc for e in a.etapas.all())),
                    None,
                )
                if acompanhamento is None:
                    colaborador = por_nome.get(chave)
                    base = _dados_do_colaborador(colaborador) if colaborador else {'nome': nome}
                    base['setor'] = str(linha.get('setor') or '').strip() or base.get('setor', '')
                    base['cargo'] = str(linha.get('cargo') or '').strip() or base.get('cargo', '')
                    base['nome'] = colaborador.nome.strip() if colaborador else nome
                    acompanhamento = Acompanhamento.objects.create(**base)
                    existentes[chave].append(acompanhamento)
                    criados += 1

                observacao = str(linha.get('observacao') or '').strip()
                etapa = next((e for e in acompanhamento.etapas.all() if e.tipo == tipo), None)
                campos = {
                    'vencimento': venc, 'situacao': situacao,
                    'avaliacao_feita': situacao == Etapa.CONCLUIDO,
                    'pendencia': pendencia, 'observacao': observacao,
                    **checklist_do_texto(observacao), **checklist_do_texto(pendencia),
                }
                if 'INFORMADO' in chave_nome(observacao):
                    campos['plano_saude_informado'] = True
                if etapa is None:
                    Etapa.objects.create(acompanhamento=acompanhamento, tipo=tipo, **campos)
                    etapas_criadas += 1
                else:
                    for k, v in campos.items():
                        setattr(etapa, k, v)
                    etapa.save()
                    atualizadas += 1
                acompanhamento._prefetched_objects_cache = {}

            for lista in existentes.values():
                for a in lista:
                    a.atualizar_situacao()

        return Response({
            'pessoas_criadas': criados, 'etapas_criadas': etapas_criadas,
            'etapas_atualizadas': atualizadas, 'ignoradas': ignoradas,
        })


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
