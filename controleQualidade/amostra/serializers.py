from rest_framework import serializers
from .models import Amostra, TipoAmostra, Produto

class TipoAmostraSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAmostra
        fields = '__all__'
        
class ProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Produto
        fields = '__all__'

class AmostraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Amostra
        fields = '__all__'