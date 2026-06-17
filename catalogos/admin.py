from django.contrib import admin

from .models import Fabricante, Equipamento, Veiculo, Secao, Produto, Pedido, ItemPedido, PedidoNotificacao


@admin.register(Fabricante)
class FabricanteAdmin(admin.ModelAdmin):
    list_display = ('nome', 'created_at', 'updated_at')
    search_fields = ('nome',)


@admin.register(Equipamento)
class EquipamentoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ativo', 'created_at', 'updated_at')
    list_filter = ('ativo', 'created_at')
    search_fields = ('nome',)


@admin.register(Veiculo)
class VeiculoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'modelo', 'fabricante', 'equipamento', 'ativo', 'created_at')
    list_filter = ('fabricante', 'equipamento', 'ativo', 'created_at')
    search_fields = ('nome', 'modelo')
    ordering = ('-created_at',)


@admin.register(Secao)
class SecaoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'veiculo', 'ativo', 'created_at')
    list_filter = ('veiculo', 'ativo', 'created_at')
    search_fields = ('nome',)
    ordering = ('-created_at',)


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'veiculo', 'secao', 'preco', 'ativo', 'created_at')
    list_filter = ('veiculo', 'secao', 'ativo', 'created_at')
    search_fields = ('nome', 'descricao')
    ordering = ('-created_at',)


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('numero_referencia', 'usuario', 'status', 'total', 'created_at', 'updated_at')
    list_filter = ('status', 'usuario', 'created_at')
    search_fields = ('numero_referencia',)
    ordering = ('-created_at',)


@admin.register(ItemPedido)
class ItemPedidoAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'produto', 'quantidade', 'preco_unitario', 'subtotal', 'created_at')
    list_filter = ('pedido', 'created_at')
    search_fields = ('pedido__numero_referencia', 'produto__nome')
    ordering = ('-created_at',)


@admin.register(PedidoNotificacao)
class PedidoNotificacaoAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'usuario_notificado', 'tipo', 'lido', 'created_at')
    list_filter = ('tipo', 'lido', 'usuario_notificado', 'created_at')
    search_fields = ('pedido__numero_referencia', 'usuario_notificado__username')
    ordering = ('-created_at',)
