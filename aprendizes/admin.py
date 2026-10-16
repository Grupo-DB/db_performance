from django.contrib import admin

from .models import Acompanhamento, Etapa


class EtapaInline(admin.TabularInline):
    model = Etapa
    extra = 0


@admin.register(Acompanhamento)
class AcompanhamentoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'setor', 'cargo', 'data_admissao', 'situacao')
    list_filter = ('situacao',)
    search_fields = ('nome', 'setor', 'cargo')
    inlines = [EtapaInline]
