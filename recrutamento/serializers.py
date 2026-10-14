from rest_framework import serializers

from .models import (
    AreaInteresse,
    Candidato,
    Desligamento,
    FichaAnexo,
    FichaEntrevista,
    FolhaPonto,
    FormularioDesligamento,
    Processo,
    Vaga,
)


class AreaInteresseSerializer(serializers.ModelSerializer):
    total_candidatos = serializers.IntegerField(read_only=True)

    class Meta:
        model = AreaInteresse
        fields = ['id', 'nome', 'ativo', 'ordem', 'total_candidatos']


class AnexoCurriculoMixin:
    """
    Expõe o arquivo do currículo como URL + nome legível.

    Fica fora do campo `anexo` de propósito: `anexo` só aceita upload
    (multipart), e a tela salva o cadastro em JSON — se o valor lido fosse o
    mesmo campo, o PUT devolveria a URL como se fosse arquivo e o DRF recusaria.
    """

    def get_anexo_url(self, obj):
        if not obj.anexo:
            return None
        pedido = self.context.get('request')
        # URL absoluta quando há request: o front roda em outra origem no
        # desenvolvimento e um caminho relativo apontaria para o lugar errado.
        return pedido.build_absolute_uri(obj.anexo.url) if pedido else obj.anexo.url

    def get_anexo_nome(self, obj):
        return obj.anexo.name.rsplit('/', 1)[-1] if obj.anexo else None


class CandidatoListSerializer(AnexoCurriculoMixin, serializers.ModelSerializer):
    """Versão enxuta para a listagem do banco de talentos (2.300+ registros)."""

    idade = serializers.IntegerField(read_only=True)
    anexo_url = serializers.SerializerMethodField()
    anexo_nome = serializers.SerializerMethodField()
    areas_interesse_nomes = serializers.SerializerMethodField()
    total_processos = serializers.IntegerField(read_only=True)
    total_fichas = serializers.IntegerField(read_only=True)
    ultimo_parecer = serializers.SerializerMethodField()
    contratado_alguma_vez = serializers.SerializerMethodField()

    class Meta:
        model = Candidato
        fields = [
            'id', 'id_legado', 'nome', 'cidade', 'telefone_principal', 'telefone_contato',
            'sexo', 'ano_nascimento', 'data_nascimento', 'idade', 'escolaridade',
            'funcao_desejada', 'pcd', 'ja_trabalhou_db', 'data_recebimento',
            'pasta_arquivo', 'anexo_url', 'anexo_nome', 'observacoes', 'ativo',
            'areas_interesse', 'areas_interesse_nomes', 'total_processos',
            'total_fichas', 'ultimo_parecer', 'contratado_alguma_vez',
        ]

    def get_areas_interesse_nomes(self, obj):
        return [a.nome for a in obj.areas_interesse.all()]

    def _processos(self, obj):
        # ``prefetch_related('processos')`` no queryset evita N+1 aqui.
        return sorted(
            obj.processos.all(),
            key=lambda p: (p.data_contato or p.created_at.date()),
            reverse=True,
        )

    def get_ultimo_parecer(self, obj):
        for processo in self._processos(obj):
            if processo.parecer:
                return processo.parecer
        return None

    def get_contratado_alguma_vez(self, obj):
        return any(p.contratado for p in obj.processos.all())


