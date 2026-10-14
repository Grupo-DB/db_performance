from django.contrib.auth.models import User
from rest_framework import serializers

from .models import (
    ConfiguracaoMonitor, EvidenciaAnexo, ExecucaoMonitor, ExtracaoIA, Norma, OrgaoMonitor, PalavraChaveMonitor, PlanoAcao,
    PublicacaoMonitorada, Requisito, Verificacao,
)


def nome_usuario(u):
    """
    Nome de quem é responsável, como as pessoas se conhecem: o do cadastro de
    colaboradores (Colaborador.user), não o login. Sem colaborador ligado, cai no
    nome do usuário e, por fim, no login.
    """
    if not u:
        return None
    # Acesso reverso de OneToOne sem registro levanta RelatedObjectDoesNotExist,
    # que também é AttributeError — o getattr com default cobre.
    colaborador = getattr(u, 'colaborador', None)
    nome = (getattr(colaborador, 'nome', '') or '').strip()
    return nome or (u.get_full_name() or u.username).strip()


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
        return nome_usuario(obj.responsavel)


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
        return nome_usuario(obj.verificado_por)


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
        return nome_usuario(obj.responsavel)

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
        fields = ['id', 'norma', 'status', 'itens', 'resumo', 'erro', 'modelo', 'paginas',
                  'tokens_entrada', 'tokens_saida', 'criado_em', 'concluido_em']


class PublicacaoSerializer(serializers.ModelSerializer):
    """Lista: sem o texto integral (vem no detalhe), que pode ter dezenas de KB."""
    fonte_rotulo = serializers.CharField(source='get_fonte_display', read_only=True)
    avaliado_por_nome = serializers.SerializerMethodField()
    norma_identificacao = serializers.CharField(source='norma.identificacao', read_only=True, default=None)

    class Meta:
        model = PublicacaoMonitorada
        fields = ['id', 'fonte', 'fonte_rotulo', 'id_externo', 'data_publicacao', 'orgao', 'tipo', 'titulo', 'link',
                  'pagina', 'palavras', 'origem', 'relevancia', 'analise', 'tema_sugerido', 'analisada_em', 'status', 'norma',
                  'norma_identificacao', 'motivo_descarte', 'avaliado_por_nome', 'avaliado_em', 'criado_em']
        read_only_fields = fields

    def get_avaliado_por_nome(self, obj):
        return nome_usuario(obj.avaliado_por)


class PublicacaoDetalheSerializer(PublicacaoSerializer):
    class Meta(PublicacaoSerializer.Meta):
        fields = PublicacaoSerializer.Meta.fields + ['texto']
        read_only_fields = fields


# ── Configuração do monitor ──────────────────────────────────────────────
class PalavraChaveSerializer(serializers.ModelSerializer):
    class Meta:
        model = PalavraChaveMonitor
        fields = ['id', 'rotulo', 'termos', 'ativo', 'atualizado_em']
        read_only_fields = ['atualizado_em']

    def validate_termos(self, valor):
        from .monitor import termo_valido
        obj = PalavraChaveMonitor(termos=valor or '')
        termos = obj.lista_termos()
        if not termos:
            raise serializers.ValidationError('Informe ao menos um termo.')
        erros = [e for e in (termo_valido(t) for t in termos) if e]
        if erros:
            raise serializers.ValidationError(erros[0])
        return '\n'.join(termos)


class OrgaoMonitorSerializer(serializers.ModelSerializer):
    fonte_rotulo = serializers.CharField(source='get_fonte_display', read_only=True)

    class Meta:
        model = OrgaoMonitor
        fields = ['id', 'fonte', 'fonte_rotulo', 'rotulo', 'campo', 'valor', 'exige_palavra', 'tipos_dou', 'ativo', 'ordem']

    def validate(self, dados):
        fonte = dados.get('fonte', getattr(self.instance, 'fonte', None))
        campo = dados.get('campo', getattr(self.instance, 'campo', None))
        if fonte == 'DOU' and campo != 'categoria':
            raise serializers.ValidationError({'campo': 'No Diário Oficial da União a consulta é pelo órgão do ato.'})
        if fonte == 'DOE_RS' and campo not in ('entidade', 'tipoMateria'):
            raise serializers.ValidationError({'campo': 'No Diário Oficial do RS a consulta é por órgão ou por tipo de matéria.'})
        if not (dados.get('valor', getattr(self.instance, 'valor', '')) or '').strip():
            raise serializers.ValidationError({'valor': 'Informe como o órgão aparece na fonte.'})
        return dados


class ConfiguracaoMonitorSerializer(serializers.ModelSerializer):
    atualizado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = ConfiguracaoMonitor
        fields = ['perfil_empresa', 'atualizado_por_nome', 'atualizado_em']
        read_only_fields = ['atualizado_em']

    def get_atualizado_por_nome(self, obj):
        return nome_usuario(obj.atualizado_por)


class ExecucaoMonitorSerializer(serializers.ModelSerializer):
    fonte_rotulo = serializers.CharField(source='get_fonte_display', read_only=True)

    class Meta:
        model = ExecucaoMonitor
        fields = ['id', 'fonte', 'fonte_rotulo', 'data_referencia', 'iniciado_em', 'concluido_em', 'ok', 'examinadas',
                  'novas', 'erro']
