"""
Serializers do UNIDB.

Padrão do projeto: a FK entra como id (`write_only`) e sai expandida em
`*_detalhes`, para a tela não precisar de uma segunda chamada só para mostrar o nome.
"""
from rest_framework import serializers

from .models import Aluno, AvaliacaoTreinamento, Curso, Matricula, Turma


class AlunoSerializer(serializers.ModelSerializer):
    colaborador_nome = serializers.CharField(source='colaborador.nome', read_only=True)
    total_treinamentos = serializers.SerializerMethodField()

    class Meta:
        model = Aluno
        fields = '__all__'

    def get_total_treinamentos(self, obj):
        # `matriculas_contadas` vem do annotate da view; sem ele (detalhe, POST) cai na
        # contagem direta, que aqui é uma consulta só.
        return getattr(obj, 'matriculas_contadas', None) or obj.matriculas.count()


class CursoSerializer(serializers.ModelSerializer):
    total_turmas = serializers.SerializerMethodField()

    class Meta:
        model = Curso
        fields = '__all__'

    def get_total_turmas(self, obj):
        return getattr(obj, 'turmas_contadas', None) or obj.turmas.count()


class TurmaSerializer(serializers.ModelSerializer):
    curso = serializers.PrimaryKeyRelatedField(queryset=Curso.objects.all())
    curso_detalhes = CursoSerializer(source='curso', read_only=True)
    # Nome e área do curso repetidos no topo porque a listagem de turmas mostra as duas
    # colunas e o `curso_detalhes` inteiro é grande para uma tabela.
    curso_nome = serializers.CharField(source='curso.nome', read_only=True)
    curso_area = serializers.CharField(source='curso.area', read_only=True)
    total_matriculados = serializers.SerializerMethodField()
    total_presentes = serializers.SerializerMethodField()

    class Meta:
        model = Turma
        fields = '__all__'

    def get_total_matriculados(self, obj):
        return getattr(obj, 'matriculados', None) or obj.matriculas.count()

    def get_total_presentes(self, obj):
        contado = getattr(obj, 'presentes', None)
        if contado is not None:
            return contado
        return obj.matriculas.filter(presente=True).count()


class MatriculaSerializer(serializers.ModelSerializer):
    turma = serializers.PrimaryKeyRelatedField(queryset=Turma.objects.all())
    aluno = serializers.PrimaryKeyRelatedField(queryset=Aluno.objects.all())
    aluno_matricula = serializers.CharField(source='aluno.matricula', read_only=True)
    aluno_nome = serializers.CharField(source='aluno.nome', read_only=True)
    aluno_cargo = serializers.CharField(source='aluno.cargo', read_only=True)
    aluno_setor = serializers.CharField(source='aluno.setor', read_only=True)
    curso_nome = serializers.CharField(source='turma.curso.nome', read_only=True)
    turma_codigo = serializers.CharField(source='turma.codigo', read_only=True)
    turma_data = serializers.DateField(source='turma.data_inicial', read_only=True)
    instrutor = serializers.CharField(source='turma.instrutor', read_only=True)

    class Meta:
        model = Matricula
        fields = '__all__'


class MatriculaEmLoteSerializer(serializers.Serializer):
    """
    Matricular várias pessoas de uma vez.

    Existe porque o RH matricula uma turma inteira: pela API normal seriam 30 POSTs, e
    a tela teria de tratar erro de cada um. Aqui é uma chamada, e aluno já matriculado
    é ignorado em vez de virar erro (o `unique_together` recusaria).
    """
    turma = serializers.PrimaryKeyRelatedField(queryset=Turma.objects.all())
    alunos = serializers.PrimaryKeyRelatedField(queryset=Aluno.objects.all(), many=True)
    data_matricula = serializers.DateField(required=False, allow_null=True)


class AvaliacaoTreinamentoSerializer(serializers.ModelSerializer):
    turma = serializers.PrimaryKeyRelatedField(queryset=Turma.objects.all(), required=False, allow_null=True)
    curso_nome = serializers.CharField(source='turma.curso.nome', read_only=True)
    turma_data = serializers.DateField(source='turma.data_inicial', read_only=True)

    class Meta:
        model = AvaliacaoTreinamento
        fields = '__all__'

    def validate(self, dados):
        # Sem turma e sem o nome digitado a resposta fica órfã: não daria para dizer a
        # que treinamento ela se refere, nem no relatório nem na conferência.
        if not dados.get('turma') and not (dados.get('nome_treinamento') or '').strip():
            raise serializers.ValidationError(
                'Informe a turma ou o nome do treinamento avaliado.')
        return dados
