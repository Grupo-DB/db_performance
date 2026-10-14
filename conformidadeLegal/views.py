from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from kanban.models import KanbanColumn, KanbanTask

from . import ia
from .models import (
    TEMAS, ConfiguracaoMonitor, EvidenciaAnexo, ExecucaoMonitor, ExtracaoIA, Norma, OrgaoMonitor, PalavraChaveMonitor,
    PlanoAcao, PublicacaoMonitorada, Requisito, Verificacao,
)
from .permissions import IsConformidade
from .serializers import nome_usuario
from .serializers import (
    ConfiguracaoMonitorSerializer, ExecucaoMonitorSerializer, ExtracaoIASerializer, NormaSerializer,
    OrgaoMonitorSerializer, PalavraChaveSerializer, PlanoAcaoSerializer, PublicacaoDetalheSerializer,
    PublicacaoSerializer, RequisitoSerializer, VerificacaoSerializer,
)
from .tasks import extrair_requisitos, monitorar_diarios

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
                'total_paginas': _total_paginas(norma),
            })

        if not ia.configurada():
            return Response({'detail': 'A IA ainda não foi configurada no servidor.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not norma.arquivo or not norma.arquivo.name.lower().endswith('.pdf'):
            raise ValidationError({'detail': 'Anexe o PDF do documento à norma antes de pedir a leitura.'})
        em_andamento = norma.extracoes.filter(status='PROCESSANDO').first()
        if em_andamento:
            return Response(ExtracaoIASerializer(em_andamento).data, status=status.HTTP_202_ACCEPTED)

        # Páginas opcionais ("20-21, 24-35"): validadas aqui para o erro voltar na hora,
        # e não minutos depois como extração com status ERRO.
        texto_paginas = (request.data.get('paginas') or '').strip()
        paginas = ''
        if texto_paginas:
            total = _total_paginas(norma)
            if not total:
                raise ValidationError({'paginas': 'Não foi possível contar as páginas deste PDF.'})
            try:
                paginas = ia.descrever_paginas(ia.interpretar_paginas(texto_paginas, total))
            except ia.PaginasInvalidas as e:
                raise ValidationError({'paginas': str(e)})

        extracao = ExtracaoIA.objects.create(norma=norma, criado_por=request.user, modelo=ia.modelo(),
                                             paginas=paginas)
        transaction.on_commit(lambda: extrair_requisitos.delay(extracao.id))
        return Response(ExtracaoIASerializer(extracao).data, status=status.HTTP_202_ACCEPTED)


LIMITE_LOTE = 500
# O que a edição em lote pode mudar. Norma, descrição e referência são de cada requisito.
CAMPOS_LOTE = ('aplicabilidade', 'justificativa', 'unidade', 'responsavel', 'periodicidade_meses', 'tema', 'ativo')


def _validar_vcl(d):
    resultado = d.get('resultado')
    if resultado not in RESULTADOS_VALIDOS:
        raise ValidationError({'resultado': 'Informe Atendido, Parcial ou Não atendido.'})
    data_vcl = _data(d.get('data'), 'data') or date.today()
    if data_vcl > date.today():
        raise ValidationError({'data': 'A verificação não pode ter data futura.'})
    return resultado, data_vcl


def _registrar_vcl(req, d, resultado, data_vcl, usuario, anexos):
    """
    Cria a VCL, liga os anexos e recalcula a situação. `anexos` são uploads (gravados
    agora) ou EvidenciaAnexo já gravados — no lote, o arquivo vai para o disco uma vez
    só e as outras verificações apontam para o mesmo caminho. Devolve (vcl, anexos
    gravados), para o próximo requisito do lote reaproveitar.
    """
    vcl = Verificacao.objects.create(
        requisito=req, data=data_vcl, resultado=resultado,
        evidencia=d.get('evidencia', '') or '', observacao=d.get('observacao', '') or '',
        verificado_por=usuario,
    )
    gravados = []
    for a in anexos:
        if isinstance(a, EvidenciaAnexo):
            gravados.append(EvidenciaAnexo.objects.create(verificacao=vcl, arquivo=a.arquivo.name, nome=a.nome,
                                                          tamanho=a.tamanho))
        else:
            gravados.append(EvidenciaAnexo.objects.create(verificacao=vcl, arquivo=a, nome=a.name))
    req.recalcular_situacao()
    return vcl, gravados


def _abrir_plano(req, vcl, d, usuario):
    return PlanoAcao.objects.create(
        requisito=req, verificacao=vcl, descricao=d['plano_descricao'].strip(),
        responsavel=_usuario(d.get('plano_responsavel'), 'plano_responsavel') or req.responsavel,
        prazo=_data(d.get('plano_prazo'), 'plano_prazo'), criado_por=usuario,
    )


def _total_paginas(norma) -> int | None:
    """Páginas do PDF da norma; None quando não há PDF ou ele não abre."""
    if not norma.arquivo or not norma.arquivo.name.lower().endswith('.pdf'):
        return None
    try:
        with norma.arquivo.open('rb') as f:
            return ia.contar_paginas(f.read())
    except Exception:  # noqa: BLE001 — PDF corrompido não pode derrubar a tela
        return None


class RequisitoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsConformidade]
    serializer_class = RequisitoSerializer

    def get_queryset(self):
        qs = (Requisito.objects
              .select_related('norma', 'responsavel__colaborador')
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
                    .select_related('norma', 'responsavel__colaborador').order_by('proxima_verificacao')[:12])

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
        resultado, data_vcl = _validar_vcl(d)
        if resultado != 'ATENDIDO' and not (d.get('plano_descricao') or '').strip() \
                and not req.planos.filter(PLANO_ABERTO).exists():
            # Sem plano, o "não atendido" fica parado sem dono — é o que a ISO cobra.
            raise ValidationError({'plano_descricao': 'Descreva o plano de ação para o que não foi atendido.'})

        with transaction.atomic():
            vcl, _ = _registrar_vcl(req, d, resultado, data_vcl, request.user, request.FILES.getlist('arquivos'))
            plano = None
            if (d.get('plano_descricao') or '').strip():
                plano = _abrir_plano(req, vcl, d, request.user)
                if d.get('coluna_id'):
                    _criar_tarefa_kanban(plano, d['coluna_id'], request.user)

        req.refresh_from_db()
        ctx = {'request': request}
        return Response({
            'requisito': RequisitoSerializer(self.get_queryset().get(pk=req.pk), context=ctx).data,
            'verificacao': VerificacaoSerializer(vcl, context=ctx).data,
            'plano': PlanoAcaoSerializer(plano, context=ctx).data if plano else None,
        }, status=status.HTTP_201_CREATED)

    def _requisitos_do_lote(self, valor) -> list:
        """`ids` em lista JSON, repetido no multipart ou "1,2,3" → os requisitos, todos existentes."""
        if hasattr(self.request.data, 'getlist') and len(self.request.data.getlist('ids')) > 1:
            valor = self.request.data.getlist('ids')
        if isinstance(valor, str):
            valor = valor.split(',')
        try:
            ids = {int(i) for i in (valor or []) if str(i).strip()}
        except (TypeError, ValueError):
            raise ValidationError({'ids': 'Lista de requisitos inválida.'})
        if not ids:
            raise ValidationError({'ids': 'Nenhum requisito selecionado.'})
        if len(ids) > LIMITE_LOTE:
            raise ValidationError({'ids': f'No máximo {LIMITE_LOTE} requisitos por vez.'})
        reqs = list(Requisito.objects.filter(pk__in=ids).order_by('id'))
        if len(reqs) != len(ids):
            raise ValidationError({'ids': 'Algum requisito selecionado não existe mais. Recarregue a lista.'})
        return reqs

    @action(detail=False, methods=['post'], url_path='editar-lote')
    def editar_lote(self, request):
        """
        Aplica os mesmos campos a vários requisitos: ``{"ids": [...], "campos": {...}}``.
        Só os campos enviados mudam — é a triagem das sugestões da IA ("estes 15 não se
        aplicam") sem abrir um por um. Tudo ou nada: um inválido desfaz o lote.
        """
        reqs = self._requisitos_do_lote(request.data.get('ids'))
        campos = {k: v for k, v in (request.data.get('campos') or {}).items() if k in CAMPOS_LOTE}
        if not campos:
            raise ValidationError({'campos': 'Nada para alterar.'})
        ctx = {'request': request}
        with transaction.atomic():
            for req in reqs:
                s = RequisitoSerializer(req, data=campos, partial=True, context=ctx)
                s.is_valid(raise_exception=True)
                req = s.save()
                if 'periodicidade_meses' in s.validated_data:
                    req.recalcular_situacao()
        return Response(RequisitoSerializer(self.get_queryset().filter(pk__in=[r.pk for r in reqs]),
                                            many=True, context=ctx).data)

    @action(detail=False, methods=['post'], url_path='verificar-lote')
    def verificar_lote(self, request):
        """
        Mesma VCL para vários requisitos — o caso do laudo único que comprova vários
        itens. Multipart como em `verificar`, mais `ids`. Os anexos são gravados UMA vez
        e ligados a todas as verificações. Fora de "Atendido", requisito sem plano aberto
        ganha um plano com a descrição informada (a tarefa no Kanban, se quiser, sai
        depois pela tela de planos — uma por plano).
        """
        reqs = self._requisitos_do_lote(request.data.get('ids'))
        fora = [r for r in reqs if r.aplicabilidade != 'APLICAVEL']
        if fora:
            raise ValidationError({'ids': f'{len(fora)} dos selecionados não estão como "Aplicável". '
                                          'Só requisitos aplicáveis são verificados.'})
        d = request.data
        resultado, data_vcl = _validar_vcl(d)
        descricao_plano = (d.get('plano_descricao') or '').strip()
        com_plano = set(Requisito.objects.filter(pk__in=[r.pk for r in reqs], planos__in=PlanoAcao.objects.filter(PLANO_ABERTO))
                        .values_list('pk', flat=True))
        if resultado != 'ATENDIDO' and not descricao_plano and any(r.pk not in com_plano for r in reqs):
            raise ValidationError({'plano_descricao': 'Descreva o plano de ação para o que não foi atendido.'})

        planos = 0
        with transaction.atomic():
            anexos = request.FILES.getlist('arquivos')
            for req in reqs:
                vcl, anexos = _registrar_vcl(req, d, resultado, data_vcl, request.user, anexos)
                if resultado != 'ATENDIDO' and descricao_plano and req.pk not in com_plano:
                    _abrir_plano(req, vcl, d, request.user)
                    planos += 1

        return Response({
            'requisitos': RequisitoSerializer(self.get_queryset().filter(pk__in=[r.pk for r in reqs]), many=True,
                                              context={'request': request}).data,
            'verificacoes': len(reqs),
            'planos': planos,
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
        qs = Verificacao.objects.select_related('verificado_por__colaborador').prefetch_related('anexos')
        if self.request.query_params.get('requisito'):
            qs = qs.filter(requisito=self.request.query_params['requisito'])
        return qs

    def perform_destroy(self, instance):
        req = instance.requisito
        anexos = list(instance.anexos.all())
        instance.delete()
        # A verificação em lote liga o MESMO arquivo a várias verificações: só sai do
        # disco quando a última que aponta para ele for embora.
        for anexo in anexos:
            if not EvidenciaAnexo.objects.filter(arquivo=anexo.arquivo.name).exists():
                anexo.arquivo.delete(save=False)
        req.recalcular_situacao()


class PlanoAcaoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsConformidade]
    serializer_class = PlanoAcaoSerializer

    def get_queryset(self):
        qs = PlanoAcao.objects.select_related(
            'requisito__norma', 'responsavel__colaborador', 'tarefa__coluna__quadro')
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


class ResponsaveisView(APIView):
    """
    Pessoas que podem ser responsáveis por requisito ou plano: usuários ativos, com o
    nome do cadastro de colaboradores. Própria do módulo — a lista geral de usuários
    (management/get_users) é usada pelo Kanban e mostra o login.
    """

    permission_classes = [IsConformidade]

    def get(self, request):
        import unicodedata
        usuarios = User.objects.filter(is_active=True).select_related('colaborador')
        lista = [{'id': u.id, 'nome': nome_usuario(u), 'login': u.username} for u in usuarios]

        def chave(item):
            sem_acento = unicodedata.normalize('NFKD', item['nome']).encode('ascii', 'ignore').decode()
            return sem_acento.casefold()

        return Response(sorted(lista, key=chave))


class PublicacaoViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Novidades legais: o que a coleta dos diários oficiais achou. A equipe descarta ou
    cadastra como norma; nada é criado sem essa decisão.
    """

    permission_classes = [IsConformidade]

    def get_serializer_class(self):
        return PublicacaoDetalheSerializer if self.action == 'retrieve' else PublicacaoSerializer

    def get_queryset(self):
        qs = PublicacaoMonitorada.objects.select_related('norma', 'avaliado_por__colaborador')
        p = self.request.query_params
        for campo in ('status', 'relevancia', 'fonte'):
            if p.get(campo):
                qs = qs.filter(**{campo: p[campo]})
        if p.get('dias'):
            try:
                qs = qs.filter(data_publicacao__gte=date.today() - timedelta(days=int(p['dias'])))
            except ValueError:
                pass
        return qs

    def _avaliar(self, pub, status_novo, request, **extra):
        pub.status = status_novo
        pub.avaliado_por = request.user if status_novo != 'NOVA' else None
        pub.avaliado_em = timezone.now() if status_novo != 'NOVA' else None
        for k, v in extra.items():
            setattr(pub, k, v)
        pub.save()
        return Response(PublicacaoSerializer(pub, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def descartar(self, request, pk=None):
        return self._avaliar(self.get_object(), 'DESCARTADA', request,
                             motivo_descarte=(request.data.get('motivo') or '').strip()[:2000])

    @action(detail=True, methods=['post'])
    def reabrir(self, request, pk=None):
        pub = self.get_object()
        if pub.status == 'CADASTRADA':
            raise ValidationError({'detail': 'Já virou norma. Para desfazer, exclua ou revogue a norma.'})
        return self._avaliar(pub, 'NOVA', request, motivo_descarte='')

    @action(detail=True, methods=['post'], url_path='cadastrar-norma')
    def cadastrar_norma(self, request, pk=None):
        """
        Cria a norma a partir da publicação: tipo, número, ano e órgão tirados do
        título, link oficial e um PDF com o texto publicado — pronto para a leitura
        por IA. A tela abre a norma em seguida para a pessoa revisar.
        """
        from django.core.files.base import ContentFile
        from . import monitor

        pub = self.get_object()
        if pub.status == 'CADASTRADA' and pub.norma_id:
            raise ValidationError({'detail': 'Esta publicação já foi cadastrada como norma.'})
        with transaction.atomic():
            norma = Norma(**monitor.dados_de_norma(pub), criado_por=request.user)
            nome = f'{pub.fonte.lower()}_{pub.data_publicacao:%Y%m%d}_{pub.id_externo}.pdf'
            norma.arquivo.save(nome, ContentFile(monitor.pdf_da_publicacao(pub)), save=False)
            norma.save()
            self._avaliar(pub, 'CADASTRADA', request, norma=norma)
        return Response({
            'norma': NormaSerializer(norma, context={'request': request}).data,
            'publicacao': PublicacaoSerializer(pub, context={'request': request}).data,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def situacao(self, request):
        """Última coleta de cada fonte (é daqui que a tela avisa que uma fonte parou) e a fila."""
        fontes = []
        for fonte, rotulo in PublicacaoMonitorada.FONTES:
            ultimas = list(ExecucaoMonitor.objects.filter(fonte=fonte).order_by('-iniciado_em')[:10])
            if not ultimas:
                continue
            falhas = 0
            for e in ultimas:
                if e.ok:
                    break
                falhas += 1
            u = ultimas[0]
            fontes.append({
                'fonte': fonte, 'rotulo': rotulo, 'ok': u.ok, 'erro': u.erro, 'data_referencia': u.data_referencia,
                'concluido_em': u.concluido_em, 'falhas_seguidas': falhas,
                'ultima_ok': next((e.concluido_em for e in ultimas if e.ok), None),
            })
        return Response({
            'fontes': fontes,
            'para_avaliar': PublicacaoMonitorada.objects.filter(status='NOVA').count(),
            'relevantes': PublicacaoMonitorada.objects.filter(status='NOVA', relevancia__in=['ALTA', 'MEDIA']).count(),
        })

    @action(detail=False, methods=['post'])
    def coletar(self, request):
        """Roda a coleta agora (além dos horários agendados)."""
        monitorar_diarios.delay()
        return Response({'detail': 'Coleta iniciada. As novidades aparecem em alguns minutos.'},
                        status=status.HTTP_202_ACCEPTED)


# ── Configurações do monitor (tela "Configurações do monitor") ───────────
JANELA_ESTATISTICA = 90  # dias de publicações para as contagens da tela


def _publicacoes_recentes():
    desde = date.today() - timedelta(days=JANELA_ESTATISTICA)
    return list(PublicacaoMonitorada.objects.filter(criado_em__date__gte=desde).values('palavras', 'status', 'origem'))


class PalavraChaveViewSet(viewsets.ModelViewSet):
    """Palavras-chave do monitor. A lista traz quantas publicações cada uma trouxe nos
    últimos 90 dias e o que a equipe fez com elas — é o que mostra quem só traz ruído."""

    permission_classes = [IsConformidade]
    serializer_class = PalavraChaveSerializer
    queryset = PalavraChaveMonitor.objects.all()

    def list(self, request, *args, **kwargs):
        dados = self.get_serializer(self.get_queryset(), many=True).data
        pubs = _publicacoes_recentes()
        for d in dados:
            minhas = [p for p in pubs if d['rotulo'] in (p['palavras'] or [])]
            d['disparos'] = len(minhas)
            d['descartadas'] = sum(1 for p in minhas if p['status'] == 'DESCARTADA')
            d['viraram_norma'] = sum(1 for p in minhas if p['status'] == 'CADASTRADA')
        return Response(dados)


class OrgaoMonitorViewSet(viewsets.ModelViewSet):
    permission_classes = [IsConformidade]
    serializer_class = OrgaoMonitorSerializer
    queryset = OrgaoMonitor.objects.all()

    def list(self, request, *args, **kwargs):
        dados = self.get_serializer(self.get_queryset(), many=True).data
        pubs = _publicacoes_recentes()
        for d in dados:
            minhas = [p for p in pubs if p['origem'] == d['rotulo']]
            d['trazidas'] = len(minhas)
            d['descartadas'] = sum(1 for p in minhas if p['status'] == 'DESCARTADA')
            d['viraram_norma'] = sum(1 for p in minhas if p['status'] == 'CADASTRADA')
        return Response(dados)


class ConfiguracaoMonitorView(APIView):
    permission_classes = [IsConformidade]

    def get(self, request):
        cfg = ConfiguracaoMonitor.atual()
        dados = ConfiguracaoMonitorSerializer(cfg).data
        # O que vale hoje (o da tela ou, vazio, o do servidor) — para a tela mostrar de onde vem.
        dados['perfil_servidor'] = getattr(settings, 'CONFORMIDADE_IA_PERFIL_EMPRESA', '')
        return Response(dados)

    def patch(self, request):
        cfg = ConfiguracaoMonitor.atual()
        s = ConfiguracaoMonitorSerializer(cfg, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save(atualizado_por=request.user)
        return self.get(request)


class ExecucoesMonitorView(APIView):
    """As últimas coletas, de todas as fontes."""

    permission_classes = [IsConformidade]

    def get(self, request):
        qs = ExecucaoMonitor.objects.order_by('-iniciado_em')[:80]
        return Response(ExecucaoMonitorSerializer(qs, many=True).data)


class TestarPalavrasView(APIView):
    """Cola um trecho e vê quais palavras-chave ativas disparariam (nada é gravado)."""

    permission_classes = [IsConformidade]

    def post(self, request):
        from . import monitor
        texto = (request.data.get('texto') or '')[:50000]
        return Response({'palavras': monitor.palavras_encontradas(texto, monitor.carregar_palavras())})
