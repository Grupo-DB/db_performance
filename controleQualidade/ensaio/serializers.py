from rest_framework import serializers
from .models import TipoEnsaio, Ensaio, Variavel

class TipoEnsaioSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoEnsaio
        fields = '__all__'
class VariavelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Variavel
        fields = '__all__'        
class EnsaioSerializer(serializers.ModelSerializer):
    tipo_ensaio = serializers.PrimaryKeyRelatedField(queryset=TipoEnsaio.objects.all(), write_only=True)
    tipo_ensaio_detalhes = TipoEnsaioSerializer(source='tipo_ensaio', read_only=True)
    variavel = serializers.PrimaryKeyRelatedField(queryset=Variavel.objects.all(), write_only=True, many=True)
    variavel_detalhes = VariavelSerializer(source='variavel', read_only=True, many=True)
    class Meta:
        model = Ensaio
        fields = '__all__'
        #fields = ['id', 'descricao', 'responsavel', 'valor', 'tipo_ensaio','tipo_ensaio_detalhes','tempo_previsto','variavel','variavel_detalhes','funcao']

    def create(self, validated_data):
        variaveis = validated_data.pop('variavel', [])
        ensaio = Ensaio.objects.create(**validated_data)
        ensaio.variavel.set(variaveis)
        return ensaio            