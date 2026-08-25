from rest_framework import serializers
from .models import Amostra, TipoAmostra, ProdutoAmostra, AmostraImagem, GarantiaProduto
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

class GarantiaProdutoSerializer(serializers.ModelSerializer):
    produto = serializers.PrimaryKeyRelatedField(queryset=ProdutoAmostra.objects.all(), write_only=True)
    produto_detalhes = ProdutoAmostraSerializer(source='produto', read_only=True)
    class Meta:
        model = GarantiaProduto
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
    # `numero` é declarado à mão para ficar SEM o UniqueValidator que o
    # ModelSerializer criaria a partir do `unique=True` do model.
    # Motivo: no POST o número que chega do navegador é só a prévia do
    # formulário e é DESCARTADO — quem numera é `AmostraViewSet.perform_create`
    # (ver controleQualidade/amostra/numeracao.py). Com o validador, uma prévia
    # velha ("cal 00.0440" já usado) devolveria 400 em vez de a amostra nascer
    # com o próximo número livre. A duplicata na EDIÇÃO é barrada no validate()
    # abaixo, e o índice único do banco fecha a porta nos dois casos.
    numero = serializers.CharField(max_length=255, required=False, allow_blank=True, validators=[])
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

    def validate(self, attrs):
        """Na edição, impede trocar o número por um que já exista.

        Só na edição: no cadastro o valor recebido é ignorado (ver o comentário
        do campo `numero`). A comparação é `iexact` porque a collation do MySQL
        é insensível a acento e caixa — para o índice único 'CAL 00.0440' e
        'cal 00.0440' são o mesmo número.
        """
        numero = attrs.get('numero')
        if numero and self.instance is not None:
            ja_existe = (Amostra.objects
                         .filter(numero__iexact=numero.strip())
                         .exclude(pk=self.instance.pk)
                         .exists())
            if ja_existe:
                raise serializers.ValidationError(
                    {'numero': f'Já existe outra amostra com o número {numero}.'})
        return attrs

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
