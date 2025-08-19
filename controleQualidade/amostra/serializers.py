from rest_framework import serializers

from baseOrcamentaria.dre.models import Produto
from baseOrcamentaria.dre.serializers import ProdutoSerializer
from .models import Amostra, TipoAmostra, ProdutoAmostra, AmostraImagem
from controleQualidade.ordem.serializers import OrdemSerializer, OrdemExpressaSerializer
from controleQualidade.ordem.models import Ordem, OrdemExpressa

class TipoAmostraSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAmostra
        fields = '__all__'

class ProdutoAmostraSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProdutoAmostra
        fields = '__all__'

class AmostraImagemSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    class Meta:
        model = AmostraImagem
        fields = '__all__'        

    def get_image_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.image.url)
        return None

class AmostraSerializer(serializers.ModelSerializer):
    ordem = serializers.PrimaryKeyRelatedField(queryset=Ordem.objects.all(), write_only=True, required=False, allow_null=True)
    ordem_detalhes = OrdemSerializer(source='ordem', read_only=True)
    expressa =  serializers.PrimaryKeyRelatedField(queryset=OrdemExpressa.objects.all(), write_only=True, required=False, allow_null=True)
    expressa_detalhes = OrdemExpressaSerializer(source='expressa', read_only=True)
    produto_amostra = serializers.PrimaryKeyRelatedField(queryset=ProdutoAmostra.objects.all(), write_only=True, required=False, allow_null=True)
    produto_amostra_detalhes = ProdutoAmostraSerializer(source='produto_amostra', read_only=True)
    imagens = AmostraImagemSerializer(many=True, read_only=True)
    uploaded_images = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False
    )
    class Meta:
        model = Amostra
        fields = '__all__'

    def create(self, validated_data):
        uploaded_images = validated_data.pop('uploaded_images', [])
        amostra = super().create(validated_data)
        
        # Cria as imagens associadas
        for image in uploaded_images:
            AmostraImagem.objects.create(
                amostra=amostra,
                image=image
            )
        
        return amostra
