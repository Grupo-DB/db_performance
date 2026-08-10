from django.contrib import admin

from .models import IndicadorBoletim, ResultadoBoletim


@admin.register(IndicadorBoletim)
class IndicadorBoletimAdmin(admin.ModelAdmin):
    """
    É aqui que o laboratório acerta o mapeamento sem depender de deploy.

    Os campos vêm agrupados na ordem da pergunta que respondem: o que é a linha,
    de onde sai o número, de quais amostras, como cobrar e como ponderar.
    """
    list_display = ('nome', 'bloco', 'ordem', 'agregacao', 'tipo_limite', 'valor_limite', 'pai', 'ativo')
    list_filter = ('bloco', 'agregacao', 'tipo_limite', 'ativo')
    search_fields = ('nome', 'bloco_titulo', 'ensaio_nome', 'material', 'tipo_amostra', 'local_coleta')
    autocomplete_fields = ()
    filter_horizontal = ('produtos',)
    ordering = ('bloco', 'ordem', 'nome')
    fieldsets = (
        ('Identificação', {
            'fields': ('bloco', 'bloco_titulo', 'nome', 'ordem', 'ativo', 'observacao'),
        }),
        ('De onde sai o número', {
            'fields': ('agregacao', 'pai', 'ensaio', 'ensaio_nome', 'campo_especial',
                       'peneira_malha', 'peneira_metrica', 'campo_data'),
            'description': 'Informe <b>ensaio</b> (preferido) ou <b>ensaio_nome</b>. O nome também '
                           'encontra cálculo composto, que não está no catálogo de ensaios — é o '
                           'caso do CO₂ e dos óxidos não hidratados.',
        }),
        ('De quais amostras', {
            'fields': ('material', 'tipo_amostra', 'local_coleta', 'finalidade', 'produtos'),
            'description': 'Os textos comparam por trecho, sem diferenciar maiúsculas. Deixar em '
                           'branco significa "não filtrar por isso".',
        }),
        ('Limite e apresentação', {
            'fields': ('unidade', 'casas_decimais', 'tipo_limite', 'valor_limite'),
            'description': 'O limite vai na mesma unidade do resultado: 5 (e não 0,05) para 5%.',
        }),
        ('Produção para ponderar', {
            'fields': ('producao_codigos', 'producao_etapa'),
            'description': 'Só nos <b>componentes</b> de um indicador ponderado. Sem produção, o pai '
                           'cai para média simples e a tela marca a célula.',
        }),
    )


@admin.register(ResultadoBoletim)
class ResultadoBoletimAdmin(admin.ModelAdmin):
    list_display = ('indicador', 'ano', 'semana', 'valor', 'texto', 'producao', 'usuario', 'atualizado_em')
    list_filter = ('ano', 'indicador__bloco')
    search_fields = ('indicador__nome', 'texto', 'observacao')
    ordering = ('-ano', '-semana')
