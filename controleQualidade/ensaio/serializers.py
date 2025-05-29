from rest_framework import serializers
from .models import TipoEnsaio, Ensaio

class TipoEnsaioSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoEnsaio
        fields = '__all__'
        
class EnsaioSerializer(serializers.ModelSerializer):
    tipo_ensaio = serializers.PrimaryKeyRelatedField(queryset=TipoEnsaio.objects.all(), write_only=True)
    tipo_ensaio_detalhes = TipoEnsaioSerializer(source='tipo_ensaio', read_only=True)
    class Meta:
        model = Ensaio
        #fields = '__all__'
        fields = ['id', 'descricao', 'responsavel', 'valor', 'tipo_ensaio','tipo_ensaio_detalhes','tempo_previsto']        