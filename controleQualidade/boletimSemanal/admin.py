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
    search_fields = ('nome', 'bloco_titulo', 'ensaio_nome', 'material', 'tipo_amostra', 'tipo_amostragem', 'local_coleta')
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
            'fields': ('material', 'tipo_amostra', 'tipo_amostragem', 'local_coleta', 'finalidade', 'produtos'),
            'description': 'Os textos comparam por trecho, sem diferenciar maiúsculas; vírgula = OU. '
                           'Deixar em branco significa "não filtrar por isso".<br>'
                           'Comece com <b>=</b> para exigir o valor exato — <code>=Fábrica I</code> '
                           'não casa com "Fábrica II"/"Fábrica III", que é o que acontece sem o sinal.<br>'
                           '<b>Tipo amostra</b> é o produto (VIRGEM, CH-II); <b>tipo amostragem</b> é '
                           'como foi colhida (Media, Pontual).',
        }),
        ('Limite e apresentação', {
            'fields': ('unidade', 'casas_decimais', 'tipo_limite', 'valor_limite'),
            'description': 'O limite vai na mesma unidade do resultado: 5 (e não 0,05) para 5%.',
        }),
        ('Produção para ponderar', {
            'fields': ('producao_codigos', 'producao_local', 'producao_etapa'),
            'description': 'Só nos <b>componentes</b> de um indicador ponderado. Sem produção, o pai '
                           'cai para média simples e a tela marca a célula.<br>'
                           '<b>Código de estoque</b> separa produto (2737 CH-II, 2738 hidráulica, etapa 3); '
                           '<b>local</b> separa fábrica (23 FCM I, 24 FCM II, 25 FCM III, etapa 6).',
        }),
    )


@admin.register(ResultadoBoletim)
class ResultadoBoletimAdmin(admin.ModelAdmin):
    list_display = ('indicador', 'ano', 'semana', 'valor', 'texto', 'producao', 'usuario', 'atualizado_em')
    list_filter = ('ano', 'indicador__bloco')
    search_fields = ('indicador__nome', 'texto', 'observacao')
    ordering = ('-ano', '-semana')
