from rest_framework import serializers

from .models import AreaInteresse, Candidato, Processo, Vaga


class AreaInteresseSerializer(serializers.ModelSerializer):
    total_candidatos = serializers.IntegerField(read_only=True)

    class Meta:
        model = AreaInteresse
        fields = ['id', 'nome', 'ativo', 'ordem', 'total_candidatos']


class CandidatoListSerializer(serializers.ModelSerializer):
    """Versão enxuta para a listagem do banco de talentos (2.300+ registros)."""

    idade = serializers.IntegerField(read_only=True)
    areas_interesse_nomes = serializers.SerializerMethodField()
    total_processos = serializers.IntegerField(read_only=True)
    ultimo_parecer = serializers.SerializerMethodField()
    contratado_alguma_vez = serializers.SerializerMethodField()

    class Meta:
        model = Candidato
        fields = [
            'id', 'id_legado', 'nome', 'cidade', 'telefone_principal', 'telefone_contato',
            'sexo', 'ano_nascimento', 'data_nascimento', 'idade', 'escolaridade',
            'funcao_desejada', 'pcd', 'ja_trabalhou_db', 'data_recebimento',
            'pasta_arquivo', 'observacoes', 'ativo',
            'areas_interesse', 'areas_interesse_nomes', 'total_processos',
            'ultimo_parecer', 'contratado_alguma_vez',
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


class CandidatoSerializer(serializers.ModelSerializer):
    """Currículo completo -- usado no detalhe, no formulário e no PDF."""

    idade = serializers.IntegerField(read_only=True)
    areas_interesse_nomes = serializers.SerializerMethodField()
    processos_resumo = serializers.SerializerMethodField()

    class Meta:
        model = Candidato
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']

    def get_areas_interesse_nomes(self, obj):
        return [a.nome for a in obj.areas_interesse.all()]

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

    class Meta:
        model = Processo
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'etapa']
