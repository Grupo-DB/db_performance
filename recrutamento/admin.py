from django.contrib import admin

from .models import AreaInteresse, Candidato, Processo, Vaga


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
