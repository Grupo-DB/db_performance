from django.contrib.auth.models import User
from rest_framework import serializers

from .models import (
    ConfiguracaoMonitor, EvidenciaAnexo, ExecucaoMonitor, ExtracaoIA, Norma, OrgaoMonitor, PalavraChaveMonitor, PlanoAcao,
    PublicacaoMonitorada, Requisito, Terceiro, DocumentoTerceiro, Verificacao, ConfiguracaoAvisos,
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
    terceiro_nome = serializers.CharField(source='terceiro.__str__', read_only=True, default=None)

    class Meta:
        model = Requisito
        fields = [
            'id', 'norma', 'norma_identificacao', 'norma_ementa', 'referencia', 'descricao', 'tema',
            'aplicabilidade', 'justificativa', 'unidade', 'responsavel', 'responsavel_nome', 'terceiro', 'terceiro_nome',
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
    terceiro_nome = serializers.CharField(source='terceiro.__str__', read_only=True, default=None)

    class Meta:
        model = PlanoAcao
        fields = [
            'id', 'requisito', 'requisito_resumo', 'verificacao', 'descricao', 'responsavel', 'responsavel_nome',
            'terceiro', 'terceiro_nome',
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
                  'tokens_entrada', 'tokens_saida', 'criado_em', 'concluido_em', 'normas_citadas']

    def to_representation(self, obj):
        dados = super().to_representation(obj)
        # Marca as NBRs que já são palavra-chave ativa do monitor.
        citadas = dados.get('normas_citadas') or []
        if citadas:
            from .normas_tecnicas import rotulo_monitor
            ativas = set(PalavraChaveMonitor.objects.filter(ativo=True).values_list('rotulo', flat=True))
            dados['normas_citadas'] = [{**c, 'monitorada': rotulo_monitor(c) in ativas} for c in citadas]
        return dados


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
        fields = ['id', 'rotulo', 'termos', 'ativo', 'qualquer_orgao', 'norma_origem', 'norma_origem_identificacao',
                  'atualizado_em']
        read_only_fields = ['atualizado_em', 'norma_origem']

    norma_origem_identificacao = serializers.CharField(source='norma_origem.identificacao', read_only=True, default=None)

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


def _url_arquivo(serializer, arquivo):
    if not arquivo:
        return None
    request = serializer.context.get('request')
    return request.build_absolute_uri(arquivo.url) if request else arquivo.url


class DocumentoTerceiroSerializer(serializers.ModelSerializer):
    tipo_rotulo = serializers.CharField(source='get_tipo_display', read_only=True)
    situacao = serializers.CharField(read_only=True)
    dias_para_vencer = serializers.IntegerField(read_only=True)
    arquivo_url = serializers.SerializerMethodField()
    arquivo_nome = serializers.SerializerMethodField()
    enviado_por_nome = serializers.SerializerMethodField()
    # Em multipart o DRF lê booleano ausente como False (checkbox HTML); o padrão é exigir.
    obrigatorio = serializers.BooleanField(required=False, default=True)

    class Meta:
        model = DocumentoTerceiro
        fields = ['id', 'terceiro', 'tipo', 'tipo_rotulo', 'descricao', 'orgao', 'numero', 'emissao', 'validade',
                  'arquivo', 'arquivo_url', 'arquivo_nome', 'obrigatorio', 'situacao', 'dias_para_vencer',
                  'substituido_em', 'enviado_por_nome', 'criado_em']
        read_only_fields = ['substituido_em', 'criado_em']
        extra_kwargs = {'arquivo': {'write_only': True, 'required': False}}

    def get_arquivo_url(self, obj):
        return _url_arquivo(self, obj.arquivo)

    def get_arquivo_nome(self, obj):
        return obj.arquivo.name.rsplit('/', 1)[-1] if obj.arquivo else None

    def get_enviado_por_nome(self, obj):
        return nome_usuario(obj.enviado_por)

    def validate(self, dados):
        emissao = dados.get('emissao', getattr(self.instance, 'emissao', None))
        validade = dados.get('validade', getattr(self.instance, 'validade', None))
        if emissao and validade and validade < emissao:
            raise serializers.ValidationError({'validade': 'A validade é anterior à emissão.'})
        arquivo = dados.get('arquivo')
        if arquivo and arquivo.size > 25 * 1024 * 1024:
            raise serializers.ValidationError({'arquivo': 'Limite de 25 MB por arquivo.'})
        return dados


class TerceiroSerializer(serializers.ModelSerializer):
    categoria_rotulo = serializers.CharField(source='get_categoria_display', read_only=True)
    situacao_documental = serializers.CharField(read_only=True)
    documentos = serializers.SerializerMethodField()
    total_requisitos = serializers.IntegerField(read_only=True, default=0)
    planos_abertos = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Terceiro
        fields = ['id', 'razao_social', 'nome_fantasia', 'cnpj', 'categoria', 'categoria_rotulo', 'servico', 'unidade',
                  'contato_nome', 'telefone', 'email', 'contrato_fim', 'ativo', 'observacao', 'situacao_documental',
                  'documentos', 'total_requisitos', 'planos_abertos', 'criado_em', 'atualizado_em']
        read_only_fields = ['criado_em', 'atualizado_em']

    def get_documentos(self, obj):
        """Só a versão atual de cada documento; o histórico vem de documentos-terceiros/?historico=1."""
        return DocumentoTerceiroSerializer(obj.documentos_vigentes(), many=True, context=self.context).data

    def validate_cnpj(self, valor):
        digitos = ''.join(c for c in (valor or '') if c.isdigit())
        if not digitos:
            return ''
        if len(digitos) != 14 or not cnpj_valido(digitos):
            raise serializers.ValidationError('CNPJ inválido.')
        return f'{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}'


def cnpj_valido(d: str) -> bool:
    if len(set(d)) == 1:
        return False
    for tamanho in (12, 13):
        pesos = list(range(tamanho - 7, 1, -1)) + list(range(9, 1, -1))
        soma = sum(int(d[i]) * pesos[i] for i in range(tamanho))
        digito = 0 if soma % 11 < 2 else 11 - soma % 11
        if int(d[tamanho]) != digito:
            return False
    return True


class ConfiguracaoAvisosSerializer(serializers.ModelSerializer):
    atualizado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = ConfiguracaoAvisos
        fields = ['dias_verificacao', 'dias_plano', 'dias_licenca', 'dias_documento', 'email_ativo', 'email_responsaveis',
                  'email_destinatarios', 'email_frequencia', 'email_dia_semana', 'ultimo_envio', 'ultimo_envio_resumo',
                  'atualizado_por_nome', 'atualizado_em']
        read_only_fields = ['ultimo_envio', 'ultimo_envio_resumo', 'atualizado_em']
        extra_kwargs = {f: {'min_value': 1, 'max_value': 730}
                        for f in ('dias_verificacao', 'dias_plano', 'dias_licenca', 'dias_documento')}

    def get_atualizado_por_nome(self, obj):
        return nome_usuario(obj.atualizado_por)

    def validate_email_destinatarios(self, valor):
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError as ErroDjango
        lista = ConfiguracaoAvisos(email_destinatarios=valor or '').lista_destinatarios()
        for e in lista:
            try:
                validate_email(e)
            except ErroDjango:
                raise serializers.ValidationError(f'E-mail inválido: {e}')
        return '\n'.join(lista)
