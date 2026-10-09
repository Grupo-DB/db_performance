from datetime import date, timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from kanban.models import KanbanColumn, KanbanTask

from . import ia
from .models import TEMAS, EvidenciaAnexo, ExtracaoIA, Norma, PlanoAcao, Requisito, Verificacao
from .permissions import IsConformidade
from .serializers import (
    ExtracaoIASerializer, NormaSerializer, PlanoAcaoSerializer, RequisitoSerializer, VerificacaoSerializer,
)
from .tasks import extrair_requisitos

RESULTADOS_VALIDOS = {r for r, _ in Verificacao.RESULTADOS}
TIPOS_COM_VALIDADE = ('LICENCA', 'OUTORGA', 'TAC')
# Plano em aberto: nem concluído à mão nem com a tarefa do Kanban concluída.
PLANO_ABERTO = Q(concluido_em__isnull=True) & (Q(tarefa__isnull=True) | Q(tarefa__concluido_em__isnull=True))


def _data(valor, campo):
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ValidationError({campo: 'Data inválida (use AAAA-MM-DD).'})


def _usuario(valor, campo):
    if valor in (None, '', 'null'):
        return None
    try:
        return User.objects.get(pk=int(valor))
    except (User.DoesNotExist, ValueError, TypeError):
        raise ValidationError({campo: 'Usuário não encontrado.'})


def _criar_tarefa_kanban(plano: PlanoAcao, coluna_id, usuario) -> KanbanTask:
    """Põe o plano de ação num quadro do Kanban, onde o dia a dia acontece."""
    try:
        coluna = KanbanColumn.objects.select_related('quadro').get(pk=int(coluna_id))
    except (KanbanColumn.DoesNotExist, ValueError, TypeError):
        raise ValidationError({'coluna_id': 'Lista do Kanban não encontrada.'})
    quadro = coluna.quadro
    if not (usuario.is_superuser or quadro.criado_por_id == usuario.id
            or quadro.membros.filter(pk=usuario.pk).exists()):
        raise ValidationError({'coluna_id': 'Você não participa deste quadro do Kanban.'})

    req = plano.requisito
    ref = f' ({req.referencia})' if req.referencia else ''
    descricao = (
        f'{plano.descricao}\n\n'
        f'Requisito legal: {req.norma.identificacao}{ref}\n'
        f'{req.descricao}'
    )
    tarefa = KanbanTask.objects.create(
        coluna=coluna,
        dono=usuario,
        responsavel=plano.responsavel,
        titulo=f'[Conformidade] {plano.descricao[:200]}',
        descricao=descricao,
        prioridade='alta' if req.situacao == 'NAO_ATENDIDO' else 'media',
        tags=['Conformidade Legal'],
        prazo=plano.prazo,
    )
    plano.tarefa = tarefa
    plano.save(update_fields=['tarefa'])
    return tarefa


