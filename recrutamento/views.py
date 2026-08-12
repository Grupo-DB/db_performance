from collections import Counter, OrderedDict
from datetime import date, timedelta
from statistics import median
from threading import Thread

from django.db.models import Count, ProtectedError, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from sqlalchemy.exc import SQLAlchemyError

from .models import (
    AreaInteresse,
    Candidato,
    FichaAnexo,
    FichaEntrevista,
    FolhaPonto,
    Processo,
    Vaga,
)
from .permissions import IsRH
from . import folha_ponto as fponto
from .turnover import apurar as apurar_turnover
from .serializers import (
    AreaInteresseSerializer,
    CandidatoListSerializer,
    CandidatoSerializer,
    FichaAnexoSerializer,
    FichaEntrevistaListSerializer,
    FichaEntrevistaSerializer,
    FolhaPontoSerializer,
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
        qs = Candidato.objects.prefetch_related('areas_interesse', 'processos__vaga', 'fichas__vaga')
        if self.action == 'list':
            qs = qs.annotate(
                total_processos=Count('processos', distinct=True),
                total_fichas=Count('fichas', distinct=True),
            )
        return qs

    def get_serializer_class(self):
        return CandidatoListSerializer if self.action == 'list' else CandidatoSerializer

    def destroy(self, request, *args, **kwargs):
        """
        Exclui o currículo. Com ``?cascata=1`` leva junto processos e fichas.

        Sem a cascata o ``PROTECT`` do ``Processo`` impede apagar quem já foi
        entrevistado -- o que é a proteção certa no dia a dia, mas deixava sem
        saída os registros trazidos da planilha (importações repetidas, nomes
        duplicados). A cascata é explícita justamente para não ser acidental.
        """
        if str(request.query_params.get('cascata', '')).lower() in ('1', 'true', 'sim'):
            candidato = self.get_object()
            FichaEntrevista.objects.filter(candidato=candidato).delete()
            Processo.objects.filter(candidato=candidato).delete()
            candidato.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post', 'delete'], url_path='anexo',
            parser_classes=[MultiPartParser, FormParser])
    def anexo(self, request, pk=None):
        """
        Anexa (POST, multipart, campo ``arquivo``) ou remove (DELETE) o arquivo
        do currículo.

        Endpoint separado do PUT do cadastro porque a tela salva o candidato em
        JSON: mandar arquivo no mesmo payload exigiria multipart em todo o
        formulário, e trocar o currículo não deveria depender de reenviar os 60
        campos do cadastro.
        """
        candidato = self.get_object()

        if request.method == 'DELETE':
            if candidato.anexo:
                # delete(save=True) já grava o campo vazio; apaga o arquivo do disco.
                candidato.anexo.delete(save=True)
            return Response(status=status.HTTP_204_NO_CONTENT)

        arquivo = request.FILES.get('arquivo') or request.FILES.get('anexo')
        if not arquivo:
            return Response({'detail': 'Envie o arquivo no campo "arquivo".'},
                            status=status.HTTP_400_BAD_REQUEST)
        if arquivo.size > 20 * 1024 * 1024:
            return Response({'detail': 'Arquivo maior que 20 MB.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Substituir sem apagar o anterior deixaria órfãos acumulando em
        # media/recrutamento/curriculos/ a cada troca.
        if candidato.anexo:
            candidato.anexo.delete(save=False)
        candidato.anexo = arquivo
        candidato.save(update_fields=['anexo', 'updated_at'])
        serializer = CandidatoSerializer(candidato, context=self.get_serializer_context())
        return Response(serializer.data)

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
        # ``fichas`` vem no prefetch para o ``ficha_id`` do serializer não gerar N+1.
        return Processo.objects.select_related('candidato', 'vaga').prefetch_related('fichas')

    @action(detail=False, methods=['get'])
    def responsaveis(self, request):
        return Response(sorted(
            v for v in Processo.objects.exclude(responsavel_contato__exact='')
            .order_by().values_list('responsavel_contato', flat=True).distinct() if v
        ))


class FichaEntrevistaViewSet(viewsets.ModelViewSet):
    """Fichas de entrevista F-018 (versão 7.1 do formulário impresso)."""

    permission_classes = [IsRH]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['candidato', 'processo', 'vaga', 'resultado', 'atende_requisitos',
                        'avaliador_1', 'setor']
    search_fields = ['candidato__nome', 'nome', 'cargo_funcao', 'setor', 'avaliador_1',
                     'parecer_recrutador', 'observacoes', 'vaga__descricao']
    ordering_fields = ['data_entrevista', 'created_at', 'resultado']

    def get_queryset(self):
        qs = FichaEntrevista.objects.select_related('candidato', 'vaga', 'processo')
        if self.action == 'list':
            # A listagem só mostra o contador; puxar os anexos inteiros seria N+1.
            qs = qs.annotate(total_anexos=Count('anexos'))
        else:
            qs = qs.prefetch_related('anexos')
        inicio = self.request.query_params.get('inicio')
        fim = self.request.query_params.get('fim')
        if inicio:
            qs = qs.filter(data_entrevista__gte=inicio)
        if fim:
            qs = qs.filter(data_entrevista__lte=fim)
        return qs

    def get_serializer_class(self):
        return FichaEntrevistaListSerializer if self.action == 'list' else FichaEntrevistaSerializer

    # Mesmo teto do currículo: o que passa disso costuma ser foto de documento
    # sem compressão, e o nginx da VM corta o upload antes de chegar no Django.
    TAMANHO_MAX_ANEXO = 20 * 1024 * 1024

    @action(detail=True, methods=['get', 'post'], url_path='anexos',
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def anexos(self, request, pk=None):
        """
        Lista (GET) ou anexa (POST, multipart, campo ``arquivo``) documentos da
        entrevista: teste aplicado, redação, cópia de documento.

        Endpoint separado do PUT da ficha porque a tela salva os ~70 campos em
        JSON — mandar arquivo no mesmo payload obrigaria o formulário inteiro a
        virar multipart.
        """
        ficha = self.get_object()

        if request.method == 'GET':
            serializer = FichaAnexoSerializer(
                ficha.anexos.all(), many=True, context=self.get_serializer_context()
            )
            return Response(serializer.data)

        arquivos = request.FILES.getlist('arquivo') or request.FILES.getlist('arquivos')
        if not arquivos:
            return Response({'detail': 'Envie o arquivo no campo "arquivo".'},
                            status=status.HTTP_400_BAD_REQUEST)

        grandes = [a.name for a in arquivos if a.size > self.TAMANHO_MAX_ANEXO]
        if grandes:
            return Response(
                {'detail': f'Arquivo maior que 20 MB: {", ".join(grandes)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        descricao = (request.data.get('descricao') or '').strip()
        enviado_por = (request.user.get_full_name() or request.user.username) if request.user.is_authenticated else ''
        criados = [
            FichaAnexo.objects.create(
                ficha=ficha, arquivo=arquivo, descricao=descricao, enviado_por=enviado_por,
            )
            for arquivo in arquivos
        ]
        serializer = FichaAnexoSerializer(criados, many=True, context=self.get_serializer_context())
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'], url_path=r'anexos/(?P<anexo_id>\d+)')
    def anexo(self, request, pk=None, anexo_id=None):
        """Renomeia a descrição (PATCH) ou remove (DELETE) um anexo da ficha."""
        ficha = self.get_object()
        try:
            anexo = ficha.anexos.get(pk=anexo_id)
        except FichaAnexo.DoesNotExist:
            return Response({'detail': 'Anexo não encontrado nesta ficha.'},
                            status=status.HTTP_404_NOT_FOUND)

        if request.method == 'DELETE':
            # O delete() do modelo apaga o arquivo do disco junto.
            anexo.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        anexo.descricao = (request.data.get('descricao') or '').strip()
        anexo.save(update_fields=['descricao'])
        serializer = FichaAnexoSerializer(anexo, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def avaliadores(self, request):
        """Nomes já usados como avaliador -- alimenta o autocomplete da ficha."""
        nomes = set()
        for campo in ('avaliador_1', 'avaliador_2', 'avaliador_3'):
            nomes.update(
                v for v in FichaEntrevista.objects.exclude(**{f'{campo}__exact': ''})
                .order_by().values_list(campo, flat=True).distinct() if v
            )
        return Response(sorted(nomes))

    @action(detail=False, methods=['get'])
    def setores(self, request):
        return Response(sorted(
            v for v in FichaEntrevista.objects.exclude(setor__exact='')
            .order_by().values_list('setor', flat=True).distinct() if v
        ))

    @action(detail=False, methods=['get'])
    def rascunho(self, request):
        """
        Devolve a ficha pré-preenchida com o que já existe no cadastro.

        A tela chama isto ao abrir uma ficha nova (``?candidato=<id>`` e,
        opcionalmente, ``?processo=<id>``) para o RH não redigitar identificação,
        escolaridade e experiências que o currículo já tem.
        """
        try:
            candidato = Candidato.objects.get(pk=request.query_params.get('candidato'))
        except (Candidato.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'Informe um candidato válido.'}, status=status.HTTP_400_BAD_REQUEST)

        processo = None
        processo_id = request.query_params.get('processo')
        if processo_id:
            processo = Processo.objects.select_related('vaga').filter(
                pk=processo_id, candidato=candidato,
            ).first()

        cursos = ' | '.join(filter(None, [
            ' '.join(filter(None, [candidato.curso_1, candidato.curso_1_local, candidato.curso_1_ano])).strip(),
            ' '.join(filter(None, [candidato.curso_2, candidato.curso_2_local, candidato.curso_2_ano])).strip(),
        ]))
        informatica = ' | '.join(filter(None, [
            f'Office: {candidato.nivel_office}' if candidato.nivel_office else '',
            f'Internet: {candidato.nivel_internet}' if candidato.nivel_internet else '',
        ]))

        return Response({
            'candidato': candidato.id,
            'processo': processo.id if processo else None,
            'vaga': processo.vaga_id if processo else None,
            'data_entrevista': processo.data_entrevista if processo else date.today(),
            'cargo_funcao': (processo.vaga.descricao if processo and processo.vaga else '') or candidato.funcao_desejada,
            'setor': (processo.vaga.area.nome if processo and processo.vaga and processo.vaga.area else ''),
            'nome': candidato.nome,
            'data_nascimento': candidato.data_nascimento,
            'endereco': candidato.endereco,
            'cidade': candidato.cidade,
            'telefone': candidato.telefone_principal,
            'telefone_contato': candidato.telefone_contato,
            'cnh_categoria': candidato.cnh_categoria,
            'email': candidato.email,
            'estado_civil': candidato.estado_civil,
            'escolaridade': candidato.escolaridade,
            'instituicao': candidato.instituicao_ensino,
            'data_conclusao': candidato.data_conclusao,
            'cursos_complementares': cursos,
            'nocoes_informatica': informatica,
            'esta_estudando': candidato.local_estudo if candidato.estuda_atualmente else '',
            'exp1_empresa': candidato.ultima_empresa,
            'exp1_atividades': candidato.ultima_empresa_funcao,
            'exp1_tempo': candidato.ultima_empresa_periodo,
            'exp2_empresa': candidato.penultima_empresa,
            'exp2_atividades': candidato.penultima_empresa_funcao,
            'exp2_tempo': candidato.penultima_empresa_periodo,
            'conhece_alguem_empresa': candidato.conhece_funcionario,
            'avaliador_1': processo.avaliador if processo and processo.avaliador else '',
        })


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


class TurnoverViewSet(viewsets.ViewSet):
    """
    Turnover (rotatividade) e absenteísmo.

    Lê o ERP, não o banco do módulo: admissão e desligamento estão em
    ``CONTRATOPESSOAL``. Ver ``recrutamento/turnover.py`` para a fonte, a
    fórmula e as ressalvas de defasagem de registro.

    ``GET /api/recrutamento/turnover/?anos=2022,2023&dias=90``
    """

    permission_classes = [IsRH]

    def list(self, request):
        anos = request.query_params.get('anos', '2022,2023')
        try:
            anos = tuple(
                int(a) for a in anos.split(',')
                if a.strip() and 2000 <= int(a) <= date.today().year
            )
        except ValueError:
            anos = (2022, 2023)
        if not anos:
            anos = (2022, 2023)

        try:
            dias = int(request.query_params.get('dias', 90))
        except ValueError:
            dias = 90
        dias = max(1, min(dias, 365 * 3))

        try:
            return Response(apurar_turnover(anos=anos, dias=dias))
        except SQLAlchemyError as erro:
            # O ERP fica noutra máquina: fora do ar, a tela precisa de um recado
            # em vez de um 500 sem explicação.
            return Response(
                {'detail': f'Não foi possível consultar o ERP: {erro}'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class FolhaPontoViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Importação da folha ponto e o absenteísmo que sai dela.

    ``POST   /api/recrutamento/folha-ponto/``            envia o ZIP da competência
    ``GET    /api/recrutamento/folha-ponto/``            lista as competências e o status
    ``DELETE /api/recrutamento/folha-ponto/<id>/``       remove uma competência
    ``GET    /api/recrutamento/folha-ponto/absenteismo/`` o indicador apurado

    ⚠️ Não use ``http_method_names`` para restringir os verbos: isso derruba as
    ``@action`` do DRF e o POST volta 405 (já aconteceu em outro módulo). Os
    mixins acima é que definem o que existe.
    """

    permission_classes = [IsRH]
    serializer_class = FolhaPontoSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = FolhaPonto.objects.all()

    def create(self, request, *args, **kwargs):
        # Aceita as três formas de o material chegar: o ZIP da competência, um PDF
        # só, ou a pasta inteira selecionada de uma vez (34 PDFs, um por setor) --
        # que é como fica depois de descompactar o e-mail do escritório.
        enviados = request.FILES.getlist('arquivos')
        if not enviados and 'arquivo' in request.data:
            enviados = [request.data['arquivo']]
        if not enviados:
            return Response(
                {'arquivo': 'Envie o ZIP da competência, ou os PDFs de espelho de ponto.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not fponto.tem_pdftotext():
            return Response(
                {'detail': (
                    'O servidor não tem o utilitário pdftotext (pacote poppler-utils), '
                    'necessário para ler o espelho de ponto. Instale com: '
                    'sudo apt-get install -y poppler-utils'
                )},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Vários PDFs viram um ZIP aqui: o modelo guarda UM arquivo por
        # competência, o que mantém o material original arquivado para reprocessar
        # sem depender de o usuário reenviar.
        if len(enviados) > 1:
            try:
                arquivo = fponto.compactar(enviados)
            except ValueError as erro:
                return Response({'arquivo': str(erro)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            arquivo = enviados[0]

        # A competência só é conhecida depois de ler o arquivo (sai do período de
        # referência impresso no cartão), então a linha nasce com chave provisória.
        folha = FolhaPonto.objects.create(
            competencia=FolhaPonto.chave_provisoria(),
            arquivo=arquivo,
            status=FolhaPonto.PROCESSANDO,
            importado_por=(request.user.get_full_name() or request.user.username)[:120],
        )

        # Em thread: 34 PDFs de uma competência levam alguns segundos e não vale
        # arriscar o timeout do nginx. A tela acompanha pelo status.
        Thread(target=fponto.importar_arquivo, args=(folha,), daemon=True).start()

        return Response(
            self.get_serializer(folha).data, status=status.HTTP_202_ACCEPTED
        )

    @action(detail=False, methods=['get'])
    def absenteismo(self, request):
        try:
            return Response(fponto.apurar_do_banco())
        except fponto.PopplerAusente as erro:
            return Response(
                {'detail': str(erro)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
