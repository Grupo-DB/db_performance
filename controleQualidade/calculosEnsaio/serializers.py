from rest_framework import serializers
from controleQualidade.ensaio.models import Ensaio, Variavel
from controleQualidade.ensaio.serializers import EnsaioSerializer, VariavelSerializer
from .models import CalculoEnsaio


class CalculoEnsaioSerializer(serializers.ModelSerializer):
    ensaios = serializers.PrimaryKeyRelatedField(queryset=Ensaio.objects.all(), write_only=True, many=True, required=False, allow_empty=True)
    ensaios_detalhes = EnsaioSerializer(source='ensaios', read_only=True, many=True)
    #variavel = serializers.PrimaryKeyRelatedField(queryset=Variavel.objects.all(), write_only=True, many=True)
    #variavel_detalhes = VariavelSerializer(source='variavel', read_only=True, many=True)
    
    def to_internal_value(self, data):
        # Converte string vazia em lista vazia antes da validação
        if 'ensaios' in data and data['ensaios'] == "":
            data = data.copy()  # Cria uma cópia para não modificar o original
            data['ensaios'] = []
        
        # Faz o mesmo para responsavel se for string vazia
        if 'responsavel' in data and data['responsavel'] == "":
            data = data.copy()
            data['responsavel'] = None
            
        return super().to_internal_value(data)
    
    class Meta:
        model = CalculoEnsaio
        fields = '__all__'

    # def create(self, validated_data):
    #     variaveis = validated_data.pop('variavel', [])
    #     calculoEnsaio = CalculoEnsaio.objects.create(**validated_data)
    #     calculoEnsaio.variavel.set(variaveis)
    #     return calculoEnsaio

    def update(self, instance, validated_data):
        variaveis = validated_data.pop('variavel', None)
        ensaios = validated_data.pop('ensaios', None)
        
        # Atualiza os campos normalmente
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Atualiza os ensaios se fornecidos
        if ensaios is not None:
            instance.ensaios.set(ensaios)
        
        # Atualiza as variáveis se fornecidas
        if variaveis is not None:
            instance.variavel.set(variaveis)
        
        instance.save()
        return instance