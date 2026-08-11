from rest_framework import serializers

from .models import VisitaTecnica, VisitaTecnicaImagem


class VisitaTecnicaImagemSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = VisitaTecnicaImagem
        fields = '__all__'

    def get_image_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.image.url)
        return None


class VisitaTecnicaSerializer(serializers.ModelSerializer):
    imagens = VisitaTecnicaImagemSerializer(many=True, read_only=True)
    # Mesmo contrato de `AmostraSerializer`: o frontend manda os arquivos em
    # `uploaded_images` no mesmo POST/PATCH da visita. `cps_imagens` diz, na mesma
    # ordem, a qual corpo de prova cada arquivo pertence (vazio = foto geral).
    uploaded_images = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False
    )
    cps_imagens = serializers.ListField(
        child=serializers.IntegerField(allow_null=True),
        write_only=True,
        required=False
    )
    # E a qual ensaio (1 = o primeiro). Omitido = primeiro, que é como as fotos
    # anteriores a vários ensaios ficaram gravadas.
    ensaios_imagens = serializers.ListField(
        child=serializers.IntegerField(allow_null=True),
        write_only=True,
        required=False
    )

    class Meta:
        model = VisitaTecnica
        fields = '__all__'

    def _criar_imagens(self, visita, arquivos, cps, ensaios):
        for indice, arquivo in enumerate(arquivos):
            cp = cps[indice] if indice < len(cps) else None
            ensaio = ensaios[indice] if indice < len(ensaios) else None
            VisitaTecnicaImagem.objects.create(visita=visita, image=arquivo, cp=cp, ensaio=ensaio)

    def create(self, validated_data):
        arquivos = validated_data.pop('uploaded_images', [])
        cps = validated_data.pop('cps_imagens', [])
        ensaios = validated_data.pop('ensaios_imagens', [])
        visita = super().create(validated_data)
        self._criar_imagens(visita, arquivos, cps, ensaios)
        return visita

    def update(self, instance, validated_data):
        # As fotos são ACRESCENTADAS: um PATCH de dados do formulário não pode
        # apagar o que o técnico já subiu da obra. Para remover uma foto existe o
        # endpoint próprio de VisitaTecnicaImagem (DELETE).
        arquivos = validated_data.pop('uploaded_images', [])
        cps = validated_data.pop('cps_imagens', [])
        ensaios = validated_data.pop('ensaios_imagens', [])
        visita = super().update(instance, validated_data)
        self._criar_imagens(visita, arquivos, cps, ensaios)
        return visita
