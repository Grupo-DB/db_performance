from django.contrib.auth.models import User
from rest_framework import serializers

from . import regras
from .models import Contato, Cotacao, MetaAgro, Produtor, VendedorAgro


def _nome(user) -> str:
    return (user.get_full_name() or user.username) if user else ''


class MetaAgroSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetaAgro
        fields = ['id', 'ano', 'toneladas']


class VendedorAgroSerializer(serializers.ModelSerializer):
    nome = serializers.CharField(read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    metas = MetaAgroSerializer(many=True, read_only=True)

    class Meta:
        model = VendedorAgro
        fields = ['id', 'user', 'username', 'nome', 'papel', 'carteira', 'repcods', 'municipios', 'ativo', 'metas']
        read_only_fields = ['municipios']  # muda pela ação territorio, que tira o município de outro vendedor

    def validate_repcods(self, v):
        try:
            return sorted({int(x) for x in v or []})
        except (TypeError, ValueError):
            raise serializers.ValidationError('Informe só números (REPCOD do SGA).')


class ProdutorSerializer(serializers.ModelSerializer):
    potencial_t = serializers.FloatField(read_only=True)
    vendedor_nome = serializers.SerializerMethodField()
    laudo_url = serializers.SerializerMethodField()

    class Meta:
        model = Produtor
        fields = [
            'id', 'nome', 'documento', 'whatsapp', 'municipio', 'tipo', 'raio_atuacao_km', 'cliente_sga', 'cadastro', 'origem',
            'vendedor', 'vendedor_nome',
            'fornecedor_atual', 'concorrente_nome', 'preco_concorrente', 'frete_concorrente',
            'area_ha', 'culturas', 'ciclo_anos', 'ultima_aplicacao', 'dose_t_ha', 'cooperativa',
            'faz_analise', 'laudo_url', 'coleta_oferecida', 'perfil_confirmado_ano', 'potencial_t',
            'car_codigo', 'ajuste_cadastro', 'ajuste_pedido_em', 'criado_em', 'atualizado_em', 'cadastrado_em',
        ]
        read_only_fields = ['cliente_sga', 'cadastro', 'origem', 'vendedor', 'ajuste_cadastro', 'ajuste_pedido_em',
                            'criado_em', 'atualizado_em', 'cadastrado_em']

    def get_vendedor_nome(self, o):
        return o.vendedor.nome if o.vendedor else ''

    def get_laudo_url(self, o):
        if not o.laudo:
            return None
        req = self.context.get('request')
        return req.build_absolute_uri(o.laudo.url) if req else o.laudo.url

    def validate_culturas(self, v):
        return [c for c in (v or []) if c in regras.CULTURAS]

    def validate_ciclo_anos(self, v):
        if v is not None and v > 10:
            raise serializers.ValidationError('Ciclo de calagem de no máximo 10 anos.')
        return v


class ContatoSerializer(serializers.ModelSerializer):
    produtor_nome = serializers.CharField(source='produtor.nome', read_only=True)
    vendedor_nome = serializers.SerializerMethodField()
    tipo_rotulo = serializers.CharField(source='get_tipo_display', read_only=True)
    resultado_rotulo = serializers.CharField(source='get_resultado_display', read_only=True)

    class Meta:
        model = Contato
        fields = ['id', 'produtor', 'produtor_nome', 'vendedor', 'vendedor_nome', 'tipo', 'tipo_rotulo', 'data_hora',
                  'latitude', 'longitude', 'resultado', 'resultado_rotulo', 'observacao',
                  'proximo_passo', 'proximo_data', 'proximo_feito_em', 'criado_em']
        read_only_fields = ['vendedor', 'proximo_feito_em', 'criado_em']

    def get_vendedor_nome(self, o):
        return o.vendedor.nome if o.vendedor else ''

    def validate_proximo_passo(self, v):
        if not (v or '').strip():
            raise serializers.ValidationError('Todo contato termina com o próximo passo.')
        return v.strip()


class CotacaoSerializer(serializers.ModelSerializer):
    produtor_nome = serializers.CharField(source='produtor.nome', read_only=True)
    produtor_tipo = serializers.CharField(source='produtor.get_tipo_display', read_only=True)
    produtor_cadastro = serializers.CharField(source='produtor.cadastro', read_only=True)
    cliente_sga = serializers.IntegerField(source='produtor.cliente_sga', read_only=True)
    vendedor_nome = serializers.SerializerMethodField()
    carteira = serializers.SerializerMethodField()
    status_rotulo = serializers.CharField(source='get_status_display', read_only=True)
    contra_condicao_rotulo = serializers.CharField(source='get_contra_condicao_display', read_only=True)
    decidido_por_nome = serializers.SerializerMethodField()
    lancado_por_nome = serializers.SerializerMethodField()
    a_vista = serializers.SerializerMethodField()
    desconto = serializers.SerializerMethodField()
    desconto_efetivo = serializers.SerializerMethodField()
    preco_final = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    prazo_final = serializers.IntegerField(read_only=True)

    class Meta:
        model = Cotacao
        fields = [
            'id', 'produtor', 'produtor_nome', 'produtor_tipo', 'produtor_cadastro', 'cliente_sga', 'contato',
            'vendedor', 'vendedor_nome', 'carteira', 'status', 'status_rotulo',
            'produto_cod', 'produto_nome', 'unidade', 'filial', 'volume_t', 'retirada',
            'preco', 'preco_padrao', 'prazo_dias', 'justificativa', 'pendencia_credito',
            'a_vista', 'desconto', 'desconto_efetivo', 'preco_final', 'prazo_final',
            'decidido_por_nome', 'decidido_em', 'aprovada_direto', 'aprovada_em',
            'contra_preco', 'contra_prazo', 'contra_condicao', 'contra_condicao_rotulo', 'recado', 'respondida_em',
            'pedido_sga', 'lancado_por_nome', 'lancado_em', 'conferencia', 'divergente', 'corrigido_em',
            'criado_em', 'atualizado_em',
        ]
        read_only_fields = [f for f in fields if f not in (
            'produtor', 'contato', 'produto_cod', 'filial', 'volume_t', 'retirada', 'preco', 'prazo_dias', 'justificativa')]

    def get_vendedor_nome(self, o):
        return o.vendedor.nome if o.vendedor else _nome(o.autor)

    def get_carteira(self, o):
        return o.vendedor.carteira if o.vendedor else ''

    def get_decidido_por_nome(self, o):
        return _nome(o.decidido_por)

    def get_lancado_por_nome(self, o):
        return _nome(o.lancado_por)

    def get_a_vista(self, o):
        return regras.a_vista(o.preco_final, o.prazo_final)

    def get_desconto(self, o):
        return regras.desconto_pct(o.preco_final, o.preco_padrao)

    def get_desconto_efetivo(self, o):
        return regras.desconto_efetivo(o.preco_final, o.prazo_final, o.preco_padrao)

    def validate_prazo_dias(self, v):
        if v not in regras.PRAZOS:
            raise serializers.ValidationError('Prazo deve ser à vista, 30, 60 ou 90 dias.')
        return v

    def validate_volume_t(self, v):
        if v <= 0:
            raise serializers.ValidationError('Informe o volume em toneladas.')
        return v

    def validate_preco(self, v):
        if v <= 0:
            raise serializers.ValidationError('Informe o preço por tonelada.')
        return v
