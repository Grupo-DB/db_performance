from django.contrib import admin

from .models import Evento, Participante, Premio, Presenca, Sorteio


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'data_inicio', 'data_fim', 'ativo')


@admin.register(Participante)
class ParticipanteAdmin(admin.ModelAdmin):
    list_display = ('nome', 'matricula', 'setor', 'evento', 'ativo')
    list_filter = ('evento', 'ativo')
    search_fields = ('nome', 'matricula')


@admin.register(Premio)
class PremioAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'categoria', 'regra', 'quantidade', 'evento')
    list_filter = ('evento', 'categoria')


@admin.register(Sorteio)
class SorteioAdmin(admin.ModelAdmin):
    list_display = ('participante', 'premio', 'status', 'total_concorrentes', 'sorteado_em')
    list_filter = ('evento', 'status')


admin.site.register(Presenca)
