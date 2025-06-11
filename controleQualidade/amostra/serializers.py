from rest_framework import serializers

from baseOrcamentaria.dre.models import Produto
from baseOrcamentaria.dre.serializers import ProdutoSerializer
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
    ordem = serializers.PrimaryKeyRelatedField(queryset=Ordem.objects.all(), write_only=True, required=False, allow_null=True)
    ordem_detalhes = OrdemSerializer(source='ordem', read_only=True)
    material = serializers.PrimaryKeyRelatedField(queryset=Produto.objects.all(), write_only=True, required=False, allow_null=True)
    material_detalhes = ProdutoSerializer(source='material', read_only=True)
    tipo_amostra = serializers.PrimaryKeyRelatedField(queryset=TipoAmostra.objects.all(), write_only=True, required=False, allow_null=True)
    tipo_amostra_detalhes = TipoAmostraSerializer(source='tipo_amostra', read_only=True)
    produto_amostra = serializers.PrimaryKeyRelatedField(queryset=ProdutoAmostra.objects.all(), write_only=True, required=False, allow_null=True)
    produto_amostra_detalhes = ProdutoAmostraSerializer(source='produto_amostra', read_only=True)
    class Meta:
        model = Amostra
        fields = '__all__'