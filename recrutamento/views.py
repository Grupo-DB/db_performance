from collections import Counter, OrderedDict
from datetime import date, timedelta
from statistics import median

from django.db.models import Count, ProtectedError, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from .models import AreaInteresse, Candidato, Processo, Vaga
from .permissions import IsRH
from .serializers import (
    AreaInteresseSerializer,
    CandidatoListSerializer,
    CandidatoSerializer,
    ProcessoSerializer,
    VagaSerializer,
)


def _media(valores):
    valores = [v for v in valores if v is not None]
    return round(sum(valores) / len(valores), 1) if valores else None


def _mediana(valores):
    valores = [v for v in valores if v is not None]
    return round(median(valores), 1) if valores else None


def _competencia(d):
    """Chave 'AAAA-MM' usada nas séries mensais."""
    return f'{d.year:04d}-{d.month:02d}' if d else None


class ProtegeExclusaoMixin:
    """
    Transforma o ``ProtectedError`` do Django em 409 com mensagem legível.

    Sem isto o DRF deixa a exceção subir e a tela recebe um 500 genérico ao
    tentar apagar, por exemplo, um candidato que já participou de um processo.
    """

    mensagem_protegido = 'Registro em uso e não pode ser excluído.'

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response({'detail': self.mensagem_protegido}, status=status.HTTP_409_CONFLICT)


class AreaInteresseViewSet(ProtegeExclusaoMixin, viewsets.ModelViewSet):
    serializer_class = AreaInteresseSerializer
    permission_classes = [IsRH]

    def get_queryset(self):
        return AreaInteresse.objects.annotate(total_candidatos=Count('candidatos', distinct=True))


class CandidatoViewSet(ProtegeExclusaoMixin, viewsets.ModelViewSet):
    permission_classes = [IsRH]
    mensagem_protegido = (
        'Este candidato já participou de um processo seletivo e não pode ser excluído. '
        'Desmarque "ativo" para arquivá-lo sem perder o histórico.'
    )
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['sexo', 'escolaridade', 'cidade', 'pcd', 'ja_trabalhou_db', 'ativo', 'areas_interesse']
    search_fields = ['nome', 'funcao_desejada', 'cidade', 'observacoes', 'cpf', 'telefone_principal',
                     'ultima_empresa', 'ultima_empresa_funcao', 'pasta_arquivo']
    ordering_fields = ['nome', 'data_recebimento', 'cidade', 'escolaridade', 'created_at']

    def get_queryset(self):
        qs = Candidato.objects.prefetch_related('areas_interesse', 'processos__vaga')
        if self.action == 'list':
            qs = qs.annotate(total_processos=Count('processos', distinct=True))
        return qs

    def get_serializer_class(self):
        return CandidatoListSerializer if self.action == 'list' else CandidatoSerializer

    @action(detail=False, methods=['get'])
    def duplicados(self, request):
        """
        Nomes que aparecem em mais de um currículo.

        A planilha acumulou 119 nomes repetidos porque não havia checagem no
        cadastro; a tela usa isto para oferecer a mesclagem manual.
        """
        nomes = (
            Candidato.objects.values('nome')
            .annotate(total=Count('id'))
            .filter(total__gt=1)
            .order_by('-total', 'nome')
        )
        alvo = [n['nome'] for n in nomes]
        registros = Candidato.objects.filter(nome__in=alvo).values(
            'id', 'id_legado', 'nome', 'cidade', 'telefone_principal', 'data_recebimento', 'ano_nascimento',
        )
        agrupado = OrderedDict()
        for reg in registros:
            agrupado.setdefault(reg['nome'], []).append(reg)
        return Response([
            {'nome': nome, 'total': len(itens), 'candidatos': itens}
            for nome, itens in sorted(agrupado.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ])

    @action(detail=False, methods=['get'])
    def opcoes(self, request):
        """Valores distintos já usados no acervo, para alimentar autocompletes."""
        def distintos(campo):
            # order_by() limpa o ordering do Meta -- sem isso o Django inclui
            # "nome" no SELECT e o DISTINCT deixa de agrupar os valores iguais.
            return sorted(
                v for v in Candidato.objects.exclude(**{f'{campo}__exact': ''})
                .order_by().values_list(campo, flat=True).distinct() if v
            )

        return Response({
            'cidades': distintos('cidade'),
            'funcoes_desejadas': distintos('funcao_desejada'),
            'pastas_arquivo': distintos('pasta_arquivo'),
            'escolaridades': [c[0] for c in Candidato.ESCOLARIDADE_CHOICES],
            'estados_civis': [c[0] for c in Candidato.ESTADO_CIVIL_CHOICES],
            'turnos': [c[0] for c in Candidato.TURNO_CHOICES],
            'niveis': [c[0] for c in Candidato.NIVEL_CHOICES],
        })


class VagaViewSet(ProtegeExclusaoMixin, viewsets.ModelViewSet):
    serializer_class = VagaSerializer
    permission_classes = [IsRH]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'tipo', 'requisitante', 'area']
    search_fields = ['descricao', 'requisitante', 'observacoes']
    ordering_fields = ['data_abertura', 'prazo_encerramento', 'descricao', 'status']

    def get_queryset(self):
        return Vaga.objects.select_related('area').annotate(
            total_candidatos=Count('processos', distinct=True),
            total_entrevistados=Count('processos', filter=Q(processos__compareceu=True), distinct=True),
            total_contratados=Count('processos', filter=Q(processos__contratado=True), distinct=True),
        )

    @action(detail=False, methods=['get'])
    def requisitantes(self, request):
        return Response(sorted(
            v for v in Vaga.objects.exclude(requisitante__exact='')
            .order_by().values_list('requisitante', flat=True).distinct() if v
        ))

    @action(detail=True, methods=['get'])
    def funil(self, request, pk=None):
        """Candidatos de uma vaga agrupados por etapa -- é a antiga aba Seleção."""
        vaga = self.get_object()
        processos = (
            Processo.objects.filter(vaga=vaga)
            .select_related('candidato')
            .order_by('-contratado', 'candidato__nome')
        )
        return Response({
            'vaga': VagaSerializer(self.get_queryset().get(pk=vaga.pk)).data,
            'processos': ProcessoSerializer(processos, many=True).data,
        })


