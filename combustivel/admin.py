from django.contrib import admin

from .models import Abastecimento, Auditoria, ChaveIntegracao, LoteIntegracao, MedicaoTanque, Tanque


@admin.register(Tanque)
class TanqueAdmin(admin.ModelAdmin):
    list_display = ['nome', 'produto', 'filial', 'capacidade_l', 'ativo']


@admin.register(Abastecimento)
class AbastecimentoAdmin(admin.ModelAdmin):
    list_display = ['abastecido_em', 'equipamento_nome', 'litros', 'situacao', 'bloqueado']
    list_filter = ['situacao', 'bloqueado', 'tanque']
    search_fields = ['equipamento_nome', 'placa', 'funcionario_nome']
    exclude = ['foto_bomba', 'foto_painel']


@admin.register(ChaveIntegracao)
class ChaveAdmin(admin.ModelAdmin):
    list_display = ['nome', 'prefixo', 'ativa', 'ultimo_uso_em', 'ultimo_ip']
    exclude = ['hash_segredo']
    readonly_fields = ['prefixo', 'ultimo_uso_em', 'ultimo_ip', 'usos']


admin.site.register(MedicaoTanque)
admin.site.register(LoteIntegracao)


@admin.register(Auditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = ['quando', 'acao', 'objeto', 'usuario', 'ip']
    readonly_fields = [f.name for f in Auditoria._meta.fields]
