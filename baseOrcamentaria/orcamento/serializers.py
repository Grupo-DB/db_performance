from rest_framework import serializers
from django.contrib.auth.models import User,Group
from avaliacoes.management.models import Ambiente, Area, Colaborador, Empresa, Filial, Setor
from avaliacoes.management.serializers import AmbienteSerializer, AreaSerializer, EmpresaSerializer, FilialSerializer, SetorSerializer
from .models import ContaContabil,Gestor,RaizAnalitica,CentroCustoPai,CentroCusto,RaizSintetica,GrupoItens,OrcamentoBase

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
                nivel_analitico_conta__endswith=raiz_contabil[-13:]
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
    # Para escrita, aceita apenas IDs
    empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all(), write_only=True)
    filial = serializers.PrimaryKeyRelatedField(queryset=Filial.objects.all(), write_only=True)
    area = serializers.PrimaryKeyRelatedField(queryset=Area.objects.all(), write_only=True)
    setor = serializers.PrimaryKeyRelatedField(queryset=Setor.objects.all(), write_only=True)
    ambiente = serializers.PrimaryKeyRelatedField(queryset=Ambiente.objects.all(), write_only=True)

    # Para leitura, retorna os dados completos
    empresa_detalhes = EmpresaSerializer(source='empresa', read_only=True)
    filial_detalhes = FilialSerializer(source='filial', read_only=True)
    area_detalhes = AreaSerializer(source='area', read_only=True)
    setor_detalhes = SetorSerializer(source='setor', read_only=True)
    ambiente_detalhes = AmbienteSerializer(source='ambiente', read_only=True)

    class Meta:
        model = CentroCustoPai
        fields = [
            'id',  'nome', 
            'empresa', 'empresa_detalhes', 
            'filial', 'filial_detalhes',
            'area', 'area_detalhes',
            'setor', 'setor_detalhes',
            'ambiente', 'ambiente_detalhes'
        ]

class CentroCustoSerializer(serializers.ModelSerializer):
    gestor = serializers.PrimaryKeyRelatedField(queryset=Gestor.objects.all(), write_only=True)  # Entrada
    gestor_detalhes = GestorSerializer(source='gestor', read_only=True)  # Exibição
    cc_pai = serializers.PrimaryKeyRelatedField(queryset=CentroCustoPai.objects.all(), write_only=True)  # Entrada
    cc_pai_detalhes = CentroCustoPaiSerializer(source='cc_pai', read_only=True)  # Exibição

    class Meta:
        model = CentroCusto
        fields = ['id','codigo','nome','cc_pai','cc_pai_detalhes','gestor','gestor_detalhes']


class RaizSinteticaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RaizSintetica
        fields = ['id','raiz_contabil','descricao','natureza','centro_custo']
        read_only_fields = ['descricao','natureza']

    def validate(self,data):
        raiz_contabil = data.get('raiz_contabil', None)

        if raiz_contabil:
            data['natureza'] = raiz_contabil[0]

            conta = ContaContabil.objects.filter(
                nivel_3_conta__startswith=raiz_contabil[:4]
            ).first()
            
            if conta:
                # Concatenando os valores de nivel_5_nome e nivel_6_nome com o separador ">"
                data['descricao'] = f"{conta.nivel_3_nome}"
            else:
                # Se não encontrar a conta, pode lançar um erro ou deixar `descricao` vazio
                raise serializers.ValidationError("Conta contábil não encontrada para a raiz fornecida.")
        return data  

    def create(self, validated_data):
        # Cria a instância de RaizAnalitica com a descrição preenchida
        return RaizSintetica.objects.create(**validated_data)
            
    def update(self, instance, validated_data):
        # Atualiza a instância de RaizAnalitica com a nova descrição, se necessário
        instance.raiz_contabil = validated_data.get('raiz_contabil', instance.raiz_contabil)
        instance.descricao = validated_data.get('descricao', instance.descricao)
        instance.natureza = validated_data.get('natureza', instance.natureza)
        instance.centro_custo = validated_data.get('centro_custo', instance.centro_custo)
        instance.save()
        return instance

class GrupoItensSerializer(serializers.ModelSerializer):
    gestor = serializers.PrimaryKeyRelatedField(queryset=Gestor.objects.all(), write_only=True)  # Entrada
    gestor_detalhes = GestorSerializer(source='gestor', read_only=True)  # Exibição
    class Meta:
        model = GrupoItens
        fields = '__all__'


class OrcamentoBaseSerializer(serializers.ModelSerializer):
    cc_pai = serializers.PrimaryKeyRelatedField(queryset=CentroCustoPai.objects.all(), write_only=True)  # Entrada
    cc =  serializers.PrimaryKeyRelatedField(queryset=CentroCusto.objects.all(), write_only=True)

    cc_pai_detalhes = CentroCustoPaiSerializer(source='cc_pai', read_only=True)
    cc_detalhes = CentroCustoSerializer(source='cc', read_only=True)
    class Meta:
        model = OrcamentoBase
        fields = '__all__'
       