from django.contrib import admin

from .models import AlertaClienteInativo


@admin.register(AlertaClienteInativo)
class AlertaClienteInativoAdmin(admin.ModelAdmin):
    list_display = ('cliente_codigo', 'cliente_nome', 'resolvido', 'ignorar',
                    'resolvido_por', 'data_resolucao', 'atualizado_em')
    list_filter = ('resolvido', 'ignorar')
    search_fields = ('cliente_codigo', 'cliente_nome')
