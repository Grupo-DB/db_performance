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
    ensaios = AnaliseEnsaioSerializer(many=True, read_only=True)
    calculos = AnaliseCalculoSerializer(many=True, read_only=True)
    ensaios_write = serializers.ListField(write_only=True, required=False)
    
    calculos_write = serializers.ListField(write_only=True, required=False)
    #ensaios_calc = AnaliseEnsaioSerializer(many=True, read_only=True)
    #calculos_calc = AnaliseCalculoSerializer(many=True, read_only=True)

    class Meta:
        model = Analise
        fields = '__all__'

    def update(self, instance, validated_data):
        ensaios_data = validated_data.pop('ensaios', [])
        calculos_data = validated_data.pop('calculos', [])

        print("UPDATE SERIALIZER")
        print("ensaios_data:", ensaios_data)
        print("calculos_data:", calculos_data)

        # Atualiza os campos normais da análise
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Atualiza ou cria ensaios
        for ensaio in ensaios_data:
            if 'id' in ensaio:
                AnaliseEnsaio.objects.filter(id=ensaio['id']).update(
                    valor=ensaio.get('valor'),
                    responsavel=ensaio.get('responsavel'),
                    digitador=ensaio.get('digitador'),
                    # outros campos...
                )
            else:
                AnaliseEnsaio.objects.create(
                    analise=instance,
                    valor=ensaio.get('valor'),
                    responsavel=ensaio.get('responsavel'),
                    digitador=ensaio.get('digitador'),
                    # outros campos...
                )

        # Atualiza ou cria cálculos
        for calc in calculos_data:
            if 'id' in calc:
                AnaliseCalculo.objects.filter(id=calc['id']).update(
                    resultados=calc.get('resultado'),
                    responsavel=calc.get('responsavel'),
                    digitador=calc.get('digitador'),
                    # outros campos...
                )
            else:
                AnaliseCalculo.objects.create(
                    analise=instance,
                    resultados=calc.get('resultado'),
                    responsavel=calc.get('responsavel'),
                    digitador=calc.get('digitador'),
                    # outros campos...
                )

        return instance


# class AnaliseEnsaioSerializer(serializers.ModelSerializer):
#     analise = serializers.PrimaryKeyRelatedField(queryset=Analise.objects.all(), write_only=True)
#     analise_detalhes = AnaliseSerializer(source='analise', read_only=True)
#     ensaios = serializers.PrimaryKeyRelatedField(queryset=Ensaio.objects.all(), write_only=True)
#     ensaios_detalhes = AmostraSerializer(source='ensaios', read_only=True)
#     class Meta:
#         model = AnaliseEnsaio
#         fields = '__all__'
       
# class AnaliseCalculoSerializer(serializers.ModelSerializer):
#     analise = serializers.PrimaryKeyRelatedField(queryset=Analise.objects.all(), write_only=True)
#     analise_detalhes = AnaliseSerializer(source='analise', read_only=True)
#     class Meta:
#         model = AnaliseCalculo
#         fields = '__all__'
