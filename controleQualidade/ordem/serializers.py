from rest_framework import serializers
from .models import Ordem, OrdemExpressa, OrdemExpressaEnsaio, OrdemExpressaCalculo
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.plano.serializers import PlanoAnaliseSerializer
from controleQualidade.ensaio.serializers import EnsaioSerializer
from controleQualidade.plano.models import PlanoAnalise
from controleQualidade.calculosEnsaio.models import CalculoEnsaio
from controleQualidade.calculosEnsaio.serializers import CalculoEnsaioSerializer

class FlexibleManyRelatedField(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        """Permite receber um único id ou uma lista de ids.

        Em Python 3.10 o uso de super() sem argumentos dentro de list comprehension
        pode perder o contexto de classe, gerando:
            TypeError: super(type, obj): obj must be an instance or subtype of type

        Para evitar isso, capturamos a função base antes da compreensão.
        """
        base_to_internal = super(FlexibleManyRelatedField, self).to_internal_value
        if isinstance(data, list):
            return [base_to_internal(item) for item in data]
        return [base_to_internal(data)]


class OrdemSerializer(serializers.ModelSerializer):
    plano_analise = FlexibleManyRelatedField(queryset=PlanoAnalise.objects.all(), write_only=True)
    plano_detalhes = PlanoAnaliseSerializer(source='plano_analise',many=True, read_only=True)
    class Meta:
        model = Ordem
        fields = '__all__'

class OrdemExpressaSerializer(serializers.ModelSerializer):
    ensaio_detalhes = serializers.SerializerMethodField()
    calculo_ensaio_detalhes = serializers.SerializerMethodField()
    
    def get_ensaio_detalhes(self, obj):
        """Retorna ensaios da tabela intermediária com info de laboratório"""
        try:
            ensaios_intermediarios = obj.ensaios_intermediarios.all().order_by('ordem')
                        
            result = []
            for item in ensaios_intermediarios:
                ensaio_data = EnsaioSerializer(item.ensaio).data
                ensaio_data['laboratorio'] = item.laboratorio
                result.append(ensaio_data)
            
            return result
        except Exception as e:
            print(f"[ERRO] Erro ao buscar ensaios: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_calculo_ensaio_detalhes(self, obj):
        """Retorna cálculos da tabela intermediária com info de laboratório"""
        try:
            calculos_intermediarios = obj.calculos_intermediarios.all().order_by('ordem')
                        
            result = []
            for item in calculos_intermediarios:
                calculo_data = CalculoEnsaioSerializer(item.calculo).data
                #  Adicionar laboratório para controle de edição
                calculo_data['laboratorio'] = item.laboratorio
                result.append(calculo_data)
            
            return result
        except Exception as e:
            print(f"[ERRO] Erro ao buscar cálculos: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    class Meta:
        model = OrdemExpressa
        fields = '__all__'