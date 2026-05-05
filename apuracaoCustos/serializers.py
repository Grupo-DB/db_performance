from rest_framework import serializers
from .models import Local, Royalty, Fatura

class LocalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Local
        fields = [
            'id', 
            'nome', 
            'periodo', 
            'data', 
            'ponto', 
            'consumo', 
            'producao', 
            'produtividade', 
            #'custo'
        ]

class RoyaltySerializer(serializers.ModelSerializer):
    class Meta:
        model = Royalty
        fields = [
            'id', 
            'periodo', 
            'tn_britada', 
            'dif_tn_britada', 
            'tn_expedida', 
            'dif_tn_expedida', 
            'valor_unitario_tn', 
            'valor_total', 
            'referencia_entrada'
        ]

class FaturaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fatura
        fields = [
            'id', 
            'periodo', 
            #'fornecedor', 
            'total_servico', 
            'total_produto',
            'total_geral'
        ]   