class ProcessoViewSet(ProtegeExclusaoMixin, viewsets.ModelViewSet):
    serializer_class = ProcessoSerializer
    permission_classes = [IsRH]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['vaga', 'candidato', 'parecer', 'etapa', 'contratado', 'compareceu',
                        'contato_com_sucesso', 'responsavel_contato', 'ex_funcionario']
    search_fields = ['candidato__nome', 'vaga__descricao', 'responsavel_contato',
                     'observacao_requisitante', 'observacao_candidato']
    ordering_fields = ['data_contato', 'data_entrevista', 'data_contratacao', 'created_at']

    def get_queryset(self):
        return Processo.objects.select_related('candidato', 'vaga')

    @action(detail=False, methods=['get'])
    def responsaveis(self, request):
        return Response(sorted(
            v for v in Processo.objects.exclude(responsavel_contato__exact='')
            .order_by().values_list('responsavel_contato', flat=True).distinct() if v
        ))


class IndicadoresViewSet(viewsets.ViewSet):
    """
    Indicadores do RH -- substitui a aba ``Indicadores`` (que era só tabela
    dinâmica) e os cartões do Menu da planilha.

    Aceita ``?inicio=AAAA-MM-DD&fim=AAAA-MM-DD`` para recortar o período; sem
    parâmetros usa os últimos 12 meses.
    """

    permission_classes = [IsRH]

    def _periodo(self, request):
        hoje = date.today()
        inicio = request.query_params.get('inicio')
        fim = request.query_params.get('fim')
        try:
            inicio = date.fromisoformat(inicio) if inicio else hoje - timedelta(days=365)
        except ValueError:
            inicio = hoje - timedelta(days=365)
        try:
            fim = date.fromisoformat(fim) if fim else hoje
        except ValueError:
            fim = hoje
        return inicio, fim

    def list(self, request):
        inicio, fim = self._periodo(request)

        vagas = Vaga.objects.filter(data_abertura__range=(inicio, fim))
        processos = list(
            Processo.objects.filter(
                Q(data_contato__range=(inicio, fim)) | Q(data_entrevista__range=(inicio, fim))
            ).select_related('candidato', 'vaga')
        )

        # --- vagas ---
        por_status = Counter(v.status for v in vagas)
        tempos_fechamento = [
            v.tempo_retorno for v in vagas
            if v.status == Vaga.STATUS_CONCLUIDA and v.tempo_retorno is not None
        ]

        # --- funil ---
        contatados = [p for p in processos if p.data_contato]
        com_sucesso = [p for p in contatados if p.contato_com_sucesso]
        entrevistas_agendadas = [p for p in processos if p.data_entrevista]
        compareceram = [p for p in entrevistas_agendadas if p.compareceu]
        com_parecer = [p for p in processos if p.parecer]
        contratados = [p for p in processos if p.contratado]

        # --- tempos ---
        t_cv_entrevista = [p.tempo_para_entrevista for p in entrevistas_agendadas]
        t_retorno_cand = [p.tempo_retorno_candidato for p in processos]

        # --- séries mensais ---
        meses = OrderedDict()
        cursor = date(inicio.year, inicio.month, 1)
        limite = date(fim.year, fim.month, 1)
        while cursor <= limite:
            meses[_competencia(cursor)] = {
                'competencia': _competencia(cursor),
                'vagas_abertas': 0, 'entrevistas': 0, 'contratacoes': 0,
            }
            cursor = date(cursor.year + (cursor.month == 12), (cursor.month % 12) + 1, 1)

        for v in vagas:
            chave = _competencia(v.data_abertura)
            if chave in meses:
                meses[chave]['vagas_abertas'] += 1
        for p in processos:
            chave = _competencia(p.data_entrevista)
            if chave in meses:
                meses[chave]['entrevistas'] += 1
            chave = _competencia(p.data_contratacao)
            if chave in meses:
                meses[chave]['contratacoes'] += 1

        def taxa(parte, todo):
            return round(100 * len(parte) / len(todo), 1) if todo else None

        return Response({
            'periodo': {'inicio': inicio, 'fim': fim},
            'vagas': {
                'total': vagas.count(),
                'abertas': por_status.get(Vaga.STATUS_ABERTA, 0),
                'stand_by': por_status.get(Vaga.STATUS_STAND_BY, 0),
                'concluidas': por_status.get(Vaga.STATUS_CONCLUIDA, 0),
                'canceladas': por_status.get(Vaga.STATUS_CANCELADA, 0),
                'atrasadas': sum(1 for v in vagas if v.atrasada),
                'tempo_medio_fechamento': _media(tempos_fechamento),
                'tempo_mediano_fechamento': _mediana(tempos_fechamento),
            },
            'funil': [
                {'etapa': 'Contatados', 'total': len(contatados)},
                {'etapa': 'Contato com sucesso', 'total': len(com_sucesso)},
                {'etapa': 'Entrevistas agendadas', 'total': len(entrevistas_agendadas)},
                {'etapa': 'Compareceram', 'total': len(compareceram)},
                {'etapa': 'Com parecer', 'total': len(com_parecer)},
                {'etapa': 'Contratados', 'total': len(contratados)},
            ],
            'taxas': {
                'contato_sucesso': taxa(com_sucesso, contatados),
                'comparecimento': taxa(compareceram, entrevistas_agendadas),
                'contratacao': taxa(contratados, compareceram),
            },
            'tempos': {
                'cv_ate_entrevista_medio': _media(t_cv_entrevista),
                'cv_ate_entrevista_mediano': _mediana(t_cv_entrevista),
                'entrevista_ate_retorno_medio': _media(t_retorno_cand),
                'entrevista_ate_retorno_mediano': _mediana(t_retorno_cand),
            },
            'pareceres': [
                {'parecer': rotulo, 'total': sum(1 for p in processos if p.parecer == chave)}
                for chave, rotulo in Processo.PARECER_CHOICES
            ],
            'por_responsavel': [
                {'responsavel': nome, 'total': total}
                for nome, total in Counter(
                    p.responsavel_contato for p in processos if p.responsavel_contato
                ).most_common()
            ],
            'por_requisitante': [
                {'requisitante': nome, 'total': total}
                for nome, total in Counter(
                    v.requisitante for v in vagas if v.requisitante
                ).most_common(15)
            ],
            'serie_mensal': list(meses.values()),
            'banco_talentos': {
                'total_curriculos': Candidato.objects.count(),
                'ativos': Candidato.objects.filter(ativo=True).count(),
                'recebidos_no_periodo': Candidato.objects.filter(
                    data_recebimento__range=(inicio, fim)
                ).count(),
                'nunca_contatados': Candidato.objects.filter(processos__isnull=True).count(),
                'pcd': Candidato.objects.filter(pcd=True).count(),
            },
        })
