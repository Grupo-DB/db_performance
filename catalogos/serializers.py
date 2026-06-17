from rest_framework import serializers
from django.contrib.auth.models import User
from decimal import Decimal

from .models import Fabricante, Equipamento, Veiculo, Secao, Item, Pedido, ItemPedido, PedidoNotificacao


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

    class Meta:
        model = ItemPedido
        fields = ['id', 'item', 'quantidade', 'preco_unitario', 'subtotal', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_subtotal(self, obj):
        return float(obj.subtotal)


class ItemPedidoWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemPedido
        fields = ['item', 'quantidade', 'preco_unitario']

    def validate_quantidade(self, value):
        if value < 1:
            raise serializers.ValidationError("Quantidade deve ser maior que 0")
        return value

    def validate_preco_unitario(self, value):
        if value < Decimal('0.01'):
            raise serializers.ValidationError("Preço deve ser maior que 0")
        return value


class PedidoListSerializer(serializers.ModelSerializer):
    usuario = serializers.CharField(source='usuario.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Pedido
        fields = ['id', 'numero_referencia', 'usuario', 'status', 'status_display', 'total', 'created_at', 'updated_at']
        read_only_fields = ['numero_referencia', 'created_at', 'updated_at']


class PedidoDetailSerializer(serializers.ModelSerializer):
    usuario = serializers.CharField(source='usuario.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    itens = ItemPedidoDetailSerializer(read_only=True, many=True)

    class Meta:
        model = Pedido
        fields = [
            'id', 'numero_referencia', 'usuario', 'status', 'status_display',
            'total', 'observacoes', 'itens', 'created_at', 'updated_at'
        ]
        read_only_fields = ['numero_referencia', 'total', 'created_at', 'updated_at']


class PedidoCreateSerializer(serializers.ModelSerializer):
    itens = ItemPedidoWriteSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = Pedido
        fields = ['observacoes', 'itens']

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
        fields = ['status', 'status_display', 'observacoes']

    def validate_status(self, value):
        """Validar transição de status permitida"""
        instance = self.instance
        if instance:
            current_status = instance.status
            allowed_transitions = {
                'RASCUNHO': ['ENVIADO', 'CANCELADO'],
                'ENVIADO': ['RECEBIDO', 'CANCELADO'],
                'RECEBIDO': ['EM_COTACAO', 'REJEITADO', 'CANCELADO'],
                'EM_COTACAO': ['APROVADO', 'REJEITADO', 'CANCELADO'],
                'APROVADO': ['REALIZADO', 'CANCELADO'],
                'REJEITADO': ['RASCUNHO', 'CANCELADO'],
                'REALIZADO': ['CANCELADO'],
                'CANCELADO': [],
            }

            if value not in allowed_transitions.get(current_status, []):
                raise serializers.ValidationError(
                    f"Não é possível mudar de {current_status} para {value}"
                )
        return value


class PedidoNotificacaoSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    pedido_numero = serializers.CharField(source='pedido.numero_referencia', read_only=True)

    class Meta:
        model = PedidoNotificacao
        fields = ['id', 'pedido_numero', 'tipo', 'tipo_display', 'mensagem', 'lido', 'created_at']
        read_only_fields = ['created_at']
