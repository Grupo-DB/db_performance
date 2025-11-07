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

    # def get_ultimo_calculo(self, obj):
    #     ultimo = obj.calculos.order_by('-id')
    #     if ultimo:
    #         return AnaliseCalculoSerializer(ultimo).data
    #     return None
    
    def get_ultimo_calculo(self, obj):
        calculos = obj.calculos.order_by('-id')
        if calculos.exists():
            calculos_lista = []
            calculos_tipos_vistos = set()  # Para controlar quais tipos já foram adicionados
            
            for calculo in calculos:
                # Se já temos este tipo de cálculo, pula
                if calculo.calculos in calculos_tipos_vistos:
                    continue
                
                calculos_tipos_vistos.add(calculo.calculos)
                data = AnaliseCalculoSerializer(calculo).data
                
                # Busca as variáveis através dos ensaios utilizados (igual ao ultimo_ensaio)
                if calculo.ensaios_utilizados:
                    ensaios_com_variaveis = []
                    
                    for ensaio_data in calculo.ensaios_utilizados:
                        # Se ensaio_data é um dicionário, pega o id
                        if isinstance(ensaio_data, dict):
                            ensaio_id = ensaio_data.get('id') or ensaio_data.get('value')
                            # Copia todos os dados do ensaio original
                            ensaio_completo = ensaio_data.copy()
                        else:
                            ensaio_id = ensaio_data
                            ensaio_completo = {'id': ensaio_id}
                            
                        # Verifica se o ensaio_id é válido (não é temporário)
                        if ensaio_id and not str(ensaio_id).startswith('temp_'):
                            try:
                                ensaio_id = int(ensaio_id)  # Converte para int
                                ensaio = Ensaio.objects.get(id=ensaio_id)
                                
                                # Adiciona o campo 'variaveis' como objeto (igual ultimo_ensaio)
                                variaveis_object = {}
                                variaveis_utilizadas = []
                                
                                for i, variavel in enumerate(ensaio.variavel.all()):
                                    key = f'var{i+1:02d}' if i < 9 else f'var{i+1}'  # var01, var02, etc.
                                    var_data = {
                                        'valor': variavel.id,
                                        'descricao': getattr(variavel, 'descricao', str(variavel))
                                    }
                                    variaveis_object[key] = var_data
                                    # Também adiciona como campo individual
                                    ensaio_completo[key] = var_data
                                    
                                    # Adiciona ao variaveis_utilizadas (igual ultimo_ensaio)
                                    variaveis_utilizadas.append({
                                        'nome': getattr(variavel, 'descricao', str(variavel)),
                                        'valor': variavel.id,
                                        'tecnica': key
                                    })
                                
                                #ensaio_completo['variaveis'] = variaveis_object
                                ensaio_completo['variaveis_utilizadas'] = variaveis_utilizadas
                                ensaios_com_variaveis.append(ensaio_completo)
                                
                            except (Ensaio.DoesNotExist, ValueError, TypeError):
                                # Se o ensaio não existe ou ID inválido, adiciona sem variáveis
                                if isinstance(ensaio_data, dict):
                                    ensaios_com_variaveis.append(ensaio_data)
                        else:
                            # ID temporário ou inválido, adiciona sem variáveis
                            if isinstance(ensaio_data, dict):
                                ensaios_com_variaveis.append(ensaio_data)
                    
                    # Atualiza os ensaios_utilizados
                    data['ensaios_utilizados'] = ensaios_com_variaveis
                
                calculos_lista.append(data)
            
            return calculos_lista
        return []

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
                ensaios=ensaio.get('ensaios'),
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
                laboratorio=calc.get('laboratorio'),
            )

        return instance

