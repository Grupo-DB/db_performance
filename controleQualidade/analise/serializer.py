from rest_framework import serializers
from .models import Analise, AnaliseCalculo, AnaliseEnsaio
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.amostra.serializers import AmostraSerializer
from controleQualidade.amostra.models import Amostra

class AnaliseSerializer(serializers.ModelSerializer):
    amostra = serializers.PrimaryKeyRelatedField(queryset=Amostra.objects.all(), write_only=True)
    amostra_detalhes = AmostraSerializer(source='amostra', read_only=True)
    ensaios = serializers.ListField(write_only=True, required=False)
    calculos = serializers.ListField(write_only=True, required=False)
    class Meta:
        model = Analise
        fields = '__all__'

    def update(self, instance, validated_data):
        ensaios_data = validated_data.pop('ensaios', [])
        calculos_data = validated_data.pop('calculos', [])
        print("Dados recebidos para atualização:", validated_data)
        # Atualize campos simples
        instance.estado = validated_data.get('estado', instance.estado)
        instance.save()

        # Atualize ou crie ensaios
        for ensaio_data in ensaios_data:
            AnaliseEnsaio.objects.update_or_create(
                analise=instance,
                ensaios_id=ensaio_data['ensaios'],
                defaults={
                    'valores': ensaio_data.get('valores'),
                    'resultados': ensaio_data.get('resultados')
                }
            )

        # Atualize ou crie cálculos
        for calculo_data in calculos_data:
            AnaliseCalculo.objects.update_or_create(
                analise=instance,
                calculos=calculo_data['calculos'],
                defaults={
                    'valores': calculo_data.get('valores'),
                    'resultados': calculo_data.get('resultados')
                }
            )

        return instance


class AnaliseEnsaioSerializer(serializers.ModelSerializer):
    analise = serializers.PrimaryKeyRelatedField(queryset=Analise.objects.all(), write_only=True)
    analise_detalhes = AnaliseSerializer(source='analise', read_only=True)
    ensaios = serializers.PrimaryKeyRelatedField(queryset=Ensaio.objects.all(), write_only=True)
    ensaios_detalhes = AmostraSerializer(source='ensaios', read_only=True)
    class Meta:
        model = AnaliseEnsaio
        fields = '__all__'
       
class AnaliseCalculoSerializer(serializers.ModelSerializer):
    analise = serializers.PrimaryKeyRelatedField(queryset=Analise.objects.all(), write_only=True)
    analise_detalhes = AnaliseSerializer(source='analise', read_only=True)
    class Meta:
        model = AnaliseCalculo
        fields = '__all__'
