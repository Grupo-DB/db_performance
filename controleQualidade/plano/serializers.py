from rest_framework import serializers

from controleQualidade.ensaio.models import Ensaio
from .models import PlanoAnalise

class PlanoAnaliseSerializer(serializers.ModelSerializer):
    ensaios = serializers.PrimaryKeyRelatedField(queryset=Ensaio.objects.all(), write_only=True, many=True)
    calculos_ensaio = serializers.PrimaryKeyRelatedField(queryset=PlanoAnalise.objects.all(), write_only=True, many=True)
    ensaio_detalhes = serializers.PrimaryKeyRelatedField(source='ensaios', read_only=True)
    calculo_ensaio_detalhes = serializers.PrimaryKeyRelatedField(source='calculos_ensaio', read_only=True)
    class Meta:
        model = PlanoAnalise
        fields = '__all__'