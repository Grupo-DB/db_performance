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
    
    # Mudança aqui: usar CharField primeiro, depois converter
    valor = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    
    def validate_valor(self, value):
        # Se é None, string vazia ou 'null', retorna None
        if value is None or value == '' or value == 'null' or value == 'undefined':
            return None
        
        # Tenta converter para float
        try:
            return float(value)
        except (ValueError, TypeError):
            raise serializers.ValidationError("Valor deve ser um número válido ou vazio.")
    
    class Meta:
        model = Ensaio
        fields = '__all__'

    def create(self, validated_data):
        variaveis = validated_data.pop('variavel', [])
        ensaio = Ensaio.objects.create(**validated_data)
        ensaio.variavel.set(variaveis)
        return ensaio

    def update(self, instance, validated_data):
        variaveis = validated_data.pop('variavel', None)
        
        # Atualiza os campos normalmente
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Atualiza as variáveis se fornecidas
        if variaveis is not None:
            instance.variavel.set(variaveis)
        
        instance.save()
        return instance