"""
API do UNIDB.

Além do CRUD, três coisas que a planilha fazia com fórmula e aqui é consulta:

  * `turma/<id>/presenca/`            → cabeçalho + alunos da lista de presença (F011);
  * `turma/<id>/analise-avaliacoes/`  → apuração das fichas de avaliação da turma;
  * `relatorios/cursos-por-periodo/`  → a aba RELAT_CURSOS;
  * `relatorios/por-aluno/`           → histórico e vencimentos de um aluno.
"""
from datetime import date, timedelta

from django.db.models import Count, Q, Sum
from rest_framework import status as http_status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import Aluno, AvaliacaoTreinamento, Curso, Matricula, Turma
from .serializers import (AlunoSerializer, AvaliacaoTreinamentoSerializer, CursoSerializer,
                          MatriculaEmLoteSerializer, MatriculaSerializer, TurmaSerializer)


def _data(valor):
    """'AAAA-MM-DD' → date, ou None quando vazio/inválido."""
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


class AlunoViewSet(viewsets.ModelViewSet):
    serializer_class = AlunoSerializer
    filterset_fields = ['origem', 'ativo', 'setor', 'grupo_alvo']
    search_fields = ['matricula', 'nome', 'cargo', 'setor']

    def get_queryset(self):
        # `matriculas_contadas` evita uma consulta por linha na listagem (1.008 alunos).
        return (Aluno.objects
                .select_related('colaborador')
                .annotate(matriculas_contadas=Count('matriculas', distinct=True))
                .order_by('nome'))


class CursoViewSet(viewsets.ModelViewSet):
    serializer_class = CursoSerializer
    filterset_fields = ['status', 'area', 'tipo_treinamento']
    search_fields = ['nome', 'area']

    def get_queryset(self):
        return Curso.objects.annotate(turmas_contadas=Count('turmas', distinct=True)).order_by('nome')