class CandidatoSerializer(AnexoCurriculoMixin, serializers.ModelSerializer):
    """Currículo completo -- usado no detalhe, no formulário e no PDF."""

    idade = serializers.IntegerField(read_only=True)
    areas_interesse_nomes = serializers.SerializerMethodField()
    processos_resumo = serializers.SerializerMethodField()
    fichas_resumo = serializers.SerializerMethodField()
    anexo_url = serializers.SerializerMethodField()
    anexo_nome = serializers.SerializerMethodField()

    class Meta:
        model = Candidato
        fields = '__all__'
        # `anexo` só entra pelo endpoint /anexo/ (multipart). Deixá-lo gravável
        # aqui quebraria o PUT da tela, que manda o cadastro inteiro em JSON.
        read_only_fields = ['created_at', 'updated_at', 'anexo']

    def get_areas_interesse_nomes(self, obj):
        return [a.nome for a in obj.areas_interesse.all()]

    def get_fichas_resumo(self, obj):
        """Fichas F-018 do candidato -- alimenta a aba Entrevistas do currículo."""
        return [
            {
                'id': f.id,
                'data_entrevista': f.data_entrevista,
                'cargo_funcao': f.cargo_funcao,
                'setor': f.setor,
                'vaga': f.vaga.descricao if f.vaga else None,
                'processo_id': f.processo_id,
                'resultado': f.resultado,
                'atende_requisitos': f.atende_requisitos,
                'avaliador_1': f.avaliador_1,
                'modelo': f.modelo,
            }
            for f in obj.fichas.all().order_by('-data_entrevista', '-id')
        ]

    def get_processos_resumo(self, obj):
        return [
            {
                'id': p.id,
                'vaga': p.vaga.descricao if p.vaga else None,
                'vaga_id': p.vaga_id,
                'data_contato': p.data_contato,
                'data_entrevista': p.data_entrevista,
                'parecer': p.parecer,
                'etapa': p.etapa,
                'contratado': p.contratado,
                'data_contratacao': p.data_contratacao,
            }
            for p in obj.processos.all().order_by('-data_contato', '-id')
        ]


class VagaSerializer(serializers.ModelSerializer):
    tempo_retorno = serializers.IntegerField(read_only=True)
    dias_em_aberto = serializers.IntegerField(read_only=True)
    atrasada = serializers.BooleanField(read_only=True)
    sem_data_abertura = serializers.BooleanField(read_only=True)
    area_nome = serializers.CharField(source='area.nome', read_only=True)
    total_candidatos = serializers.IntegerField(read_only=True)
    total_entrevistados = serializers.IntegerField(read_only=True)
    total_contratados = serializers.IntegerField(read_only=True)

    class Meta:
        model = Vaga
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class ProcessoSerializer(serializers.ModelSerializer):
    candidato_nome = serializers.CharField(source='candidato.nome', read_only=True)
    candidato_telefone = serializers.CharField(source='candidato.telefone_principal', read_only=True)
    candidato_cidade = serializers.CharField(source='candidato.cidade', read_only=True)
    vaga_descricao = serializers.CharField(source='vaga.descricao', read_only=True)
    vaga_requisitante = serializers.CharField(source='vaga.requisitante', read_only=True)
    tempo_para_entrevista = serializers.IntegerField(read_only=True)
    tempo_retorno_candidato = serializers.IntegerField(read_only=True)
    etapa = serializers.CharField(read_only=True)  # sempre derivada em Processo.save()
    ficha_id = serializers.SerializerMethodField()

    class Meta:
        model = Processo
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'etapa']

    def get_ficha_id(self, obj):
        """Ficha F-018 mais recente do processo -- ``null`` quando ainda não existe."""
        fichas = sorted(
            obj.fichas.all(),
            key=lambda f: (f.data_entrevista or f.created_at.date(), f.id),
            reverse=True,
        )
        return fichas[0].id if fichas else None


class FichaEntrevistaListSerializer(serializers.ModelSerializer):
    """Linha da listagem de fichas -- sem os blocos de texto longo."""

    candidato_nome = serializers.CharField(source='candidato.nome', read_only=True)
    candidato_cidade = serializers.CharField(source='candidato.cidade', read_only=True)
    candidato_telefone = serializers.CharField(source='candidato.telefone_principal', read_only=True)
    vaga_descricao = serializers.CharField(source='vaga.descricao', read_only=True)
    total_anexos = serializers.IntegerField(read_only=True)

    class Meta:
        model = FichaEntrevista
        fields = [
            'id', 'candidato', 'candidato_nome', 'candidato_cidade', 'candidato_telefone',
            'processo', 'vaga', 'vaga_descricao', 'data_entrevista',
            'cargo_funcao', 'setor', 'atende_requisitos', 'resultado',
            'modelo', 'avaliacao_requisitos',
            'avaliador_1', 'total_anexos', 'created_at', 'updated_at',
        ]


