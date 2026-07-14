from rest_framework import serializers

from .models import Aplicacao, Banco, Credor, Empresa, Resgate


class CredorSerializer(serializers.ModelSerializer):
    # SerializerMethodField em vez de DecimalField: capital_total só existe quando o
    # queryset foi anotado (CredorViewSet); em serializações aninhadas (ex.: dentro de
    # Aplicacao) o atributo não existe, e um DecimalField normal levantaria AttributeError.
    capital_total = serializers.SerializerMethodField()

    class Meta:
        model = Credor
        fields = [
            'id', 'nome', 'cpf', 'rg', 'endereco', 'bairro', 'cidade', 'estado',
            'ativo', 'capital_total', 'created_at', 'updated_at',
        ]

    def get_capital_total(self, obj):
        return getattr(obj, 'capital_total', None)


class EmpresaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empresa
        fields = ['id', 'nome', 'local', 'cnpj', 'endereco', 'ativo', 'created_at', 'updated_at']


class BancoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Banco
        fields = ['id', 'codigo', 'nome']


class ResgateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resgate
        fields = [
            'id', 'aplicacao', 'data_resgate', 'valor_resgatado', 'juros_periodo',
            'tipo', 'observacoes', 'created_at',
        ]

    def validate(self, attrs):
        aplicacao = attrs.get('aplicacao') or getattr(self.instance, 'aplicacao', None)
        valor_resgatado = attrs.get('valor_resgatado')
        tipo = attrs.get('tipo')
        if aplicacao and valor_resgatado is not None:
            if tipo == Resgate.TIPO_PARCIAL and valor_resgatado >= aplicacao.valor_aplicacao:
                raise serializers.ValidationError(
                    'Resgate parcial deve ser menor que o valor total aplicado. Use tipo "total" para resgatar tudo.'
                )
            if valor_resgatado > aplicacao.valor_aplicacao:
                raise serializers.ValidationError('Valor resgatado maior que o valor aplicado.')
        return attrs

    def create(self, validated_data):
        resgate = super().create(validated_data)
        aplicacao = resgate.aplicacao
        if resgate.tipo == Resgate.TIPO_TOTAL:
            aplicacao.status = Aplicacao.STATUS_RESGATE_TOTAL
        else:
            aplicacao.valor_aplicacao = aplicacao.valor_aplicacao - resgate.valor_resgatado
            aplicacao.status = Aplicacao.STATUS_RESGATE_PARCIAL
        aplicacao.save()
        return resgate


class AplicacaoListSerializer(serializers.ModelSerializer):
    credor_nome = serializers.CharField(source='credor.nome', read_only=True)
    empresa_nome = serializers.CharField(source='empresa.nome', read_only=True)
    banco_nome = serializers.CharField(source='banco.nome', read_only=True, default=None)

    class Meta:
        model = Aplicacao
        fields = [
            'id', 'numero_contrato', 'credor', 'credor_nome', 'empresa', 'empresa_nome',
            'banco', 'banco_nome', 'data_aplicacao', 'valor_aplicacao', 'taxa',
            'dia_vencimento', 'juros', 'irrf', 'liquido', 'status', 'vencimento_contrato',
        ]


class AplicacaoDetailSerializer(serializers.ModelSerializer):
    credor_nome = serializers.CharField(source='credor.nome', read_only=True)
    empresa_nome = serializers.CharField(source='empresa.nome', read_only=True)
    credor_detalhes = CredorSerializer(source='credor', read_only=True)
    empresa_detalhes = EmpresaSerializer(source='empresa', read_only=True)
    banco_detalhes = BancoSerializer(source='banco', read_only=True)
    resgates = ResgateSerializer(many=True, read_only=True)

    class Meta:
        model = Aplicacao
        fields = [
            'id', 'numero_contrato', 'ano_referencia', 'credor', 'credor_nome', 'credor_detalhes',
            'empresa', 'empresa_nome', 'empresa_detalhes', 'banco', 'banco_detalhes',
            'data_aplicacao', 'data_renovacao', 'valor_aplicacao', 'taxa', 'dia_vencimento',
            'agencia', 'conta', 'titular_conta', 'observacoes', 'status',
            'juros', 'parcela_ajustada', 'liquido', 'irrf', 'descendio', 'vencimento_contrato',
            'resgates', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'numero_contrato', 'juros', 'parcela_ajustada', 'liquido', 'irrf',
            'descendio', 'vencimento_contrato',
        ]


class AplicacaoCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Aplicacao
        fields = [
            'id', 'credor', 'empresa', 'banco', 'data_aplicacao', 'data_renovacao',
            'valor_aplicacao', 'taxa', 'dia_vencimento', 'agencia', 'conta',
            'titular_conta', 'observacoes', 'status', 'ano_referencia',
        ]

    def to_representation(self, instance):
        return AplicacaoDetailSerializer(instance, context=self.context).data
