from rest_framework import serializers
from .models import Analise
from controleQualidade.amostra.serializers import AmostraSerializer
from controleQualidade.amostra.models import Amostra

class AnaliseSerializer(serializers.ModelSerializer):
    amostra = serializers.PrimaryKeyRelatedField(queryset=Amostra.objects.all(), write_only=True)
    amostra_detalhes = AmostraSerializer(source='amostra', read_only=True)
    class Meta:
        model = Analise
        fields = '__all__'