class TurmaViewSet(viewsets.ModelViewSet):
    serializer_class = TurmaSerializer
    filterset_fields = ['status', 'curso', 'instrutor']
    search_fields = ['codigo', 'codigo_modulo', 'curso__nome', 'instrutor']

    def get_queryset(self):
        qs = (Turma.objects
              .select_related('curso')
              .annotate(
                  matriculados=Count('matriculas', distinct=True),
                  presentes=Count('matriculas', filter=Q(matriculas__presente=True), distinct=True),
              ))
        # `?dias=` / `?desde=` no mesmo espírito das listagens do laboratório: a tela de
        # turmas cresce para sempre e o RH trabalha nas recentes.
        desde = _data(self.request.query_params.get('desde'))
        dias = self.request.query_params.get('dias')
        if not desde and dias:
            try:
                n = int(dias)
                if n > 0:
                    desde = date.today() - timedelta(days=n)
            except ValueError:
                desde = None
        if desde:
            qs = qs.filter(Q(data_inicial__gte=desde) | Q(data_inicial__isnull=True))
        return qs.order_by('-data_inicial', '-id')

    @action(detail=True, methods=['get'])
    def presenca(self, request, pk=None):
        """Cabeçalho e alunos da lista de presença — o que o PDF F011 imprime."""
        turma = self.get_object()
        matriculas = (turma.matriculas
                      .select_related('aluno')
                      .order_by('aluno__nome'))
        return Response({
            'turma': TurmaSerializer(turma).data,
            'alunos': [{
                'matricula_id': m.id,
                'codigo': m.aluno.matricula,
                'nome': m.aluno.nome,
                'cargo': m.aluno.cargo,
                'setor': m.aluno.setor,
                'presente': m.presente,
            } for m in matriculas],
        })

    @action(detail=True, methods=['post'], url_path='registrar-presenca')
    def registrar_presenca(self, request, pk=None):
        """
        Grava a chamada de uma vez: `{"presencas": [{"matricula_id": 1, "presente": true}]}`.

        A folha assinada continua existindo no papel; isto é para o dado não morrer lá.
        Marcar presença fecha a matrícula como CONCLUIDO (e ausência não muda a situação,
        porque faltar não é reprovar — pode ser reposição).
        """
        turma = self.get_object()
        presencas = request.data.get('presencas') or []
        atualizadas = 0
        for item in presencas:
            matricula = turma.matriculas.filter(id=item.get('matricula_id')).first()
            if not matricula:
                continue
            matricula.presente = bool(item.get('presente'))
            if matricula.presente and matricula.situacao == 'MATRICULADO':
                matricula.situacao = 'CONCLUIDO'
            matricula.save(update_fields=['presente', 'situacao'])
            atualizadas += 1
        return Response({'atualizadas': atualizadas})

    @action(detail=True, methods=['get'], url_path='analise-avaliacoes')
    def analise_avaliacoes(self, request, pk=None):
        """
        Apuração das fichas da turma: contagem por resposta e os comentários.

        É a aba ANÁLISE_TREINAMENTO da planilha. Sai contagem e percentual por opção,
        na ordem das escalas do modelo — assim uma opção sem nenhuma resposta aparece
        com zero em vez de desaparecer do relatório.
        """
        turma = self.get_object()
        avaliacoes = list(turma.avaliacoes.all())
        total = len(avaliacoes)

        perguntas = [
            ('avaliacao_geral', 'Como você avalia o treinamento de forma geral?', AvaliacaoTreinamento.ESCALA_QUALIDADE),
            ('conteudo_atendeu', 'O conteúdo abordado atendeu às suas expectativas?', AvaliacaoTreinamento.ESCALA_SIM),
            ('didatica_instrutor', 'A didática do(a) instrutor(a) foi:', AvaliacaoTreinamento.ESCALA_QUALIDADE),
            ('material_apoio', 'O material de apoio foi claro e útil?', AvaliacaoTreinamento.ESCALA_SIM),
            ('tempo_duracao', 'O tempo de duração foi:', AvaliacaoTreinamento.ESCALA_TEMPO),
        ]
        resultado = []
        for campo, rotulo, escala in perguntas:
            opcoes = []
            for valor, texto in escala:
                quantas = sum(1 for a in avaliacoes if getattr(a, campo) == valor)
                opcoes.append({
                    'valor': valor, 'rotulo': texto, 'quantidade': quantas,
                    'percentual': round(quantas / total * 100, 1) if total else 0,
                })
            resultado.append({'campo': campo, 'pergunta': rotulo, 'opcoes': opcoes})

        return Response({
            'turma': TurmaSerializer(turma).data,
            'total_respostas': total,
            'total_matriculados': turma.matriculas.count(),
            'perguntas': resultado,
            'pontos_positivos': [a.pontos_positivos for a in avaliacoes if (a.pontos_positivos or '').strip()],
            'pontos_melhoria': [a.pontos_melhoria for a in avaliacoes if (a.pontos_melhoria or '').strip()],
        })


class MatriculaViewSet(viewsets.ModelViewSet):
    serializer_class = MatriculaSerializer
    filterset_fields = ['turma', 'aluno', 'situacao', 'presente']
    search_fields = ['aluno__nome', 'aluno__matricula', 'turma__curso__nome']

    def get_queryset(self):
        return (Matricula.objects
                .select_related('aluno', 'turma', 'turma__curso')
                .order_by('-turma__data_inicial', 'aluno__nome'))

    @action(detail=False, methods=['post'], url_path='em-lote')
    def em_lote(self, request):
        """Matricula vários alunos numa turma; quem já estava matriculado é ignorado."""
        serializer = MatriculaEmLoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        turma = serializer.validated_data['turma']
        alunos = serializer.validated_data['alunos']
        data_matricula = serializer.validated_data.get('data_matricula') or turma.data_inicial

        ja_matriculados = set(turma.matriculas.values_list('aluno_id', flat=True))
        novas = [Matricula(turma=turma, aluno=aluno, data_matricula=data_matricula)
                 for aluno in alunos if aluno.id not in ja_matriculados]
        Matricula.objects.bulk_create(novas)
        return Response({
            'criadas': len(novas),
            'ignoradas': len(alunos) - len(novas),
        }, status=http_status.HTTP_201_CREATED)


