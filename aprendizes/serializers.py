from rest_framework import serializers

from .models import Acompanhamento, Etapa


class EtapaSerializer(serializers.ModelSerializer):
    tipo_rotulo = serializers.CharField(source='get_tipo_display', read_only=True)
    situacao_rotulo = serializers.CharField(source='get_situacao_display', read_only=True)
    concluido_por_nome = serializers.SerializerMethodField()
    # Para a lista do mês, que mostra etapas de várias pessoas.
    nome = serializers.CharField(source='acompanhamento.nome', read_only=True)
    setor = serializers.CharField(source='acompanhamento.setor', read_only=True)
    cargo = serializers.CharField(source='acompanhamento.cargo', read_only=True)
    data_admissao = serializers.DateField(source='acompanhamento.data_admissao', read_only=True)
    situacao_pessoa = serializers.CharField(source='acompanhamento.situacao', read_only=True)

    class Meta:
        model = Etapa
        fields = [
            'id', 'acompanhamento', 'tipo', 'tipo_rotulo', 'vencimento', 'situacao', 'situacao_rotulo',
            'avaliacao_feita', 'feedback_dado', 'brinde_entregue', 'camiseta_entregue', 'plano_saude_informado',
            'pendencia', 'observacao', 'concluido_em', 'concluido_por_nome',
            'nome', 'setor', 'cargo', 'data_admissao', 'situacao_pessoa',
        ]
        read_only_fields = ['concluido_em']

    def get_concluido_por_nome(self, obj):
        u = obj.concluido_por
        if not u:
            return None
        colaborador = getattr(u, 'colaborador', None)
        return (colaborador.nome if colaborador else '') or u.get_full_name() or u.username


class AcompanhamentoSerializer(serializers.ModelSerializer):
    etapas = EtapaSerializer(many=True, read_only=True)
    situacao_rotulo = serializers.CharField(source='get_situacao_display', read_only=True)

    class Meta:
        model = Acompanhamento
        fields = [
            'id', 'colaborador', 'nome', 'setor', 'cargo', 'data_admissao', 'situacao', 'situacao_rotulo',
            'observacao', 'etapas', 'criado_em',
        ]

    def validate_nome(self, valor):
        if not valor.strip():
            raise serializers.ValidationError('Informe o nome.')
        return valor.strip()
