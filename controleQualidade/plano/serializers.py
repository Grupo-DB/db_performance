from rest_framework import serializers
from controleQualidade.ensaio.serializers import EnsaioSerializer
from controleQualidade.calculosEnsaio.serializers import CalculoEnsaioSerializer
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.calculosEnsaio.models import CalculoEnsaio
from .models import PlanoAnalise

class FlexibleManyRelatedField(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        """Permite receber um único id ou uma lista de ids.

        Em Python 3.10 o uso de super() sem argumentos dentro de list comprehension
        pode perder o contexto de classe, gerando:
            TypeError: super(type, obj): obj must be an instance or subtype of type

        Para evitar isso, capturamos a função base antes da compreensão.
        """
        base_to_internal = super(FlexibleManyRelatedField, self).to_internal_value
        if isinstance(data, list):
            return [base_to_internal(item) for item in data]
        return [base_to_internal(data)]
    
class PlanoAnaliseSerializer(serializers.ModelSerializer):
    ensaios = FlexibleManyRelatedField(queryset=Ensaio.objects.all(), write_only=True)
    calculos_ensaio = FlexibleManyRelatedField(queryset=CalculoEnsaio.objects.all(), write_only=True)
    ensaio_detalhes = EnsaioSerializer(source='ensaios', read_only=True, many=True)
    calculo_ensaio_detalhes = CalculoEnsaioSerializer(source='calculos_ensaio', read_only=True, many=True)
    class Meta:
        model = PlanoAnalise
        fields = '__all__'