class FichaAnexoSerializer(serializers.ModelSerializer):
    """Anexo da ficha lido pela tela: URL para baixar + nome e tamanho legíveis."""

    url = serializers.SerializerMethodField()
    nome = serializers.CharField(read_only=True)
    tamanho = serializers.IntegerField(read_only=True)

    class Meta:
        model = FichaAnexo
        fields = ['id', 'ficha', 'url', 'nome', 'tamanho', 'descricao', 'enviado_por', 'enviado_em']
        read_only_fields = ['ficha', 'enviado_por', 'enviado_em']

    def get_url(self, obj):
        if not obj.arquivo:
            return None
        pedido = self.context.get('request')
        # Absoluta quando há request: no desenvolvimento o front roda em outra
        # origem e o caminho relativo apontaria para o servidor errado.
        return pedido.build_absolute_uri(obj.arquivo.url) if pedido else obj.arquivo.url


class FichaEntrevistaSerializer(serializers.ModelSerializer):
    """Ficha completa -- formulário da tela e PDF do F-018."""

    candidato_nome = serializers.CharField(source='candidato.nome', read_only=True)
    candidato_cidade = serializers.CharField(source='candidato.cidade', read_only=True)
    candidato_telefone = serializers.CharField(source='candidato.telefone_principal', read_only=True)
    vaga_descricao = serializers.CharField(source='vaga.descricao', read_only=True)
    vaga_requisitante = serializers.CharField(source='vaga.requisitante', read_only=True)
    # Só leitura: o arquivo entra pelo endpoint /anexos/ (multipart), porque a
    # tela salva a ficha inteira em JSON.
    anexos = FichaAnexoSerializer(many=True, read_only=True)

    class Meta:
        model = FichaEntrevista
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']

    def validate(self, attrs):
        processo = attrs.get('processo', getattr(self.instance, 'processo', None))
        candidato = attrs.get('candidato', getattr(self.instance, 'candidato', None))
        if processo and candidato and processo.candidato_id != candidato.id:
            raise serializers.ValidationError(
                {'processo': 'O processo selecionado é de outro candidato.'}
            )
        return attrs


class FolhaPontoSerializer(serializers.ModelSerializer):
    """Uma competência de folha ponto importada -- a tela lista e acompanha o
    status por aqui."""

    rotulo = serializers.CharField(read_only=True)
    nome_arquivo = serializers.SerializerMethodField()

    class Meta:
        model = FolhaPonto
        fields = [
            'id', 'competencia', 'rotulo', 'periodo_inicio', 'periodo_fim',
            'arquivo', 'nome_arquivo', 'status', 'mensagem', 'cartoes_lidos',
            'cartoes_sem_controle', 'importado_por', 'importado_em', 'processado_em',
        ]
        read_only_fields = [
            'competencia', 'periodo_inicio', 'periodo_fim', 'status', 'mensagem',
            'cartoes_lidos', 'cartoes_sem_controle', 'importado_por',
            'importado_em', 'processado_em',
        ]

    def get_nome_arquivo(self, obj):
        return obj.arquivo.name.rsplit('/', 1)[-1] if obj.arquivo else ''


