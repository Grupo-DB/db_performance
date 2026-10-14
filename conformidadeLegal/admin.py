from django.contrib import admin

from .models import (
    ConfiguracaoMonitor, EvidenciaAnexo, ExecucaoMonitor, ExtracaoIA, Norma, OrgaoMonitor, PalavraChaveMonitor, PlanoAcao,
    PublicacaoMonitorada, Requisito, Verificacao,
)


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


@admin.register(PublicacaoMonitorada)
class PublicacaoMonitoradaAdmin(admin.ModelAdmin):
    list_display = ('data_publicacao', 'fonte', 'orgao', 'titulo', 'relevancia', 'status')
    list_filter = ('fonte', 'status', 'relevancia')
    search_fields = ('titulo', 'texto', 'orgao')
    raw_id_fields = ('norma', 'avaliado_por')


@admin.register(ExecucaoMonitor)
class ExecucaoMonitorAdmin(admin.ModelAdmin):
    list_display = ('data_referencia', 'fonte', 'ok', 'examinadas', 'novas', 'iniciado_em', 'erro')
    list_filter = ('fonte', 'ok')


@admin.register(PalavraChaveMonitor)
class PalavraChaveMonitorAdmin(admin.ModelAdmin):
    list_display = ('rotulo', 'ativo', 'atualizado_em')
    list_filter = ('ativo',)


@admin.register(OrgaoMonitor)
class OrgaoMonitorAdmin(admin.ModelAdmin):
    list_display = ('rotulo', 'fonte', 'campo', 'valor', 'exige_palavra', 'ativo', 'ordem')
    list_filter = ('fonte', 'ativo')


admin.site.register(ConfiguracaoMonitor)
