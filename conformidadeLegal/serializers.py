from django.contrib.auth.models import User
from rest_framework import serializers

from .models import EvidenciaAnexo, ExtracaoIA, Norma, PlanoAcao, Requisito, Verificacao


def _nome_usuario(u):
    if not u:
        return None
    return (u.get_full_name() or u.username).strip()


class NormaSerializer(serializers.ModelSerializer):
    identificacao = serializers.CharField(read_only=True)
    total_requisitos = serializers.IntegerField(read_only=True, default=0)
    arquivo_url = serializers.SerializerMethodField()

    class Meta:
        model = Norma
        fields = [
            'id', 'tipo', 'numero', 'ano', 'orgao', 'esfera', 'tema', 'ementa', 'link',
            'data_publicacao', 'validade', 'situacao', 'arquivo', 'arquivo_url', 'observacao',
            'identificacao', 'total_requisitos', 'criado_em', 'atualizado_em',
        ]
        read_only_fields = ['criado_em', 'atualizado_em']
        extra_kwargs = {'arquivo': {'write_only': True, 'required': False}}

    def get_arquivo_url(self, obj):
        if not obj.arquivo:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(obj.arquivo.url) if request else obj.arquivo.url


class RequisitoSerializer(serializers.ModelSerializer):
    norma_identificacao = serializers.CharField(source='norma.identificacao', read_only=True)
    norma_ementa = serializers.CharField(source='norma.ementa', read_only=True)
    responsavel_nome = serializers.SerializerMethodField()
    responsavel = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), allow_null=True, required=False)
    planos_abertos = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Requisito
        fields = [
            'id', 'norma', 'norma_identificacao', 'norma_ementa', 'referencia', 'descricao', 'tema',
            'aplicabilidade', 'justificativa', 'unidade', 'responsavel', 'responsavel_nome',
            'periodicidade_meses', 'prazo_legal', 'situacao', 'ultima_verificacao', 'proxima_verificacao',
            'origem', 'trecho_fonte', 'pagina_fonte', 'ativo', 'planos_abertos', 'criado_em', 'atualizado_em',
        ]
        # O estado só muda registrando (ou apagando) uma verificação.
        read_only_fields = ['situacao', 'ultima_verificacao', 'proxima_verificacao', 'criado_em', 'atualizado_em']

    def get_responsavel_nome(self, obj):
        return _nome_usuario(obj.responsavel)


class EvidenciaAnexoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = EvidenciaAnexo
        fields = ['id', 'nome', 'tamanho', 'url', 'criado_em']

    def get_url(self, obj):
        request = self.context.get('request')
        return request.build_absolute_uri(obj.arquivo.url) if request else obj.arquivo.url


class VerificacaoSerializer(serializers.ModelSerializer):
    verificado_por_nome = serializers.SerializerMethodField()
    anexos = EvidenciaAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = Verificacao
        fields = [
            'id', 'requisito', 'data', 'resultado', 'evidencia', 'observacao',
            'verificado_por_nome', 'anexos', 'criado_em',
        ]
        read_only_fields = ['requisito', 'criado_em']

    def get_verificado_por_nome(self, obj):
        return _nome_usuario(obj.verificado_por)


class PlanoAcaoSerializer(serializers.ModelSerializer):
    responsavel = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), allow_null=True, required=False)
    responsavel_nome = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    requisito_resumo = serializers.SerializerMethodField()
    tarefa_coluna = serializers.SerializerMethodField()

    class Meta:
        model = PlanoAcao
        fields = [
            'id', 'requisito', 'requisito_resumo', 'verificacao', 'descricao', 'responsavel', 'responsavel_nome',
            'prazo', 'tarefa', 'tarefa_coluna', 'concluido_em', 'status', 'criado_em',
        ]
        read_only_fields = ['tarefa', 'concluido_em', 'criado_em']

    def get_responsavel_nome(self, obj):
        return _nome_usuario(obj.responsavel)

    def get_requisito_resumo(self, obj):
        r = obj.requisito
        ref = f' — {r.referencia}' if r.referencia else ''
        return f'{r.norma.identificacao}{ref}'

    def get_tarefa_coluna(self, obj):
        t = obj.tarefa
        if not t:
            return None
        return {'quadro': t.coluna.quadro.nome, 'lista': t.coluna.titulo, 'quadro_id': t.coluna.quadro_id}


class ExtracaoIASerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtracaoIA
        fields = ['id', 'norma', 'status', 'itens', 'resumo', 'erro', 'modelo',
                  'tokens_entrada', 'tokens_saida', 'criado_em', 'concluido_em']
