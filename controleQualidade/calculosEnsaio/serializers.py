from rest_framework import serializers
from controleQualidade.ensaio.models import Ensaio, Variavel
from controleQualidade.ensaio.serializers import EnsaioSerializer, VariavelSerializer
from .models import CalculoEnsaio


class CalculoEnsaioSerializer(serializers.ModelSerializer):
    ensaios = serializers.PrimaryKeyRelatedField(queryset=Ensaio.objects.all(), write_only=True, many=True)
    ensaios_detalhes = EnsaioSerializer(source='ensaios', read_only=True, many=True)
    variavel = serializers.PrimaryKeyRelatedField(queryset=Variavel.objects.all(), write_only=True, many=True)
    variavel_detalhes = VariavelSerializer(source='variavel', read_only=True, many=True)
    class Meta:
        model = CalculoEnsaio
        fields = '__all__'

    def create(self, validated_data):
        variaveis = validated_data.pop('variavel', [])
        calculoEnsaio = CalculoEnsaio.objects.create(**validated_data)
        calculoEnsaio.variavel.set(variaveis)
        return calculoEnsaio

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