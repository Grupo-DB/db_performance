from rest_framework import serializers
from django.contrib.auth.models import User,Group
from rest_framework import serializers

from avaliacoes.management.models import Colaborador
from .models import ContaContabil, Gestor, RaizAnalitica, CentroCustoPai, CentroCusto

class GestorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Gestor
        fields = '__all__'
    def create(self, validated_data):
        colaborador_data = validated_data.pop('colaborador_id', None)
        if colaborador_data:
            colaborador = Colaborador.objects.get(id=colaborador_data)
            validated_data['colaborador_ptr'] = colaborador
        gestor = Gestor.objects.create(**validated_data)
        return gestor

class ContaContabilSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContaContabil
        fields = '__all__'

class RaizAnaliticaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RaizAnalitica
        fields = ['id', 'raiz_contabil', 'descricao', 'gestor']
        read_only_fields = ['descricao']  # `descricao` será preenchido automaticamente

    def validate(self, data):
        # Obtendo a raiz_contabil fornecida pelo usuário
        raiz_contabil = data.get('raiz_contabil', None)
        
        if raiz_contabil:
            # Buscando o registro correspondente em ContaContabil
            conta = ContaContabil.objects.filter(
                nivel_analitico_conta__endswith=raiz_contabil
            ).first()
            
            if conta:
                # Concatenando os valores de nivel_5_nome e nivel_6_nome com o separador ">"
                data['descricao'] = f"{conta.nivel_5_nome} > {conta.nivel_analitico_nome}"
            else:
                # Se não encontrar a conta, pode lançar um erro ou deixar `descricao` vazio
                data['descricao'] = ''  # Ou lançar um erro se necessário

        return data

    def create(self, validated_data):
        # Cria a instância de RaizAnalitica com a descrição preenchida
        return RaizAnalitica.objects.create(**validated_data)

    def update(self, instance, validated_data):
        # Atualiza a instância de RaizAnalitica com a nova descrição, se necessário
        instance.raiz_contabil = validated_data.get('raiz_contabil', instance.raiz_contabil)
        instance.descricao = validated_data.get('descricao', instance.descricao)
        instance.gestor = validated_data.get('gestor', instance.gestor)
        instance.save()
        return instance
    
class CentroCustoPaiSerializer(serializers.ModelSerializer):
    class Meta:
        model = CentroCustoPai
        fields = '__all__'

class CentroCustoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CentroCusto
        fields = '__all__'