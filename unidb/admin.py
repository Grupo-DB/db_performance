from django.contrib import admin

from .models import Aluno, AvaliacaoTreinamento, Curso, Matricula, Turma


@admin.register(Aluno)
class AlunoAdmin(admin.ModelAdmin):
    list_display = ('matricula', 'nome', 'cargo', 'setor', 'origem', 'ativo')
    list_filter = ('origem', 'ativo', 'setor')
    search_fields = ('matricula', 'nome', 'cargo', 'setor')


@admin.register(Curso)
class CursoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'area', 'tipo_treinamento', 'validade_dias', 'status')
    list_filter = ('status', 'area', 'tipo_treinamento')
    search_fields = ('nome', 'area')


@admin.register(Turma)
class TurmaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'curso', 'instrutor', 'data_inicial', 'horas_aula', 'status')
    list_filter = ('status', 'instrutor')
    search_fields = ('codigo', 'codigo_modulo', 'curso__nome', 'instrutor')
    autocomplete_fields = ('curso',)


@admin.register(Matricula)
class MatriculaAdmin(admin.ModelAdmin):
    list_display = ('aluno', 'turma', 'situacao', 'presente', 'nota')
    list_filter = ('situacao', 'presente')
    search_fields = ('aluno__nome', 'aluno__matricula', 'turma__curso__nome')
    autocomplete_fields = ('turma', 'aluno')


@admin.register(AvaliacaoTreinamento)
class AvaliacaoTreinamentoAdmin(admin.ModelAdmin):
    list_display = ('nome_treinamento', 'instrutor', 'data_conclusao', 'avaliacao_geral', 'turma')
    list_filter = ('avaliacao_geral', 'conteudo_atendeu', 'tempo_duracao')
    search_fields = ('nome_treinamento', 'instrutor')
