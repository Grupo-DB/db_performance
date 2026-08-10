from rest_framework import serializers

from .models import IndicadorBoletim, ResultadoBoletim


class IndicadorBoletimSerializer(serializers.ModelSerializer):
    ensaio_descricao = serializers.CharField(source='ensaio.descricao', read_only=True, default='')
    componentes_nomes = serializers.SerializerMethodField()

    class Meta:
        model = IndicadorBoletim
        fields = [
            'id', 'bloco', 'bloco_titulo', 'nome', 'ordem', 'ativo', 'agregacao', 'pai',
            'ensaio', 'ensaio_descricao', 'ensaio_nome', 'campo_especial',
            'peneira_malha', 'peneira_metrica',
            'material', 'tipo_amostra', 'local_coleta', 'finalidade', 'produtos', 'campo_data',
            'unidade', 'casas_decimais', 'tipo_limite', 'valor_limite',
            'producao_codigos', 'producao_etapa', 'observacao', 'componentes_nomes',
        ]

    def get_componentes_nomes(self, obj):
        return [c.nome for c in obj.componentes.all()]


class ResultadoBoletimSerializer(serializers.ModelSerializer):
    usuario_nome = serializers.CharField(source='usuario.username', read_only=True, default='')

    class Meta:
        model = ResultadoBoletim
        fields = [
            'id', 'indicador', 'ano', 'semana', 'valor', 'texto', 'producao',
            'observacao', 'usuario', 'usuario_nome', 'atualizado_em',
        ]
        read_only_fields = ['usuario', 'atualizado_em']

    def validate_semana(self, semana):
        if not 1 <= semana <= 53:
            raise serializers.ValidationError('Semana ISO vai de 1 a 53.')
        return semana
