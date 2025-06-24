from rest_framework import serializers
from .models import Analise, AnaliseCalculo, AnaliseEnsaio
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.amostra.serializers import AmostraSerializer
from controleQualidade.amostra.models import Amostra


class AnaliseEnsaioSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnaliseEnsaio
        fields = '__all__'

class AnaliseCalculoSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnaliseCalculo
        fields = '__all__'


class AnaliseSerializer(serializers.ModelSerializer):
    amostra = serializers.PrimaryKeyRelatedField(queryset=Amostra.objects.all(), write_only=True)
    amostra_detalhes = AmostraSerializer(source='amostra', read_only=True)
    ensaios = AnaliseEnsaioSerializer(many=True, required=False, write_only=True)
    calculos = AnaliseCalculoSerializer(many=True, required=False, write_only=True)
    ensaios_detalhes = AnaliseEnsaioSerializer(source='ensaios', many=True, read_only=True)
    calculos_detalhes = AnaliseCalculoSerializer(source='calculos', many=True, read_only=True)
    ultimo_ensaio = serializers.SerializerMethodField(read_only=True)
    ultimo_calculo = serializers.SerializerMethodField(read_only=True) 
    class Meta:
        model = Analise
        fields = '__all__'

    def get_ultimo_ensaio(self, obj):
        ultimo = obj.ensaios.order_by('-id').first()
        if ultimo:
            return AnaliseEnsaioSerializer(ultimo).data
        return None
    def get_ultimo_calculo(self, obj):
        ultimo = obj.calculos.order_by('-id').first()
        if ultimo:
            return AnaliseCalculoSerializer(ultimo).data
        return None 

    def update(self, instance, validated_data):
        ensaios_data = validated_data.pop('ensaios', [])
        calculos_data = validated_data.pop('calculos', [])
        
        # Atualiza os campos normais da análise
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Salva ensaios
        for ensaio in ensaios_data:
            AnaliseEnsaio.objects.create(
                analise=instance,
                ensaios_utilizados=ensaio.get('ensaios_utilizados', []),
                responsavel=ensaio.get('responsavel'),
                digitador=ensaio.get('digitador'),
                ensaios=ensaio.get('ensaios'), # se enviar o id do ensaio
            )
            
        # Salva cálculos
        for calc in calculos_data:
            AnaliseCalculo.objects.create(
                analise=instance,
                calculos=calc.get('calculos'),
                resultados=calc.get('resultados'),
                ensaios_utilizados=calc.get('ensaios_utilizados', []),
                responsavel=calc.get('responsavel'),
                digitador=calc.get('digitador'),
            )

        return instance