class AvaliacaoTreinamentoViewSet(viewsets.ModelViewSet):
    serializer_class = AvaliacaoTreinamentoSerializer
    filterset_fields = ['turma', 'avaliacao_geral', 'conteudo_atendeu', 'tempo_duracao']
    search_fields = ['nome_treinamento', 'instrutor']

    def get_queryset(self):
        return (AvaliacaoTreinamento.objects
                .select_related('turma', 'turma__curso')
                .order_by('-data_conclusao', '-id'))


# ─────────────────────────── Relatórios ────────────────────────────────────────

@api_view(['GET'])
def cursos_por_periodo(request):
    """
    Aba RELAT_CURSOS: treinamentos realizados entre duas datas.

    `?inicio=AAAA-MM-DD&fim=AAAA-MM-DD`. Sem datas devolve o ano corrente — o relatório
    sem recorte somaria a base inteira, que não é pergunta que alguém faz.

    Os totais saem daqui e não da tela para o número não depender de paginação: horas
    de treinamento é `horas_aula` da turma, e "participações" é a contagem de
    matrículas (o mesmo aluno em duas turmas conta duas vezes, porque foram dois
    treinamentos).
    """
    inicio = _data(request.query_params.get('inicio')) or date(date.today().year, 1, 1)
    fim = _data(request.query_params.get('fim')) or date.today()

    turmas = (Turma.objects
              .select_related('curso')
              .filter(data_inicial__gte=inicio, data_inicial__lte=fim)
              .annotate(
                  matriculados=Count('matriculas', distinct=True),
                  presentes=Count('matriculas', filter=Q(matriculas__presente=True), distinct=True),
                  respostas=Count('avaliacoes', distinct=True),
              )
              .order_by('data_inicial'))

    linhas = [{
        'turma_id': t.id,
        'codigo': t.codigo,
        'curso': t.curso.nome,
        'area': t.curso.area,
        'modulo': t.modulo,
        'instrutor': t.instrutor,
        'data_inicial': t.data_inicial,
        'data_final': t.data_final,
        'horas_aula': float(t.horas_aula or 0),
        'vagas': t.vagas,
        'matriculados': t.matriculados,
        'presentes': t.presentes,
        'avaliacoes': t.respostas,
        'status': t.status,
    } for t in turmas]

    horas = sum(l['horas_aula'] for l in linhas)
    participacoes = sum(l['matriculados'] for l in linhas)
    return Response({
        'inicio': inicio, 'fim': fim,
        'total_treinamentos': len(linhas),
        'total_horas_aula': round(horas, 2),
        'total_participacoes': participacoes,
        # Homem-hora de treinamento: é o número que o RH usa em indicador anual.
        'total_horas_homem': round(sum(l['horas_aula'] * l['matriculados'] for l in linhas), 2),
        'total_alunos_distintos': (Matricula.objects
                                   .filter(turma__data_inicial__gte=inicio, turma__data_inicial__lte=fim)
                                   .values('aluno_id').distinct().count()),
        'por_area': _somar_por(linhas, 'area'),
        'por_instrutor': _somar_por(linhas, 'instrutor'),
        'turmas': linhas,
    })


def _somar_por(linhas, chave):
    """Agrupa as linhas do relatório por área/instrutor, para os gráficos da tela."""
    grupos = {}
    for linha in linhas:
        nome = linha.get(chave) or 'Não informado'
        item = grupos.setdefault(nome, {'nome': nome, 'treinamentos': 0, 'horas_aula': 0.0, 'participacoes': 0})
        item['treinamentos'] += 1
        item['horas_aula'] += linha['horas_aula']
        item['participacoes'] += linha['matriculados']
    return sorted(grupos.values(), key=lambda g: -g['treinamentos'])


