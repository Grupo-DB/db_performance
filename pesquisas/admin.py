from django.contrib import admin

from .models import Pergunta, Pesquisa, Resposta, RespostaItem


class PerguntaInline(admin.TabularInline):
    model = Pergunta
    extra = 0


@admin.register(Pesquisa)
class PesquisaAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'codigo_formulario', 'status', 'criada_em')
    list_filter = ('status',)
    search_fields = ('titulo', 'codigo_formulario')
    inlines = [PerguntaInline]


@admin.register(Resposta)
class RespostaAdmin(admin.ModelAdmin):
    list_display = ('id', 'pesquisa', 'setor', 'enviada_em')
    list_filter = ('pesquisa', 'setor')


admin.site.register(RespostaItem)
