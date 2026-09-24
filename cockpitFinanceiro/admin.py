from django.contrib import admin

from .models import AnexoCockpit, DocumentoCockpit


@admin.register(DocumentoCockpit)
class DocumentoCockpitAdmin(admin.ModelAdmin):
    list_display = ('colecao', 'doc_id', 'atualizado_por', 'atualizado_em')
    list_filter = ('colecao',)
    exclude = ('dados',)


@admin.register(AnexoCockpit)
class AnexoCockpitAdmin(admin.ModelAdmin):
    list_display = ('nome', 'content_type', 'tamanho', 'enviado_por', 'enviado_em')
