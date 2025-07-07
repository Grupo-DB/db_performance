from rest_framework import serializers
from .models import Ordem, OrdemExpressa
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.plano.serializers import PlanoAnaliseSerializer
from controleQualidade.ensaio.serializers import EnsaioSerializer
from controleQualidade.plano.models import PlanoAnalise
from controleQualidade.calculosEnsaio.models import CalculoEnsaio
from controleQualidade.calculosEnsaio.serializers import CalculoEnsaioSerializer

class OrdemSerializer(serializers.ModelSerializer):
    plano_analise = serializers.PrimaryKeyRelatedField(queryset=PlanoAnalise.objects.all(),many=True, write_only=True)
    plano_detalhes = PlanoAnaliseSerializer(source='plano_analise',many=True, read_only=True)
    class Meta:
        model = Ordem
        fields = '__all__'

class OrdemExpressaSerializer(serializers.ModelSerializer):
    ensaio = serializers.PrimaryKeyRelatedField(queryset=Ensaio.objects.all(), many=True, write_only=True)
    ensaio_detalhes = EnsaioSerializer(source='ensaio', many=True, read_only=True)
    calculo = serializers.PrimaryKeyRelatedField(queryset=CalculoEnsaio.objects.all(), many=True, write_only=True)
    calculo_detalhes = CalculoEnsaioSerializer(source='calculo', many=True, read_only=True)
    class Meta:
        model = OrdemExpressa
        fields = '__all__' 