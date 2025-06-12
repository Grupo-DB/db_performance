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

        instance.estado = validated_data.get('estado', instance.estado)
        instance.save()

        # Atualize ou crie ensaios
        for ensaio_data in ensaios_data:
            ensaios_utilizados = ensaio_data.get('ensaios_utilizados', [])
            responsavel = ensaio_data.get('responsavel')
            if isinstance(responsavel, dict):
                responsavel = responsavel.get('value')  # pega o valor se vier como objeto
            digitador = ensaio_data.get('digitador')
            AnaliseEnsaio.objects.update_or_create(
                analise=instance,
                ensaios_id=ensaio_data['id'],
                defaults={
                    'valores': ensaio_data.get('valores'),
                    'resultados': ensaio_data.get('resultados'),
                    'ensaios_utilizados': ensaios_utilizados,
                    'responsavel': responsavel,
                    'digitador': digitador,
                }
            )

        for calculo_data in calculos_data:
            ensaios_utilizados = calculo_data.get('ensaios_utilizados', [])
            responsavel = calculo_data.get('responsavel')
            if isinstance(responsavel, dict):
                responsavel = responsavel.get('value')
            digitador = calculo_data.get('digitador')
            AnaliseCalculo.objects.update_or_create(
                analise=instance,
                calculos=calculo_data['calculos'],
                defaults={
                    'valores': calculo_data.get('valores'),
                    'resultados': calculo_data.get('resultados'),
                    'ensaios_utilizados': ensaios_utilizados,
                    'responsavel': responsavel,
                    'digitador': digitador,
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
