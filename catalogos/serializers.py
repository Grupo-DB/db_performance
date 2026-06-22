from rest_framework import serializers
from django.contrib.auth.models import User
from decimal import Decimal

from .models import (
    Fabricante, Equipamento, Veiculo, Secao, Item, Pedido, ItemPedido, AnexoPedido,
    PedidoNotificacao, CatalogoPDF, ItemErpCatalogo, EquipamentoCatalogo,
)


class FabricanteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fabricante
        fields = ['id', 'nome', 'image', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class EquipamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Equipamento
        fields = ['id', 'nome', 'descricao', 'ativo', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class VeiculoListSerializer(serializers.ModelSerializer):
    fabricante = FabricanteSerializer(read_only=True)
    equipamento = EquipamentoSerializer(read_only=True)

    class Meta:
        model = Veiculo
        fields = ['id', 'nome', 'modelo', 'fabricante', 'equipamento', 'descricao', 'ativo', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class VeiculoDetailSerializer(serializers.ModelSerializer):
    fabricante = FabricanteSerializer(read_only=True)
    equipamento = EquipamentoSerializer(read_only=True)

    class Meta:
        model = Veiculo
        fields = ['id', 'nome', 'modelo', 'fabricante', 'equipamento', 'descricao', 'ativo', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class VeiculoCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Veiculo
        fields = ['nome', 'modelo', 'fabricante', 'equipamento', 'descricao', 'ativo']


class SecaoSerializer(serializers.ModelSerializer):
    veiculo = VeiculoListSerializer(read_only=True)

    class Meta:
        model = Secao
        fields = ['id', 'nome', 'veiculo', 'descricao', 'ativo', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class SecaoCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Secao
        fields = ['nome', 'veiculo', 'descricao', 'ativo']


class ItemListSerializer(serializers.ModelSerializer):
    veiculo = VeiculoListSerializer(read_only=True)
    secao = SecaoSerializer(read_only=True)

    class Meta:
        model = Item
        fields = ['id', 'nome', 'apelido', 'descricao', 'veiculo', 'secao', 'preco', 'cod_catalogo', 'cod_minerion', 'referencia', 'localizacao', 'image', 'ativo']


class ItemDetailSerializer(serializers.ModelSerializer):
    veiculo = VeiculoDetailSerializer(read_only=True)
    secao = SecaoSerializer(read_only=True)

    class Meta:
        model = Item
        fields = ['id', 'nome', 'apelido', 'descricao', 'veiculo', 'secao', 'preco', 'cod_catalogo', 'cod_minerion', 'referencia', 'localizacao', 'image', 'ativo', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class ItemCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = ['nome', 'apelido', 'descricao', 'veiculo', 'secao', 'preco', 'cod_catalogo', 'cod_minerion', 'referencia', 'localizacao', 'image', 'ativo']


class ItemPedidoDetailSerializer(serializers.ModelSerializer):
    item = ItemListSerializer(read_only=True)
    subtotal = serializers.SerializerMethodField()
    nome_exibicao = serializers.SerializerMethodField()

    class Meta:
        model = ItemPedido
        fields = [
            'id', 'item', 'cod_erp', 'nome_produto', 'nome_exibicao',
            'quantidade', 'preco_unitario', 'subtotal', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_subtotal(self, obj):
        return float(obj.subtotal)

    def get_nome_exibicao(self, obj):
        if obj.nome_produto:
            return obj.nome_produto
        if obj.item:
            return obj.item.nome
        return obj.cod_erp or ''


class ItemPedidoWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemPedido
        fields = ['item', 'cod_erp', 'nome_produto', 'quantidade', 'preco_unitario']

    def validate(self, attrs):
        if not attrs.get('item') and not attrs.get('cod_erp'):
            raise serializers.ValidationError("Informe 'item' (local) ou 'cod_erp' (ERP).")
        return attrs

    def validate_quantidade(self, value):
        if value < 1:
            raise serializers.ValidationError("Quantidade deve ser maior que 0")
        return value

    def validate_preco_unitario(self, value):
        if value < Decimal('0.00'):
            raise serializers.ValidationError("Preço não pode ser negativo")
        return value


class CatalogoPDFSerializer(serializers.ModelSerializer):
    veiculo_obj = VeiculoListSerializer(source='veiculo', read_only=True)

    class Meta:
        model = CatalogoPDF
        fields = ['id', 'titulo', 'arquivo', 'veiculo', 'veiculo_obj', 'descricao', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class ItemErpCatalogoSerializer(serializers.ModelSerializer):
    catalogo_titulo = serializers.CharField(source='catalogo.titulo', read_only=True)
    catalogo_arquivo = serializers.FileField(source='catalogo.arquivo', read_only=True)
    catalogo_obj = CatalogoPDFSerializer(source='catalogo', read_only=True)

    class Meta:
        model = ItemErpCatalogo
        fields = [
            'id', 'cod_erp', 'nome_erp', 'cod_catalogo',
            'catalogo', 'catalogo_titulo', 'catalogo_arquivo', 'catalogo_obj',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class PedidoListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    solicitante_nome = serializers.SerializerMethodField(read_only=True)
    responsavel_nome = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Pedido
        fields = [
            'id', 'numero_referencia', 'status', 'status_display',
            'solicitante_nome', 'responsavel', 'responsavel_nome',
            'total', 'motivo_rejeicao', 'created_at', 'updated_at',
        ]
        read_only_fields = ['numero_referencia', 'created_at', 'updated_at']

    def get_solicitante_nome(self, obj):
        if not obj.usuario:
            return None
        return obj.usuario.get_full_name() or obj.usuario.username

    def get_responsavel_nome(self, obj):
        if not obj.responsavel:
            return None
        return obj.responsavel.get_full_name() or obj.responsavel.username


class AnexoPedidoSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnexoPedido
        fields = ['id', 'pedido', 'arquivo', 'descricao', 'created_at']
        read_only_fields = ['id', 'created_at']


class PedidoDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    solicitante_nome = serializers.SerializerMethodField(read_only=True)
    responsavel_nome = serializers.SerializerMethodField(read_only=True)
    itens_pedido = ItemPedidoDetailSerializer(read_only=True, many=True)
    anexos = AnexoPedidoSerializer(read_only=True, many=True)

    class Meta:
        model = Pedido
        fields = [
            'id', 'numero_referencia', 'status', 'status_display',
            'solicitante_nome', 'responsavel', 'responsavel_nome',
            'total', 'observacoes', 'motivo_rejeicao', 'itens_pedido',
            'anexos', 'created_at', 'updated_at',
        ]
        read_only_fields = ['numero_referencia', 'total', 'created_at', 'updated_at']

    def get_solicitante_nome(self, obj):
        if not obj.usuario:
            return None
        return obj.usuario.get_full_name() or obj.usuario.username

    def get_responsavel_nome(self, obj):
        if not obj.responsavel:
            return None
        return obj.responsavel.get_full_name() or obj.responsavel.username


class PedidoCreateSerializer(serializers.ModelSerializer):
    itens = ItemPedidoWriteSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = Pedido
        fields = ['id', 'numero_referencia', 'observacoes', 'itens']
        read_only_fields = ['id', 'numero_referencia']

    def create(self, validated_data):
        itens_data = validated_data.pop('itens', [])
        request = self.context.get('request')

        pedido = Pedido.objects.create(
            usuario=request.user,
            **validated_data
        )

        # Gerar número de referência
        pedido.numero_referencia = f"PED-{pedido.id:06d}"
        pedido.save(update_fields=['numero_referencia'])

        # Criar itens
        for item_data in itens_data:
            ItemPedido.objects.create(pedido=pedido, **item_data)

        return pedido


class PedidoUpdateStatusSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Pedido
        fields = ['status', 'status_display', 'observacoes', 'motivo_rejeicao']

    def validate(self, attrs):
        novo_status = attrs.get('status')
        if novo_status == 'REJEITADO' and not attrs.get('motivo_rejeicao', '').strip():
            raise serializers.ValidationError(
                {'motivo_rejeicao': 'Informe o motivo da rejeição.'}
            )
        return attrs

    def validate_status(self, value):
        return value


class EquipamentoCatalogoSerializer(serializers.ModelSerializer):
    catalogo_titulo = serializers.CharField(source='catalogo.titulo', read_only=True, default=None)

    class Meta:
        model = EquipamentoCatalogo
        fields = ['id', 'equipamento', 'catalogo', 'catalogo_titulo', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class PedidoNotificacaoSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    pedido_numero = serializers.CharField(source='pedido.numero_referencia', read_only=True)

    class Meta:
        model = PedidoNotificacao
        fields = ['id', 'pedido_numero', 'tipo', 'tipo_display', 'mensagem', 'lido', 'created_at']
        read_only_fields = ['created_at']
