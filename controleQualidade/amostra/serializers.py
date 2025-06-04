from rest_framework import serializers
from .models import Amostra, TipoAmostra, ProdutoAmostra

class TipoAmostraSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAmostra
        fields = '__all__'

class ProdutoAmostraSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProdutoAmostra
        fields = '__all__'

class AmostraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Amostra
        fields = '__all__'