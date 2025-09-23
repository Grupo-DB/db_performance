from rest_framework import serializers
from .models import Ordem, OrdemExpressa
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.plano.serializers import PlanoAnaliseSerializer
from controleQualidade.ensaio.serializers import EnsaioSerializer
from controleQualidade.plano.models import PlanoAnalise
from controleQualidade.calculosEnsaio.models import CalculoEnsaio
from controleQualidade.calculosEnsaio.serializers import CalculoEnsaioSerializer

class FlexibleManyRelatedField(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        if isinstance(data, list):
            return [super().to_internal_value(item) for item in data]
        return [super().to_internal_value(data)]


class OrdemSerializer(serializers.ModelSerializer):
    plano_analise = FlexibleManyRelatedField(queryset=PlanoAnalise.objects.all(), write_only=True)
    plano_detalhes = PlanoAnaliseSerializer(source='plano_analise',many=True, read_only=True)
    class Meta:
        model = Ordem
        fields = '__all__'

class OrdemExpressaSerializer(serializers.ModelSerializer):
    ensaios = FlexibleManyRelatedField(queryset=Ensaio.objects.all(), write_only=True)
    calculos_ensaio = FlexibleManyRelatedField(queryset=CalculoEnsaio.objects.all(), write_only=True)
    ensaio_detalhes = EnsaioSerializer(source='ensaios', read_only=True, many=True)
    calculo_ensaio_detalhes = CalculoEnsaioSerializer(source='calculos_ensaio', read_only=True, many=True)
    class Meta:
        model = OrdemExpressa
        fields = '__all__' 