from django.contrib import admin

from .models import FolhaCarga, FotoProduto, ItemFolhaCarga, ItemPedidoVenda, PedidoVenda, PedidoVendaEvento, PedidoVendaNotificacao, VendedorPerfil


@admin.register(VendedorPerfil)
class VendedorPerfilAdmin(admin.ModelAdmin):
    list_display = ('user', 'tipo', 'repcods', 'filial_padrao', 'desconto_maximo', 'interno', 'ativo')
    list_filter = ('tipo', 'ativo', 'filial_padrao')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')


class ItemInline(admin.TabularInline):
    model = ItemPedidoVenda
    extra = 0


class EventoInline(admin.TabularInline):
    model = PedidoVendaEvento
    extra = 0
    readonly_fields = ('tipo', 'usuario', 'texto', 'criado_em')


@admin.register(PedidoVenda)
class PedidoVendaAdmin(admin.ModelAdmin):
    list_display = ('id', 'cliente_nome', 'vendedor', 'interno', 'status', 'total', 'numero_erp', 'criado_em')
    list_filter = ('status', 'filial')
    search_fields = ('cliente_nome', 'cliente_documento', 'numero_erp')
    inlines = [ItemInline, EventoInline]


admin.site.register(PedidoVendaNotificacao)


@admin.register(FotoProduto)
class FotoProdutoAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'codigos', 'enviado_por', 'atualizado_em')


class ItemFolhaInline(admin.TabularInline):
    model = ItemFolhaCarga
    extra = 0


@admin.register(FolhaCarga)
class FolhaCargaAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'filial', 'data_prevista', 'status', 'carga_sga', 'criado_por', 'criado_em')
    list_filter = ('status', 'filial')
    search_fields = ('descricao', 'placa', 'itens__pedido')
    inlines = [ItemFolhaInline]