# ── Desligamentos ────────────────────────────────────────────────────────
class FormularioDesligamentoSerializer(serializers.ModelSerializer):
    formulario_rotulo = serializers.CharField(source='get_formulario_display', read_only=True)
    preenchido_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = FormularioDesligamento
        fields = ['id', 'desligamento', 'formulario', 'formulario_rotulo', 'tipo_informado', 'respostas',
                  'classificacao', 'classificacao_revisada', 'classificado_em', 'erro_classificacao',
                  'data_preenchimento', 'preenchido_por_nome', 'origem', 'criado_em', 'atualizado_em']
        read_only_fields = ['classificado_em', 'erro_classificacao', 'origem', 'criado_em', 'atualizado_em']

    def get_preenchido_por_nome(self, obj):
        u = obj.preenchido_por
        return (u.get_full_name() or u.username) if u else None

    def validate_respostas(self, valor):
        from .desligamento import PERGUNTAS
        if not isinstance(valor, dict):
            raise serializers.ValidationError('Formato inválido.')
        formulario = self.initial_data.get('formulario') or getattr(self.instance, 'formulario', None)
        chaves = {p['chave'] for p in PERGUNTAS.get(formulario, [])}
        return {k: v for k, v in valor.items() if k in chaves}

    def validate_classificacao(self, valor):
        from .desligamento import CLASSES, perguntas_classificadas
        formulario = self.initial_data.get('formulario') or getattr(self.instance, 'formulario', None)
        validos = {p['chave']: {v for v, _ in CLASSES[p['classe']]} for p in perguntas_classificadas(formulario or '')}
        return {k: v for k, v in (valor or {}).items() if k in validos and v in validos[k]}


class DesligamentoListSerializer(serializers.ModelSerializer):
    tipo_rotulo = serializers.CharField(source='get_tipo_display', read_only=True)
    tempo_casa_meses = serializers.IntegerField(read_only=True)
    formularios = serializers.SerializerMethodField()
    divergencia_tipo = serializers.SerializerMethodField()

    class Meta:
        model = Desligamento
        fields = ['id', 'colaborador', 'nome', 'cargo', 'setor', 'data_admissao', 'data_desligamento', 'tipo',
                  'tipo_rotulo', 'gestor', 'gestor_nome', 'tempo_casa_meses', 'tempo_casa_texto', 'formularios',
                  'divergencia_tipo']

    def get_formularios(self, obj):
        return {f.formulario: {'id': f.id, 'tipo_informado': f.tipo_informado,
                               'classificado': bool(f.classificacao), 'revisada': f.classificacao_revisada}
                for f in obj.formularios.all()}

    def get_divergencia_tipo(self, obj):
        tipos = {f.tipo_informado for f in obj.formularios.all() if f.tipo_informado}
        return len(tipos) > 1


class DesligamentoSerializer(DesligamentoListSerializer):
    formularios = FormularioDesligamentoSerializer(many=True, read_only=True)

    class Meta(DesligamentoListSerializer.Meta):
        fields = DesligamentoListSerializer.Meta.fields + ['observacao', 'criado_em', 'atualizado_em']
        read_only_fields = ['criado_em', 'atualizado_em']
        # Escolhido do cadastro, o nome vem dele (validate); obrigatório só sem colaborador.
        extra_kwargs = {'nome': {'required': False}}

    def validate(self, dados):
        """Escolhido do cadastro, o que estiver em branco vem dele (a tela já preenche; a API garante)."""
        c = dados.get('colaborador')
        if c:
            dados.setdefault('nome', c.nome)
            if not dados.get('nome'):
                dados['nome'] = c.nome
            if not dados.get('cargo') and c.cargo_id:
                dados['cargo'] = c.cargo.nome
            if not dados.get('setor') and c.setor_id:
                dados['setor'] = c.setor.nome
            if not dados.get('data_admissao') and c.data_admissao:
                dados['data_admissao'] = c.data_admissao.date()
        g = dados.get('gestor')
        if g and not dados.get('gestor_nome'):
            dados['gestor_nome'] = g.nome
        if not (dados.get('nome') or getattr(self.instance, 'nome', '')):
            raise serializers.ValidationError({'colaborador': 'Escolha o colaborador desligado.'})
        return dados
