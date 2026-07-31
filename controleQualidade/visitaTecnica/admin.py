from django.contrib import admin

from .models import VisitaTecnica, VisitaTecnicaImagem


class VisitaTecnicaImagemInline(admin.TabularInline):
    model = VisitaTecnicaImagem
    extra = 0


@admin.register(VisitaTecnica)
class VisitaTecnicaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'cliente', 'nome_obra', 'data_visita', 'data_ensaio')
    search_fields = ('codigo', 'cliente', 'nome_obra')
    list_filter = ('data_visita', 'laboratorio')
    inlines = [VisitaTecnicaImagemInline]
