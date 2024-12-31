from rest_framework import serializers
from .models import Linha,Produto

    
class ProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Produto
        fields = '__all__'    

class LinhaSerializer(serializers.ModelSerializer):
    # Para escrita, aceita apenas IDs
    produto = serializers.PrimaryKeyRelatedField(queryset=Produto.objects.all(), write_only=True)
    # Para leitura, retorna os dados completos
    produto_detalhes = ProdutoSerializer(source='produto', read_only=True)
    class Meta:
        model = Linha
        fields= '__all__'        