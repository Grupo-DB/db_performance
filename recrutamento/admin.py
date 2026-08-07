from django.contrib import admin

from .models import AreaInteresse, Candidato, FichaAnexo, FichaEntrevista, Processo, Vaga


@admin.register(AreaInteresse)
class AreaInteresseAdmin(admin.ModelAdmin):
    list_display = ['nome', 'ordem', 'ativo']
    list_editable = ['ordem', 'ativo']


@admin.register(Candidato)
class CandidatoAdmin(admin.ModelAdmin):
    list_display = ['id_legado', 'nome', 'cidade', 'telefone_principal', 'escolaridade', 'funcao_desejada', 'ativo']
    list_filter = ['ativo', 'sexo', 'escolaridade', 'pcd', 'areas_interesse']
    search_fields = ['nome', 'cpf', 'telefone_principal', 'funcao_desejada']
    filter_horizontal = ['areas_interesse']


@admin.register(Vaga)
class VagaAdmin(admin.ModelAdmin):
    list_display = ['id_legado', 'descricao', 'requisitante', 'tipo', 'data_abertura', 'status']
    list_filter = ['status', 'tipo']
    search_fields = ['descricao', 'requisitante']
    date_hierarchy = 'data_abertura'


@admin.register(Processo)
class ProcessoAdmin(admin.ModelAdmin):
    list_display = ['id_legado', 'candidato', 'vaga', 'data_contato', 'data_entrevista', 'parecer', 'etapa', 'contratado']
    list_filter = ['etapa', 'parecer', 'contratado', 'compareceu']
    search_fields = ['candidato__nome', 'vaga__descricao']
    autocomplete_fields = ['candidato', 'vaga']


class FichaAnexoInline(admin.TabularInline):
    model = FichaAnexo
    extra = 0
    readonly_fields = ['enviado_por', 'enviado_em']


@admin.register(FichaEntrevista)
class FichaEntrevistaAdmin(admin.ModelAdmin):
    list_display = ['id', 'nome', 'cargo_funcao', 'setor', 'data_entrevista', 'resultado', 'avaliador_1']
    list_filter = ['resultado', 'atende_requisitos', 'setor', 'disponibilidade_horario']
    search_fields = ['nome', 'candidato__nome', 'cargo_funcao', 'setor', 'avaliador_1']
    autocomplete_fields = ['candidato', 'vaga']
    date_hierarchy = 'data_entrevista'
    inlines = [FichaAnexoInline]
