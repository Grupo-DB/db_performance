from baseOrcamentaria.dre.models import Produto
from baseOrcamentaria.dre.serializers import ProdutoSerializer
from baseOrcamentaria.orcamento.models import CentroCustoPai
from baseOrcamentaria.orcamento.serializers import CentroCustoPaiSerializer
from .models import CustoProducao
from rest_framework import serializers

class CustoProducaoSerializer(serializers.ModelSerializer):
    produto = serializers.PrimaryKeyRelatedField(queryset=Produto.objects.all(), write_only=True)
    produto_detalhes = ProdutoSerializer(source='produto', read_only=True)
    centro_custo_pai = serializers.PrimaryKeyRelatedField(queryset=CentroCustoPai.objects.all(), write_only=True)
    centro_custo_pai_detalhes = CentroCustoPaiSerializer(source='centro_custo_pai', read_only=True)
    class Meta:
        model = CustoProducao
        fields = '__all__'