@api_view(['GET'])
def analise_por_aluno(request):
    """
    Análise de treinamentos por funcionário.

    `?aluno=<id>` ou `?matricula=<chapa>` para um aluno; sem parâmetro devolve o
    consolidado de todos (uma linha por aluno), que é o que responde "quem está
    treinado e quem não está".

    `vencimento` sai da `data_vencimento` da turma quando existe; senão de
    `data_inicial + Curso.validade_dias`. Treinamento sem validade cadastrada não vence
    e fica com null — melhor que inventar uma data.
    """
    alunos = Aluno.objects.all()
    aluno_id = request.query_params.get('aluno')
    matricula = request.query_params.get('matricula')
    if aluno_id:
        alunos = alunos.filter(id=aluno_id)
    elif matricula:
        alunos = alunos.filter(matricula=str(matricula).strip())
    if request.query_params.get('setor'):
        alunos = alunos.filter(setor=request.query_params['setor'])
    if request.query_params.get('somente_ativos') in ('1', 'true', 'True'):
        alunos = alunos.filter(ativo=True)

    detalhar = bool(aluno_id or matricula)
    hoje = date.today()

    matriculas = (Matricula.objects
                  .filter(aluno__in=alunos)
                  .select_related('turma', 'turma__curso', 'aluno')
                  .order_by('-turma__data_inicial'))

    por_aluno = {}
    for m in matriculas:
        turma, curso = m.turma, m.turma.curso
        vencimento = turma.data_vencimento
        if not vencimento and turma.data_inicial and curso.validade_dias:
            vencimento = turma.data_inicial + timedelta(days=int(curso.validade_dias))

        item = por_aluno.setdefault(m.aluno_id, {
            'aluno_id': m.aluno_id,
            'matricula': m.aluno.matricula,
            'nome': m.aluno.nome,
            'cargo': m.aluno.cargo,
            'setor': m.aluno.setor,
            'treinamentos': 0, 'concluidos': 0, 'horas_aula': 0.0,
            'vencidos': 0, 'a_vencer_90_dias': 0,
            'ultimo_treinamento': None,
            'cursos': [],
        })
        item['treinamentos'] += 1
        if m.situacao == 'CONCLUIDO':
            item['concluidos'] += 1
            # Horas contam o que foi concluído: matrícula pendente ainda não é hora
            # treinada, e somá-la inflaria o indicador.
            item['horas_aula'] += float(turma.horas_aula or 0)
        if vencimento:
            if vencimento < hoje:
                item['vencidos'] += 1
            elif vencimento <= hoje + timedelta(days=90):
                item['a_vencer_90_dias'] += 1
        if turma.data_inicial and (not item['ultimo_treinamento'] or turma.data_inicial > item['ultimo_treinamento']):
            item['ultimo_treinamento'] = turma.data_inicial
        if detalhar:
            item['cursos'].append({
                'turma_id': turma.id,
                'curso': curso.nome,
                'area': curso.area,
                'modulo': turma.modulo,
                'instrutor': turma.instrutor,
                'data': turma.data_inicial,
                'horas_aula': float(turma.horas_aula or 0),
                'situacao': m.situacao,
                'presente': m.presente,
                'nota': float(m.nota) if m.nota is not None else None,
                'nota_minima': float(curso.nota_minima) if curso.nota_minima is not None else None,
                'vencimento': vencimento,
                'vencido': bool(vencimento and vencimento < hoje),
            })

    # Aluno sem nenhuma matrícula também entra: "quem nunca treinou" é justamente o que
    # o relatório precisa mostrar.
    for aluno in alunos:
        por_aluno.setdefault(aluno.id, {
            'aluno_id': aluno.id, 'matricula': aluno.matricula, 'nome': aluno.nome,
            'cargo': aluno.cargo, 'setor': aluno.setor,
            'treinamentos': 0, 'concluidos': 0, 'horas_aula': 0.0,
            'vencidos': 0, 'a_vencer_90_dias': 0, 'ultimo_treinamento': None, 'cursos': [],
        })

    linhas = sorted(por_aluno.values(), key=lambda a: a['nome'])
    for linha in linhas:
        linha['horas_aula'] = round(linha['horas_aula'], 2)

    return Response({
        'total_alunos': len(linhas),
        'total_treinamentos': sum(l['treinamentos'] for l in linhas),
        'total_horas_aula': round(sum(l['horas_aula'] for l in linhas), 2),
        'alunos_sem_treinamento': sum(1 for l in linhas if l['treinamentos'] == 0),
        'total_vencidos': sum(l['vencidos'] for l in linhas),
        'alunos': linhas,
    })
