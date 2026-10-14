from rest_framework import serializers
from .models import Despesa, DocumentoAnexo


class DocumentoAnexoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoAnexo
        fields = ['id', 'arquivo', 'nome_original', 'created_at', 'created_by']


class DespesaSerializer(serializers.ModelSerializer):
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)
    status_rotulo = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Despesa
        fields = [
            'id',
            'colaborador',
            'usuario',
            'tipo',
            'descricao',
            'data',
            'valor',
            'anexo',
            'anexos',
            'created_at',
            'status',
            'status_rotulo',
            'lancada',
            'reembolsavel',
            'aprovado_por',
            'aprovado_em',
            'motivo_recusa',
            'lancada_por',
            'lancada_em',
            'reembolsada',
            'reembolsada_em',
            'reembolsada_por',
        ]
        # Quem lança é a pessoa logada; só o gestor informa outro colaborador.
        extra_kwargs = {'colaborador': {'required': False}}
        # O fluxo só anda pelas ações (aprovar, recusar, lançar, reembolsar).
        read_only_fields = [
            'usuario', 'created_at', 'status', 'lancada', 'aprovado_por', 'aprovado_em', 'motivo_recusa',
            'lancada_por', 'lancada_em', 'reembolsada', 'reembolsada_em', 'reembolsada_por',
        ]

    def validate_valor(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Informe um valor maior que zero.')
        return value

    def validate(self, attrs):
        tipo = attrs.get('tipo', getattr(self.instance, 'tipo', None))
        descricao = attrs.get('descricao', getattr(self.instance, 'descricao', '')) or ''
        if tipo == 'outros' and not descricao.strip():
            raise serializers.ValidationError({'descricao': 'Descreva a despesa quando o tipo for "Outros".'})
        return attrs
