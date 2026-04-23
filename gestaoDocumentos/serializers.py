from rest_framework import serializers
from gestaoDocumentos.models import Acao, Alvara, Atas, Diretorio, Contrato, DocumentoAnexo, Patrimonial, ProcessoInterno, ProcessoExterno, Procuracao, Seguro, Societario, Veiculo


class DocumentoAnexoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoAnexo
        fields = ['id', 'arquivo', 'nome_original', 'created_at', 'created_by']


class DiretorioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Diretorio
        fields = '__all__'

class AtasSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = Atas
        fields = [
            'id',
            'tipo',
            'data_reuniao',
            'participantes',
            'pauta',
            'deliberacoes',
            'observacoes',
            'status',
            'anexo',
            'anexos',
            'diretorio',
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'
        ]        

class SocietarioSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = Societario
        fields = [
            'id',
            'tipo',
            'data_assinatura',
            'orgao_registro',
            'administadores',
            'status',
            'observacoes',
            'anexo',
            'anexos',
            'diretorio',
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'
        ]

class SeguroSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = Seguro
        fields = [
            'id',
            'tipo',
            'seguradora',
            'numero_apolice',
            'empresa_segurada',
            'bem_segurado',
            'valor_seguro',
            'data_inicio',
            'data_fim',
            'vigencia',
            'status',
            'observacoes',
            'anexo',
            'anexos',
            'diretorio',
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'
        ]

class ContratoSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = Contrato
        fields = [
            'id',
            'tipo', 
            'numero',
            'contratante',
            'contratado',
            'objeto_contrato', 
            'valor_contrato',
            'data_inicio', 
            'data_fim', 
            'prazo_aviso',
            'vigencia', 
            'responsavel_contratante', 
            'responsavel_contratado', 
            'multa_recisao',
            'renovacao',
            'reajuste', 
            'forma_pagamento',
            'observacoes', 
            'status', 
            'anexo',
            'anexos',
            'diretorio', 
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'
        ]

class ProcessoInternoSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = ProcessoInterno
        fields = [
            'id', 
            'tag', 
            'titulo', 
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
            'observacoes', 
            'anexo',
            'anexos',
            'diretorio', 
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'
        ]

class ProcessoExternoSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = ProcessoExterno
        fields = [
            'id', 
            'tipo', 
            'numero', 
            'empresa_envolvida', 
            'parte_contraria', 
            'orgao_foro', 
            'vara_instancia',
            'objeto_processo', 
            'valor_causa', 
            'escritorio_juridico',
            'advogado_responsavel', 
            'andamento', 
            'status',
            'observacoes', 
            'anexo',
            'anexos',
            'diretorio', 
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'
        ]        

class VeiculoSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = Veiculo
        fields = [
            'id', 
            'placa', 
            'modelo_veiculo', 
            'tipo_documento', 
            'situacao_veiculo', 
            'data_emissao', 
            'data_vencimento', 
            'vigencia',
            'ano_exercicio', 
            'valor_ipva', 
            'situacao_pagamento', 
            'data_pagamento',
            'responsavel',
            'status',
            'observacoes',
            'anexo',
            'anexos',
            'diretorio',
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'
        ]

class AcaoSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

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
            'anexos',
            'diretorio', 
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'    
        ]

class AlvaraSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = Alvara
        fields = [
            'id', 
            'empresa_titular', 
            'tipo_alvara',
            'numero_alvara', 
            'orgao_emissor',
            'responsavel_alvara', 
            'data_inicio', 
            'data_fim', 
            'vigencia', 
            'ultima_atualizacao', 
            'renovavel',
            'prazo_renovacao', 
            'observacoes',
            'status', 
            'anexo',
            'anexos',
            'diretorio', 
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'
        ]

class ProcuracaoSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = Procuracao
        fields = [
            'id', 
            'outorgante', 
            'outorgado',
            'tipo', 
            'finalidade', 
            'substabelecer', 
            'substabelecimento_vinculado', 
            'observacoes',
            'data_inicio', 
            'data_fim', 
            'vigencia',
            'status', 
            'anexo',
            'anexos',
            'diretorio', 
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'    
        ]

class PatrimonialSerializer(serializers.ModelSerializer):
    diretorio = serializers.PrimaryKeyRelatedField(queryset=Diretorio.objects.all(), write_only=True)
    diretorio_detalhes = DiretorioSerializer(source='diretorio', read_only=True)
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = Patrimonial
        fields = [
            'id', 
            'titular', 
            'tipo_bem', 
            'descricao_bem',
            'cod_interno', 
            'situacao_bem', 
            'data_aquisicao', 
            'forma_aquisicao',
            'responsavel_bem',
            # 'localizacao', 
            'localizacao_tipo',
            'endereco', 
            'bairro', 
            'cidade', 
            'estado', 
            'cep', 
            'distrito',
            'coordenadas', 
            'codigo_cartorio', 
            # 'registro',
            'matricula', 
            'comarca', 
            'zona',
            'cartorio',
            'insc_municipal',
            'insc_estadual',
            # 'benfeitorias
            'valor_contabil',
            'valor_venal',
            'valor_avaliado',
            'benfeitoria', 
            'area_privativa', 
            'area_total',
            'tipo_construcao', 
            'estado_conservacao', 
            'padrao_construtivo', 
            'idade',
            # 'status',
            'observacoes',
            'status', 
            'anexo', 
            'anexos',
            'diretorio', 
            'diretorio_detalhes',
            'empresa_grupo',
            'setor_interessado',
            'responsavel_interno',
            'data_cadastro',
            'created_at',
            'updated_at',
            'created_by',
            'updated_by'    
        ]