from django.contrib import admin

from .models import EvidenciaAnexo, ExtracaoIA, Norma, PlanoAcao, Requisito, Verificacao


@admin.register(Norma)
class NormaAdmin(admin.ModelAdmin):
    list_display = ('identificacao', 'tema', 'esfera', 'situacao', 'validade')
    list_filter = ('tema', 'esfera', 'tipo', 'situacao')
    search_fields = ('ementa', 'numero', 'orgao')


@admin.register(Requisito)
class RequisitoAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'aplicabilidade', 'situacao', 'proxima_verificacao', 'responsavel', 'ativo')
    list_filter = ('tema', 'aplicabilidade', 'situacao', 'origem', 'ativo')
    search_fields = ('descricao', 'referencia', 'norma__ementa')
    raw_id_fields = ('norma',)


class EvidenciaInline(admin.TabularInline):
    model = EvidenciaAnexo
    extra = 0


@admin.register(Verificacao)
class VerificacaoAdmin(admin.ModelAdmin):
    list_display = ('requisito', 'data', 'resultado', 'verificado_por')
    list_filter = ('resultado',)
    raw_id_fields = ('requisito',)
    inlines = [EvidenciaInline]


@admin.register(PlanoAcao)
class PlanoAcaoAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'requisito', 'responsavel', 'prazo', 'concluido_em')
    raw_id_fields = ('requisito', 'verificacao', 'tarefa')


@admin.register(ExtracaoIA)
class ExtracaoIAAdmin(admin.ModelAdmin):
    list_display = ('norma', 'status', 'modelo', 'tokens_entrada', 'tokens_saida', 'criado_em')
    list_filter = ('status',)
    raw_id_fields = ('norma',)
