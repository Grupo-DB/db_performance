from rest_framework import serializers
from .models import TipoEnsaio, Ensaio, Variavel, PlanoPeneira

class TipoEnsaioSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoEnsaio
        fields = '__all__'
class VariavelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Variavel
        fields = '__all__'        


class EnsaioSerializer(serializers.ModelSerializer):
    tipo_ensaio = serializers.PrimaryKeyRelatedField(queryset=TipoEnsaio.objects.all(), write_only=True)
    tipo_ensaio_detalhes = TipoEnsaioSerializer(source='tipo_ensaio', read_only=True)
    variavel = serializers.PrimaryKeyRelatedField(queryset=Variavel.objects.all(), write_only=True, many=True)
    variavel_detalhes = VariavelSerializer(source='variavel', read_only=True, many=True)
    
    # Mudança aqui: usar CharField primeiro, depois converter
    valor = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    
    def validate_valor(self, value):
        # Se é None, string vazia ou 'null', retorna None
        if value is None or value == '' or value == 'null' or value == 'undefined':
            return None
        
        # Tenta converter para float
        try:
            return float(value)
        except (ValueError, TypeError):
            raise serializers.ValidationError("Valor deve ser um número válido ou vazio.")
    
    class Meta:
        model = Ensaio
        fields = '__all__'

    def create(self, validated_data):
        variaveis = validated_data.pop('variavel', [])
        ensaio = Ensaio.objects.create(**validated_data)
        ensaio.variavel.set(variaveis)
        return ensaio

    def update(self, instance, validated_data):
        variaveis = validated_data.pop('variavel', None)
        
        # Atualiza os campos normalmente
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Atualiza as variáveis se fornecidas
        if variaveis is not None:
            instance.variavel.set(variaveis)
        
        instance.save()
        return instance

class PlanoPeneiraSerializer(serializers.ModelSerializer):
    """Cadastro dos planos de peneiramento.

    `tipo_display` existe para a listagem do front não precisar repetir o de/para
    de 'peneiras_secas' -> 'Peneiras Secas'.
    """

    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)

    class Meta:
        model = PlanoPeneira
        fields = '__all__'

    def validate_descricao(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError('Informe a descrição do plano.')
        return value

    def validate_peneiras(self, value):
        """Lista de malhas, sem repetição e sem item vazio.

        A malha é casada por igualdade de string com o que está gravado na
        análise: um espaço a mais ou um item duplicado não dá erro nenhum na
        gravação e depois vira coluna vazia (ou dobrada) no relatório.
        """
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('Envie uma lista de malhas.')

        malhas = []
        for item in value:
            if not isinstance(item, str):
                raise serializers.ValidationError('Cada malha deve ser um texto.')
            malha = item.strip()
            if not malha:
                continue
            if malha not in malhas:
                malhas.append(malha)
        return malhas
