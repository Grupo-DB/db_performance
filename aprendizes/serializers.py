from rest_framework import serializers

from . import jovem_aprendiz
from .models import Acompanhamento, Etapa, AvaliacaoJovemAprendiz


class EtapaSerializer(serializers.ModelSerializer):
    tipo_rotulo = serializers.CharField(source='get_tipo_display', read_only=True)
    situacao_rotulo = serializers.CharField(source='get_situacao_display', read_only=True)
    concluido_por_nome = serializers.SerializerMethodField()
    # Para a lista do mês, que mostra etapas de várias pessoas.
    nome = serializers.CharField(source='acompanhamento.nome', read_only=True)
    setor = serializers.CharField(source='acompanhamento.setor', read_only=True)
    cargo = serializers.CharField(source='acompanhamento.cargo', read_only=True)
    data_admissao = serializers.DateField(source='acompanhamento.data_admissao', read_only=True)
    situacao_pessoa = serializers.CharField(source='acompanhamento.situacao', read_only=True)

    class Meta:
        model = Etapa
        fields = [
            'id', 'acompanhamento', 'tipo', 'tipo_rotulo', 'vencimento', 'situacao', 'situacao_rotulo',
            'avaliacao_feita', 'feedback_dado', 'brinde_entregue', 'camiseta_entregue', 'plano_saude_informado',
            'pendencia', 'observacao', 'concluido_em', 'concluido_por_nome',
            'nome', 'setor', 'cargo', 'data_admissao', 'situacao_pessoa',
        ]
        read_only_fields = ['concluido_em']

    def get_concluido_por_nome(self, obj):
        u = obj.concluido_por
        if not u:
            return None
        colaborador = getattr(u, 'colaborador', None)
        return (colaborador.nome if colaborador else '') or u.get_full_name() or u.username


class AcompanhamentoSerializer(serializers.ModelSerializer):
    etapas = EtapaSerializer(many=True, read_only=True)
    situacao_rotulo = serializers.CharField(source='get_situacao_display', read_only=True)

    class Meta:
        model = Acompanhamento
        fields = [
            'id', 'colaborador', 'nome', 'setor', 'cargo', 'data_admissao', 'situacao', 'situacao_rotulo',
            'observacao', 'etapas', 'criado_em',
        ]

    def validate_nome(self, valor):
        if not valor.strip():
            raise serializers.ValidationError('Informe o nome.')
        return valor.strip()


class AvaliacaoJovemAprendizSerializer(serializers.ModelSerializer):
    media = serializers.SerializerMethodField()
    tipo_rotulo = serializers.CharField(source='get_tipo_display', read_only=True)
    evolucao_rotulo = serializers.CharField(source='get_evolucao_display', read_only=True)
    criado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = AvaliacaoJovemAprendiz
        fields = ['id', 'tipo', 'tipo_rotulo', 'colaborador', 'nome', 'setor', 'data', 'notas', 'respostas', 'evolucao',
                  'evolucao_rotulo', 'competencia_prioritaria', 'avaliador', 'observacao', 'media', 'criado_por_nome',
                  'criado_em', 'atualizado_em']
        read_only_fields = ['criado_em', 'atualizado_em']

    def get_media(self, obj):
        return jovem_aprendiz.media(obj.notas)

    def get_criado_por_nome(self, obj):
        u = obj.criado_por
        return (u.get_full_name() or u.username) if u else ''

    def validate(self, attrs):
        tipo = attrs.get('tipo') or getattr(self.instance, 'tipo', None)
        notas = attrs.get('notas', getattr(self.instance, 'notas', None)) or {}
        faltando = [c for c in jovem_aprendiz.CHAVES if c not in notas]
        if faltando:
            raise serializers.ValidationError({'notas': f'Marque a nota de todas as competências ({len(faltando)} em branco).'})
        extras = set(notas) - set(jovem_aprendiz.CHAVES)
        if extras:
            raise serializers.ValidationError({'notas': f'Competência desconhecida: {", ".join(sorted(extras))}.'})
        try:
            attrs['notas'] = {c: int(notas[c]) for c in jovem_aprendiz.CHAVES}
        except (TypeError, ValueError):
            raise serializers.ValidationError({'notas': 'Nota deve ser de 1 a 4.'})
        if any(v not in (1, 2, 3, 4) for v in attrs['notas'].values()):
            raise serializers.ValidationError({'notas': 'Nota deve ser de 1 a 4.'})
        respostas = attrs.get('respostas')
        if respostas is not None:
            validas = {k for k, _ in jovem_aprendiz.PERGUNTAS.get(tipo, [])}
            attrs['respostas'] = {k: str(v)[:3000] for k, v in respostas.items() if k in validas}
        if tipo == AvaliacaoJovemAprendiz.AUTO:
            attrs['evolucao'] = ''
            attrs['competencia_prioritaria'] = ''
        elif attrs.get('competencia_prioritaria') and attrs['competencia_prioritaria'] not in jovem_aprendiz.CHAVES:
            raise serializers.ValidationError({'competencia_prioritaria': 'Competência desconhecida.'})
        return attrs
