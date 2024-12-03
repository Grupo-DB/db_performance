from rest_framework import serializers
from django.contrib.auth.models import User,Group
from rest_framework import serializers

from avaliacoes.management.models import Colaborador
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
    empresa = EmpresaSerializer()
    filial = FilialSerializer()
    area = AreaSerializer()
    setor = SetorSerializer()
    ambiente = AmbienteSerializer() 
    class Meta:
        model = CentroCustoPai
        fields = '__all__'

class CentroCustoSerializer(serializers.ModelSerializer):
    gestor = serializers.PrimaryKeyRelatedField(queryset=Gestor.objects.all(), write_only=True)  # Entrada
    gestor_detalhes = GestorSerializer(source='gestor', read_only=True)  # Exibição

    class Meta:
        model = CentroCusto
        fields = ['id','codigo','nome','cc_pai','gestor','gestor_detalhes']


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
    class Meta:
        model = GrupoItens
        fields = '__all__'


class OrcamentoBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrcamentoBase
        fields = '__all__'
        # fields = [
        #     'centro_de_custo_pai','centro_de_custo_nome','gestor','empresa','filial','area','setor',
        #     'ambiente','raiz_sintetica','raiz_sintetica_desc','raiz_analitica','raiz_analitica_desc',
        #     'conta_contabil','conta_contabil_descricao','raiz_contabil_grupo','raiz_contabil_grupo_desc',
        #     'recorrencia','mensal_tipo','mes_especifico','meses_recorrentes','suplementacao',
        #     'base_orcamento','id_base','valor'
        #     ]
        # read_only_fields = [
        #     'empresa','filial','area','setor','ambiente','raiz_sintetica_desc',
        #     'raiz_analitica_desc','conta_contabil','conta_contabil_descricao','raiz_contabil_grupo',
        #     'raiz_contabil_grupo_desc','id_base',
        #     ]
        
        # def get_periodicidade_choices(self, obj):
        #     return OrcamentoBase.PERIODICIDADE_CHOICES

        # def get_mensal_choices(self, obj):
        #     return OrcamentoBase.MENSAL_CHOICES


        # def validate(self,data):
        #     centro_de_custo_pai = data.get('centro_de_custo_pai')
        #     centro_custo = data.get('centro_de_custo')
        #     raiz_sintetica = data.get('raiz_sintetica')
        #     raiz_analitica = data.get('raiz_analitica')
        #     conta_contabil = data.get('conta_contabil')

        #     if centro_de_custo_pai:
        #         # Preenche os campos empresa, filial, area, setor e ambiente com base no centro_de_custo_pai
        #         data['empresa'] = centro_de_custo_pai.empresa.nome
        #         data['filial'] = centro_de_custo_pai.filial.nome
        #         data['area'] = centro_de_custo_pai.area.nome
        #         data['setor'] = centro_de_custo_pai.setor.nome
        #         data['ambiente'] = centro_de_custo_pai.ambiente.nome

            
        #     if raiz_sintetica and raiz_analitica and conta_contabil and centro_custo:
        #         data['raiz_sintetica_desc'] = raiz_sintetica.descricao
        #         data['raiz_analitica_desc'] = raiz_analitica.descricao
        #         data['conta_contabil'] = f"{raiz_sintetica.raiz_contabil}{raiz_analitica.raiz_contabil}"
        #         data['conta_contabil_desc'] = f"{conta_contabil.nivel_analitico_nome}"
        #         data['raiz_contabil_grupo'] = f"{raiz_sintetica.raiz_contabil[:4]}{raiz_analitica.raiz_contabil[:2]}"
        #         data['raiz_contabil_grupo_desc']=f'{conta_contabil.nivel_4_nome}'
        #         data['id_base'] = f"{centro_custo.codigo}{conta_contabil.nivel_analitico_conta}"
            
        #     return data   

        # def create(self, validated_data):
        # # Cria a instância de RaizAnalitica com a descrição preenchida
        #     return OrcamentoBase.objects.create(**validated_data)     
        
        # def update(self, instance, validated_data):
        #     # Atualiza campos editáveis
        #     instance.centro_de_custo_pai = validated_data.get('centro_de_custo_pai', instance.centro_de_custo_pai)
        #     instance.centro_de_custo_nome = validated_data.get('centro_de_custo_nome', instance.centro_de_custo_nome)
        #     instance.gestor = validated_data.get('gestor', instance.gestor)
        #     instance.recorrencia = validated_data.get('recorrencia', instance.recorrencia)
        #     instance.mensal_tipo = validated_data.get('mensal_tipo', instance.mensal_tipo)
        #     instance.mes_especifico = validated_data.get('mes_especifico', instance.mes_especifico)
        #     instance.meses_recorrentes = validated_data.get('meses_recorrentes', instance.meses_recorrentes)
        #     instance.suplementacao = validated_data.get('suplementacao', instance.suplementacao)
        #     instance.base_orcamento = validated_data.get('base_orcamento', instance.base_orcamento)
        #     instance.valor = validated_data.get('valor', instance.valor)

        #     # Atualiza campos relacionados dinamicamente
        #     centro_de_custo_pai = validated_data.get('centro_de_custo_pai')
        #     if centro_de_custo_pai:
        #         instance.empresa = centro_de_custo_pai.empresa.nome
        #         instance.filial = centro_de_custo_pai.filial.nome
        #         instance.area = centro_de_custo_pai.area.nome
        #         instance.setor = centro_de_custo_pai.setor.nome
        #         instance.ambiente = centro_de_custo_pai.ambiente.nome

        #     raiz_sintetica = validated_data.get('raiz_sintetica')
        #     raiz_analitica = validated_data.get('raiz_analitica')
        #     conta_contabil = validated_data.get('conta_contabil')
        #     centro_custo = validated_data.get('centro_de_custo_nome')

        #     if raiz_sintetica and raiz_analitica and conta_contabil and centro_custo:
        #         instance.raiz_sintetica_desc = raiz_sintetica.descricao
        #         instance.raiz_analitica_desc = raiz_analitica.descricao
        #         instance.conta_contabil = f"{raiz_sintetica.raiz_contabil}{raiz_analitica.raiz_contabil}"
        #         instance.conta_contabil_descricao = conta_contabil.nivel_analitico_nome
        #         instance.raiz_contabil_grupo = f"{raiz_sintetica.raiz_contabil[:4]}{raiz_analitica.raiz_contabil[:2]}"
        #         instance.raiz_contabil_grupo_desc = conta_contabil.nivel_4_nome
        #         instance.id_base = f"{centro_custo.codigo}{conta_contabil.nivel_analitico_conta}"

        #     # Salva a instância atualizada
        #     instance.save()
        #     return instance