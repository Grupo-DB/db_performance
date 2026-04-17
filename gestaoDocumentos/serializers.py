from rest_framework import serializers
from gestaoDocumentos.models import Acao, Alvara, Diretorio, Contrato, Patrimonial, Processo, Procuracao

class DiretorioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Diretorio
        fields = '__all__'

class ContratoSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)

    class Meta:
        model = Contrato
        fields = [
            'id', 'numero','contratante','contratado', 'objeto_contrato', 'valor_contrato',
            'data_inicio', 'data_fim', 'vigencia', 'setor_interessado',
            'responsavel_contratante', 'responsavel_contratado', 'multa_recisao',
            'reajuste', 'observacoes', 'status', 'anexo',
            'diretorio', 'diretorio_detalhes',
        ]

class ProcessoSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)

    class Meta:
        model = Processo
        fields = [
            'id', 
            'tag', 
            'titulo', 
            'setor_interessado', 
            'responsavel_setor',
            'versao', 
            'data_versao', 
            'documento_citado', 
            'copia_fisica_setores',
            'copia_digital_setores', 
            'periodicidade_auditoria', 
            'ultima_auditoria',
            'periodicidade_reciclagem', 
            'ultimo_treinamento', 
            'status', 
            'anexo',
            'diretorio', 
            'diretorio_detalhes',
        ]

class AcaoSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)

    class Meta:
        model = Acao
        fields = [
            'id', 
            'nome', 
            'cpf', 
            'especie', 
            'quantidade', 
            'participacao', 
            'observacoes',
            'status', 
            'anexo', 
            'diretorio', 
            'diretorio_detalhes',
        ]

class AlvaraSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)

    class Meta:
        model = Alvara
        fields = [
            'id', 
            'empresa_titular', 
            'tipo_alvara', 
            'setor_interessado', 
            'responsavel_setor',
            'responsavel_alvara',
            'data_inicio', 
            'data_fim', 
            'vigencia', 
            'status', 
            'anexo',
            'diretorio', 
            'diretorio_detalhes',
        ]

class ProcuracaoSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)

    class Meta:
        model = Procuracao
        fields = [
            'id', 
            'outorgante', 
            'outorgado', 
            'poderes', 
            'data_inicio', 
            'data_fim', 
            'vigencia',
            'status', 
            'anexo', 
            'diretorio', 
            'diretorio_detalhes',
        ]

class PatrimonialSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)

    class Meta:
        model = Patrimonial
        fields = [
            'id', 
            'titular', 
            'tipo_bem', 
            'descricao_bem', 
            'localizacao_tipo',
            'endereco', 
            'bairro', 
            'cidade', 
            'estado', 
            'cep', 
            'distrito',
            'coordenadas', 
            'codigo_cartorio', 
            'matricula', 
            'comarca', 
            'zona',
            'valor_contabil', 
            'bemfeitoria', 
            'area_privativa', 
            'area_total',
            'tipo_construcao', 
            'estado_conservacao', 
            'padrao_construtivo', 
            'idade',
            'status', 
            'anexo', 
            'diretorio', 
            'diretorio_detalhes',
        ]