from django.contrib import admin

from .models import Campanha, ItemPedido, Peca, Pedido


class PecaInline(admin.TabularInline):
    model = Peca
    extra = 0


class ItemInline(admin.TabularInline):
    model = ItemPedido
    extra = 0


@admin.register(Campanha)
class CampanhaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ano', 'ativa')
    inlines = [PecaInline]


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'campanha', 'modalidade', 'genero', 'setor')
    list_filter = ('campanha', 'modalidade', 'genero')
    search_fields = ('nome', 'cpf', 'setor')
    inlines = [ItemInline]
