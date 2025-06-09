from rest_framework import serializers
from .models import Ordem
from controleQualidade.plano.serializers import PlanoAnaliseSerializer
from controleQualidade.plano.models import PlanoAnalise
class OrdemSerializer(serializers.ModelSerializer):
    plano_analise = serializers.PrimaryKeyRelatedField(queryset=PlanoAnalise.objects.all(), write_only=True)
    plano_detalhes = PlanoAnaliseSerializer(source='plano_analise', read_only=True)
    class Meta:
        model = Ordem
        fields = '__all__'
    