from rest_framework import serializers

from .models import Evento, Participante, Premio, Sorteio
from .regras import dias_uteis


class EventoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Evento
        fields = ['id', 'nome', 'data_inicio', 'data_fim', 'dias', 'ativo', 'criado_em']
        read_only_fields = ['criado_em']

    def validate(self, attrs):
        inicio = attrs.get('data_inicio', getattr(self.instance, 'data_inicio', None))
        fim = attrs.get('data_fim', getattr(self.instance, 'data_fim', None))
        if inicio and fim and fim < inicio:
            raise serializers.ValidationError({'data_fim': 'A data final é anterior à inicial.'})
        dias = attrs.get('dias')
        if dias is not None:
            attrs['dias'] = sorted(set(str(d)[:10] for d in dias))
        elif self.instance is None and inicio and fim:
            attrs['dias'] = dias_uteis(inicio, fim)
        return attrs


class ParticipanteSerializer(serializers.ModelSerializer):
    # 'AAAA-MM-DD|M' — compacto porque a tela de presença carrega o evento inteiro.
    presencas = serializers.SerializerMethodField()
    sorteio = serializers.SerializerMethodField()

    class Meta:
        model = Participante
        fields = ['id', 'evento', 'matricula', 'nome', 'setor', 'empresa', 'ativo', 'presencas', 'sorteio']

    def get_presencas(self, obj):
        return [f'{p.data.isoformat()}|{p.turno}' for p in obj.presencas.all()]

    def get_sorteio(self, obj):
        s = next(iter(obj.sorteios.all()), None)
        if not s:
            return None
        return {'id': s.id, 'premio': s.premio.descricao, 'status': s.status}


class SorteioSerializer(serializers.ModelSerializer):
    participante_nome = serializers.CharField(source='participante.nome', read_only=True)
    participante_matricula = serializers.CharField(source='participante.matricula', read_only=True)
    participante_setor = serializers.CharField(source='participante.setor', read_only=True)
    premio_descricao = serializers.CharField(source='premio.descricao', read_only=True)
    premio_categoria = serializers.CharField(source='premio.categoria', read_only=True)
    sorteado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = Sorteio
        fields = [
            'id', 'evento', 'premio', 'premio_descricao', 'premio_categoria',
            'participante', 'participante_nome', 'participante_matricula', 'participante_setor',
            'status', 'total_concorrentes', 'sorteado_por_nome', 'sorteado_em',
        ]

    def get_sorteado_por_nome(self, obj):
        u = obj.sorteado_por
        return (u.get_full_name() or u.username) if u else None


class PremioSerializer(serializers.ModelSerializer):
    ganhadores = serializers.SerializerMethodField()
    restantes = serializers.SerializerMethodField()

    class Meta:
        model = Premio
        fields = [
            'id', 'evento', 'descricao', 'categoria', 'regra', 'data', 'turno',
            'quantidade', 'ordem', 'patrocinador', 'ganhadores', 'restantes',
        ]

    def validate(self, attrs):
        regra = attrs.get('regra', getattr(self.instance, 'regra', None))
        data = attrs.get('data', getattr(self.instance, 'data', None))
        if regra == Premio.REGRA_DIA and not data:
            raise serializers.ValidationError({'data': 'Informe o dia do sorteio para a regra "Presentes no dia".'})
        if regra != Premio.REGRA_DIA:
            attrs['data'] = None
            attrs['turno'] = ''
        return attrs

    def _validos(self, obj):
        return [s for s in obj.sorteios.all() if s.status == Sorteio.STATUS_GANHADOR]

    def get_ganhadores(self, obj):
        return [
            {'id': s.id, 'nome': s.participante.nome, 'matricula': s.participante.matricula,
             'setor': s.participante.setor}
            for s in self._validos(obj)
        ]

    def get_restantes(self, obj):
        return max(0, obj.quantidade - len(self._validos(obj)))
