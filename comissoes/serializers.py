from rest_framework import serializers
from .models import Comissao, Meta, Regiao, Representante


class RegiaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Regiao
        fields = ['id', 'nome']

class RepresentanteSerializer(serializers.ModelSerializer):
    regiao = serializers.PrimaryKeyRelatedField(queryset=Regiao.objects.all(), write_only=True)
    regiao_detalhes = RegiaoSerializer(source='regiao', read_only=True)
    class Meta:
        model = Representante
        fields = [
            'id', 
            'nome',
            'empresa', 
            'vendededor_externo', 
            'vendedor_interno', 
            'regiao', 
            'segmento', 
            'email', 
            'telefone', 
            'cpf', 
            'cnpj', 
            'regiao_detalhes'
        ]

class MetaSerializer(serializers.ModelSerializer):
    representante = serializers.PrimaryKeyRelatedField(queryset=Representante.objects.all(), write_only=True)
    representante_detalhes = RepresentanteSerializer(source='representante', read_only=True)
    regiao = serializers.PrimaryKeyRelatedField(queryset=Regiao.objects.all(), write_only=True)
    regiao_detalhes = RegiaoSerializer(source='regiao', read_only=True)
    class Meta:
        model = Meta
        fields = [
            'id', 
            'regiao', 
            'representante', 
            'segmento', 
            'valor', 
            'periodo', 
            'data_meta', 
            'representante_detalhes', 
            'regiao_detalhes'
        ]

class ComissaoSerializer(serializers.ModelSerializer):
    representante = serializers.PrimaryKeyRelatedField(queryset=Representante.objects.all(), write_only=True)
    representante_detalhes = RepresentanteSerializer(source='representante', read_only=True)
    class Meta:
        model = Comissao
        fields = [
            'id', 
            'representante', 
            'valor', 
            'periodo', 
            'data_pagamento', 
            'representante_detalhes'
        ]