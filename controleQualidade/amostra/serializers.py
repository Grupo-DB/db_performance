from rest_framework import serializers
from .models import Amostra, TipoAmostra, ProdutoAmostra
from controleQualidade.ordem.serializers import OrdemSerializer
from controleQualidade.ordem.models import Ordem

class TipoAmostraSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAmostra
        fields = '__all__'

class ProdutoAmostraSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProdutoAmostra
        fields = '__all__'

class AmostraSerializer(serializers.ModelSerializer):
    ordem = serializers.PrimaryKeyRelatedField(queryset=Ordem.objects.all(), write_only=True)
    ordem_detalhes = OrdemSerializer(source='ordem', read_only=True)
    class Meta:
        model = Amostra
        fields = '__all__'