class NormaViewSet(viewsets.ModelViewSet):
    permission_classes = [IsConformidade]
    serializer_class = NormaSerializer

    def get_queryset(self):
        qs = Norma.objects.annotate(total_requisitos=Count('requisitos', filter=Q(requisitos__ativo=True)))
        p = self.request.query_params
        for campo in ('tema', 'esfera', 'situacao', 'tipo'):
            if p.get(campo):
                qs = qs.filter(**{campo: p[campo]})
        if p.get('q'):
            termo = p['q'].strip()
            qs = qs.filter(Q(ementa__icontains=termo) | Q(numero__icontains=termo) | Q(orgao__icontains=termo))
        return qs

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'detail': 'Esta norma tem requisitos cadastrados. Marque-a como revogada em vez de excluir — '
                           'o histórico de verificações é evidência de auditoria.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=['get', 'post'], url_path='extracao-ia')
    def extracao_ia(self, request, pk=None):
        """
        GET: a extração mais recente desta norma (ou null). POST: pede uma nova
        leitura do PDF anexado. Roda no Celery — um PDF longo leva minutos, mais
        que o timeout do gunicorn — e a tela acompanha pelo GET.
        """
        norma = self.get_object()
        if request.method == 'GET':
            ultima = norma.extracoes.first()
            return Response({
                'configurada': ia.configurada(),
                'extracao': ExtracaoIASerializer(ultima).data if ultima else None,
            })

        if not ia.configurada():
            return Response({'detail': 'A IA ainda não foi configurada no servidor.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not norma.arquivo or not norma.arquivo.name.lower().endswith('.pdf'):
            raise ValidationError({'detail': 'Anexe o PDF do documento à norma antes de pedir a leitura.'})
        em_andamento = norma.extracoes.filter(status='PROCESSANDO').first()
        if em_andamento:
            return Response(ExtracaoIASerializer(em_andamento).data, status=status.HTTP_202_ACCEPTED)

        extracao = ExtracaoIA.objects.create(norma=norma, criado_por=request.user, modelo=ia.modelo())
        transaction.on_commit(lambda: extrair_requisitos.delay(extracao.id))
        return Response(ExtracaoIASerializer(extracao).data, status=status.HTTP_202_ACCEPTED)


class RequisitoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsConformidade]
    serializer_class = RequisitoSerializer

    def get_queryset(self):
        qs = (Requisito.objects
              .select_related('norma', 'responsavel')
              .annotate(planos_abertos=Count('planos', filter=Q(planos__concluido_em__isnull=True)
                                             & (Q(planos__tarefa__isnull=True) | Q(planos__tarefa__concluido_em__isnull=True)))))
        p = self.request.query_params
        if p.get('ativo', '1') != 'todos':
            qs = qs.filter(ativo=True)
        for campo in ('norma', 'tema', 'aplicabilidade', 'situacao', 'responsavel', 'origem'):
            if p.get(campo):
                qs = qs.filter(**{campo: p[campo]})
        if p.get('vencidos') == '1':
            qs = qs.filter(aplicabilidade='APLICAVEL', proxima_verificacao__lt=date.today())
        if p.get('q'):
            termo = p['q'].strip()
            qs = qs.filter(Q(descricao__icontains=termo) | Q(referencia__icontains=termo)
                           | Q(norma__ementa__icontains=termo) | Q(norma__numero__icontains=termo)
                           | Q(unidade__icontains=termo))
        return qs.order_by('norma__tema', 'norma_id', 'id')

    def perform_create(self, serializer):
        req = serializer.save(criado_por=self.request.user)
        # Sem verificação ainda, o primeiro vencimento é o prazo legal (se houver).
        if req.prazo_legal and not req.proxima_verificacao:
            req.recalcular_situacao()

    def perform_update(self, serializer):
        req = serializer.save()
        # Periodicidade ou prazo legal mudaram: a próxima data precisa acompanhar.
        if {'periodicidade_meses', 'prazo_legal'} & set(serializer.validated_data):
            req.recalcular_situacao()

    @action(detail=False, methods=['get'])
    def resumo(self, request):
        """Números do painel. Só requisitos ativos; situação conta só os aplicáveis."""
        hoje = date.today()
        ativos = Requisito.objects.filter(ativo=True)
        aplicaveis = ativos.filter(aplicabilidade='APLICAVEL')

        por_situacao = dict(aplicaveis.values_list('situacao').annotate(n=Count('id')))
        avaliados = sum(por_situacao.get(s, 0) for s in ('ATENDIDO', 'PARCIAL', 'NAO_ATENDIDO'))
        rotulos_tema = dict(TEMAS)
        por_tema = []
        for linha in (aplicaveis.values('tema')
                      .annotate(total=Count('id'),
                                atendidos=Count('id', filter=Q(situacao='ATENDIDO')),
                                nao_atendidos=Count('id', filter=Q(situacao='NAO_ATENDIDO')),
                                parciais=Count('id', filter=Q(situacao='PARCIAL')),
                                nao_avaliados=Count('id', filter=Q(situacao='NAO_AVALIADO')))
                      .order_by('-total')):
            linha['rotulo'] = rotulos_tema.get(linha['tema'], linha['tema'])
            por_tema.append(linha)

        planos = PlanoAcao.objects.filter(PLANO_ABERTO)

        validades = (Norma.objects
                     .filter(tipo__in=TIPOS_COM_VALIDADE, validade__isnull=False,
                             validade__lte=hoje + timedelta(days=180))
                     .exclude(situacao='REVOGADA')
                     .order_by('validade'))

        proximas = (aplicaveis.filter(proxima_verificacao__isnull=False,
                                      proxima_verificacao__lte=hoje + timedelta(days=30))
                    .select_related('norma', 'responsavel').order_by('proxima_verificacao')[:12])

        return Response({
            'total': ativos.count(),
            'aplicaveis': aplicaveis.count(),
            'em_analise': ativos.filter(aplicabilidade='EM_ANALISE').count(),
            'nao_aplicaveis': ativos.filter(aplicabilidade='NAO_APLICAVEL').count(),
            'por_situacao': {s: por_situacao.get(s, 0) for s, _ in Requisito.SITUACOES},
            # Parcial conta meio: atendeu a parte, mas o auditor vai apontar o resto.
            'indice_conformidade': round(
                100 * (por_situacao.get('ATENDIDO', 0) + 0.5 * por_situacao.get('PARCIAL', 0)) / avaliados, 1
            ) if avaliados else None,
            'verificacoes_vencidas': aplicaveis.filter(proxima_verificacao__lt=hoje).count(),
            'verificacoes_30_dias': aplicaveis.filter(proxima_verificacao__gte=hoje,
                                                      proxima_verificacao__lte=hoje + timedelta(days=30)).count(),
            'planos_abertos': planos.count(),
            'planos_atrasados': planos.filter(prazo__lt=hoje).count(),
            'por_tema': por_tema,
            'validades': [
                {'id': n.id, 'identificacao': n.identificacao, 'ementa': n.ementa, 'validade': n.validade,
                 'dias': (n.validade - hoje).days}
                for n in validades
            ],
            'proximas': RequisitoSerializer(proximas, many=True, context={'request': request}).data,
        })

    @action(detail=True, methods=['post'])
    def verificar(self, request, pk=None):
        """
        Registra uma VCL. Multipart: resultado, data, evidencia, observacao,
        arquivos (vários). Se vier `plano_descricao`, já abre o plano de ação —
        e, com `coluna_id`, a tarefa no Kanban.
        """
        req = self.get_object()
        if req.aplicabilidade != 'APLICAVEL':
            raise ValidationError({'detail': 'Só requisitos aplicáveis são verificados. Defina a aplicabilidade antes.'})
        d = request.data
        resultado = d.get('resultado')
        if resultado not in RESULTADOS_VALIDOS:
            raise ValidationError({'resultado': 'Informe Atendido, Parcial ou Não atendido.'})
        data_vcl = _data(d.get('data'), 'data') or date.today()
        if data_vcl > date.today():
            raise ValidationError({'data': 'A verificação não pode ter data futura.'})
        arquivos = request.FILES.getlist('arquivos')
        if resultado != 'ATENDIDO' and not (d.get('plano_descricao') or '').strip() \
                and not req.planos.filter(PLANO_ABERTO).exists():
            # Sem plano, o "não atendido" fica parado sem dono — é o que a ISO cobra.
            raise ValidationError({'plano_descricao': 'Descreva o plano de ação para o que não foi atendido.'})

        with transaction.atomic():
            vcl = Verificacao.objects.create(
                requisito=req, data=data_vcl, resultado=resultado,
                evidencia=d.get('evidencia', '') or '', observacao=d.get('observacao', '') or '',
                verificado_por=request.user,
            )
            for f in arquivos:
                EvidenciaAnexo.objects.create(verificacao=vcl, arquivo=f, nome=f.name)
            req.recalcular_situacao()

            plano = None
            if (d.get('plano_descricao') or '').strip():
                plano = PlanoAcao.objects.create(
                    requisito=req, verificacao=vcl, descricao=d['plano_descricao'].strip(),
                    responsavel=_usuario(d.get('plano_responsavel'), 'plano_responsavel') or req.responsavel,
                    prazo=_data(d.get('plano_prazo'), 'plano_prazo'), criado_por=request.user,
                )
                if d.get('coluna_id'):
                    _criar_tarefa_kanban(plano, d['coluna_id'], request.user)

        req.refresh_from_db()
        ctx = {'request': request}
        return Response({
            'requisito': RequisitoSerializer(self.get_queryset().get(pk=req.pk), context=ctx).data,
            'verificacao': VerificacaoSerializer(vcl, context=ctx).data,
            'plano': PlanoAcaoSerializer(plano, context=ctx).data if plano else None,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='criar-lote')
    def criar_lote(self, request):
        """
        Cria vários requisitos de uma norma de uma vez (a tela de revisão da
        extração por IA manda os itens aprovados). ``{"norma": id, "itens": [...]}``.
        """
        norma_id = request.data.get('norma')
        itens = request.data.get('itens') or []
        if not isinstance(itens, list) or not itens:
            raise ValidationError({'itens': 'Nenhum requisito recebido.'})
        criados = []
        with transaction.atomic():
            for item in itens:
                s = RequisitoSerializer(data={**item, 'norma': norma_id}, context={'request': request})
                s.is_valid(raise_exception=True)
                req = s.save(criado_por=request.user)
                if req.prazo_legal:
                    req.recalcular_situacao()
                criados.append(req.pk)
        return Response(RequisitoSerializer(self.get_queryset().filter(pk__in=criados), many=True,
                                            context={'request': request}).data, status=status.HTTP_201_CREATED)


class VerificacaoViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin,
                         viewsets.GenericViewSet):
    """Histórico. Criar é pelo `requisitos/{id}/verificar/`; editar não existe —
    VCL errada se apaga e registra de novo, para a trilha ficar honesta."""

    permission_classes = [IsConformidade]
    serializer_class = VerificacaoSerializer

    def get_queryset(self):
        qs = Verificacao.objects.select_related('verificado_por').prefetch_related('anexos')
        if self.request.query_params.get('requisito'):
            qs = qs.filter(requisito=self.request.query_params['requisito'])
        return qs

    def perform_destroy(self, instance):
        req = instance.requisito
        for anexo in instance.anexos.all():
            anexo.arquivo.delete(save=False)
        instance.delete()
        req.recalcular_situacao()


class PlanoAcaoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsConformidade]
    serializer_class = PlanoAcaoSerializer

    def get_queryset(self):
        qs = PlanoAcao.objects.select_related(
            'requisito__norma', 'responsavel', 'tarefa__coluna__quadro')
        p = self.request.query_params
        if p.get('requisito'):
            qs = qs.filter(requisito=p['requisito'])
        if p.get('abertos') == '1':
            qs = qs.filter(PLANO_ABERTO)
        return qs

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    @action(detail=True, methods=['post'], url_path='gerar-tarefa')
    def gerar_tarefa(self, request, pk=None):
        plano = self.get_object()
        if plano.tarefa_id:
            raise ValidationError({'detail': 'Este plano já tem tarefa no Kanban.'})
        _criar_tarefa_kanban(plano, request.data.get('coluna_id'), request.user)
        return Response(self.get_serializer(self.get_queryset().get(pk=plano.pk)).data)

    @action(detail=True, methods=['post'])
    def concluir(self, request, pk=None):
        plano = self.get_object()
        plano.concluido_em = None if request.data.get('reabrir') else timezone.now()
        plano.save(update_fields=['concluido_em'])
        return Response(self.get_serializer(plano).data)

