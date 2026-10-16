from django.db import transaction
from rest_framework import serializers

from .models import Campanha, ItemPedido, Peca, Pedido
from .regras import alertas, valor_pedido


class PecaSerializer(serializers.ModelSerializer):
    rotulo = serializers.CharField(source='__str__', read_only=True)

    class Meta:
        model = Peca
        fields = ['id', 'campanha', 'nome', 'publico', 'grupo', 'preco', 'precos_por_tamanho', 'tem_ziper', 'ordem', 'rotulo']


class CampanhaSerializer(serializers.ModelSerializer):
    pecas = PecaSerializer(many=True, read_only=True)
    total_pedidos = serializers.IntegerField(source='pedidos.count', read_only=True)

    class Meta:
        model = Campanha
        fields = ['id', 'nome', 'ano', 'ativa', 'camisas_quem_ganha', 'parcelas_max', 'regras', 'pecas', 'total_pedidos']


class ItemPedidoSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    peca_nome = serializers.CharField(source='peca.nome', read_only=True)
    peca_grupo = serializers.CharField(source='peca.grupo', read_only=True)
    valor_unitario = serializers.SerializerMethodField()

    class Meta:
        model = ItemPedido
        fields = ['id', 'peca', 'peca_nome', 'peca_grupo', 'quantidade', 'tamanho', 'ziper',
                  'entregue', 'entregue_em', 'entrega_obs', 'valor_unitario']

    def get_valor_unitario(self, obj):
        return obj.peca.preco_do_tamanho(obj.tamanho)

    def validate(self, attrs):
        if attrs.get('entregue_em') and 'entregue' not in attrs:
            attrs['entregue'] = True
        if 'tamanho' in attrs:
            attrs['tamanho'] = attrs['tamanho'].strip().upper()
        return attrs


class PedidoSerializer(serializers.ModelSerializer):
    itens = ItemPedidoSerializer(many=True, required=False)
    valor_total = serializers.SerializerMethodField()
    valor_parcela = serializers.SerializerMethodField()
    alertas = serializers.SerializerMethodField()
    itens_pendentes = serializers.SerializerMethodField()

    class Meta:
        model = Pedido
        fields = ['id', 'campanha', 'colaborador', 'nome', 'cpf', 'setor', 'cargo', 'genero', 'modalidade', 'parcelas',
                  'observacao', 'itens', 'valor_total', 'valor_parcela', 'alertas', 'itens_pendentes']

    def get_valor_total(self, obj):
        return valor_pedido(obj)

    def get_valor_parcela(self, obj):
        total = valor_pedido(obj)
        return (total / max(1, obj.parcelas)).quantize(total.__class__('0.01')) if total else total

    def get_alertas(self, obj):
        return alertas(obj)

    def get_itens_pendentes(self, obj):
        return sum(1 for i in obj.itens.all() if not i.entregue)

    def validate(self, attrs):
        campanha = attrs.get('campanha') or getattr(self.instance, 'campanha', None)
        for item in attrs.get('itens', []):
            if item['peca'].campanha_id != campanha.id:
                raise serializers.ValidationError({'itens': 'Peça de outra campanha.'})
        if not (attrs.get('nome') or getattr(self.instance, 'nome', '')).strip():
            raise serializers.ValidationError({'nome': 'Informe o nome.'})
        return attrs

    def _salvar_itens(self, pedido, itens):
        existentes = {i.id: i for i in pedido.itens.all()}
        manter = set()
        for dados in itens:
            item_id = dados.pop('id', None)
            if item_id in existentes:
                item = existentes[item_id]
                for k, v in dados.items():
                    setattr(item, k, v)
                item.save()
                manter.add(item_id)
            else:
                manter.add(ItemPedido.objects.create(pedido=pedido, **dados).id)
        pedido.itens.exclude(id__in=manter).delete()

    @transaction.atomic
    def create(self, validated_data):
        itens = validated_data.pop('itens', [])
        pedido = Pedido.objects.create(**validated_data)
        self._salvar_itens(pedido, itens)
        return pedido

    @transaction.atomic
    def update(self, instance, validated_data):
        itens = validated_data.pop('itens', None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if itens is not None:
            self._salvar_itens(instance, itens)
        return instance
