from rest_framework import serializers
from controleQualidade.ensaio.serializers import EnsaioSerializer
from controleQualidade.calculosEnsaio.serializers import CalculoEnsaioSerializer
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.calculosEnsaio.models import CalculoEnsaio
from .models import PlanoAnalise

class FlexibleManyRelatedField(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        if isinstance(data, list):
            return [super().to_internal_value(item) for item in data]
        return [super().to_internal_value(data)]
    
class PlanoAnaliseSerializer(serializers.ModelSerializer):
    ensaios = FlexibleManyRelatedField(queryset=Ensaio.objects.all(), write_only=True)
    calculos_ensaio = FlexibleManyRelatedField(queryset=CalculoEnsaio.objects.all(), write_only=True)
    ensaio_detalhes = EnsaioSerializer(source='ensaios', read_only=True, many=True)
    calculo_ensaio_detalhes = CalculoEnsaioSerializer(source='calculos_ensaio', read_only=True, many=True)
    class Meta:
        model = PlanoAnalise
        fields = '__all__'