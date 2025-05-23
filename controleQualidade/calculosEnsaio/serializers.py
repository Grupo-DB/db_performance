from rest_framework import serializers
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.ensaio.serializers import EnsaioSerializer
from .models import CalculoEnsaio


class CalculoEnsaioSerializer(serializers.ModelSerializer):
    ensaios = serializers.PrimaryKeyRelatedField(queryset=Ensaio.objects.all(), write_only=True, many=True)
    ensaios_detalhes = EnsaioSerializer(source='ensaios', read_only=True, many=True)
    class Meta:
        model = CalculoEnsaio
        fields = '__all__'