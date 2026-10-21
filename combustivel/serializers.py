import io
from datetime import timedelta

from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import serializers

from .models import Abastecimento, ChaveIntegracao, LoteIntegracao, Lubrificacao, MedicaoTanque, Tanque, Transferencia

FOTO_MAX_BYTES = 8 * 1024 * 1024
FOTO_MAX_PIXELS = 40_000_000
FOTO_LADO_FINAL = 1600
FORMATOS_FOTO = {'JPEG', 'PNG', 'WEBP', 'MPO'}


class FotoSegura(serializers.ImageField):
    """
    Aceita só imagem de verdade (aberta pelo Pillow, formato da lista, tamanho e resolução
    limitados) e devolve SEMPRE um JPEG novo, reduzido e sem metadados: some o GPS do
    aparelho e qualquer conteúdo escondido num arquivo "disfarçado" de foto.
    """

    def to_internal_value(self, data):
        if getattr(data, 'size', 0) > FOTO_MAX_BYTES:
            raise serializers.ValidationError('Foto maior que 8 MB.')
        try:
            data.seek(0)
            img = Image.open(data)
            if (img.format or '').upper() not in FORMATOS_FOTO:
                raise serializers.ValidationError('Envie a foto em JPEG, PNG ou WebP.')
            if img.width * img.height > FOTO_MAX_PIXELS:
                raise serializers.ValidationError('Foto com resolução grande demais.')
            img = ImageOps.exif_transpose(img).convert('RGB')
            img.thumbnail((FOTO_LADO_FINAL, FOTO_LADO_FINAL))
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise serializers.ValidationError('Arquivo não é uma imagem válida.')
        saida = io.BytesIO()
        img.save(saida, 'JPEG', quality=82, optimize=True)
        return ContentFile(saida.getvalue(), name='foto.jpg')


class TanqueSerializer(serializers.ModelSerializer):
    produto_nome = serializers.CharField(read_only=True)

    class Meta:
        model = Tanque
        fields = ['id', 'nome', 'tipo', 'equipamento', 'envia_ao_sga', 'filial', 'produto', 'produto_nome',
                  'capacidade_l', 'estoque_minimo_l', 'bomba_ident', 'ativo', 'criado_em']
        read_only_fields = ['criado_em']

    def validate(self, attrs):
        tipo = attrs.get('tipo', getattr(self.instance, 'tipo', Tanque.FIXO))
        if tipo == Tanque.FIXO:
            # Tanque fixo sempre baixa no SGA; os campos de comboio não se aplicam.
            attrs['envia_ao_sga'] = True
            attrs['equipamento'] = None
        return attrs

    def validate_capacidade_l(self, v):
        if v <= 0:
            raise serializers.ValidationError('Capacidade precisa ser maior que zero.')
        return v


class MedicaoSerializer(serializers.ModelSerializer):
    foto = FotoSegura(required=False, allow_null=True, write_only=True)
    tem_foto = serializers.SerializerMethodField()
    usuario_nome = serializers.SerializerMethodField()
    diferenca_l = serializers.SerializerMethodField()

    class Meta:
        model = MedicaoTanque
        fields = ['id', 'tanque', 'medido_em', 'litros', 'saldo_sistema_l', 'diferenca_l', 'foto', 'tem_foto',
                  'observacao', 'usuario_nome', 'criado_em']
        read_only_fields = ['saldo_sistema_l', 'criado_em']

    def get_tem_foto(self, obj):
        return bool(obj.foto)

    def get_usuario_nome(self, obj):
        return (obj.usuario.get_full_name() or obj.usuario.username) if obj.usuario else ''

    def get_diferenca_l(self, obj):
        if obj.saldo_sistema_l is None:
            return None
        return float(obj.litros - obj.saldo_sistema_l)

    def validate_litros(self, v):
        if v < 0:
            raise serializers.ValidationError('Leitura não pode ser negativa.')
        return v


class AbastecimentoSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False)
    foto_bomba = FotoSegura(required=False, allow_null=True, write_only=True)
    foto_painel = FotoSegura(required=False, allow_null=True, write_only=True)
    tem_foto_bomba = serializers.SerializerMethodField()
    tem_foto_painel = serializers.SerializerMethodField()
    tanque_nome = serializers.CharField(source='tanque.nome', read_only=True)
    produto_nome = serializers.CharField(source='tanque.produto_nome', read_only=True)
    codigo_integracao = serializers.IntegerField(read_only=True)
    registrado_por_nome = serializers.SerializerMethodField()
    situacao_label = serializers.CharField(source='get_situacao_display', read_only=True)

    class Meta:
        model = Abastecimento
        fields = [
            'id', 'uuid', 'codigo_integracao', 'tanque', 'tanque_nome', 'produto_nome', 'abastecido_em',
            'equipamento', 'equipamento_nome', 'placa', 'centro_custo', 'funcionario', 'funcionario_nome',
            'litros', 'horimetro', 'km', 'encerrante_inicial', 'encerrante_final',
            'foto_bomba', 'foto_painel', 'tem_foto_bomba', 'tem_foto_painel', 'latitude', 'longitude', 'observacao',
            'situacao', 'situacao_label', 'alertas', 'bloqueado', 'lote', 'baixa_sga', 'erro_sga',
            'enviado_sga_em', 'baixado_em', 'motivo_cancelamento', 'registrado_por_nome', 'criado_em', 'atualizado_em',
        ]
        # Nome do equipamento/funcionário, placa e centro de custo saem do SGA, não do aparelho.
        read_only_fields = [
            'equipamento_nome', 'placa', 'centro_custo', 'funcionario_nome', 'situacao', 'alertas', 'bloqueado',
            'lote', 'baixa_sga', 'erro_sga', 'enviado_sga_em', 'baixado_em', 'motivo_cancelamento',
            'criado_em', 'atualizado_em',
        ]

    def get_tem_foto_bomba(self, obj):
        return bool(obj.foto_bomba)

    def get_tem_foto_painel(self, obj):
        return bool(obj.foto_painel)

    def get_registrado_por_nome(self, obj):
        u = obj.registrado_por
        return (u.get_full_name() or u.username) if u else ''

    def validate_tanque(self, tanque):
        if not tanque.ativo:
            raise serializers.ValidationError('Tanque inativo.')
        return tanque

    def validate_litros(self, v):
        if v <= 0:
            raise serializers.ValidationError('Quantidade precisa ser maior que zero.')
        return v

    def validate(self, attrs):
        for campo in ('horimetro', 'km', 'encerrante_inicial', 'encerrante_final'):
            if attrs.get(campo) is not None and attrs[campo] < 0:
                raise serializers.ValidationError({campo: 'Não pode ser negativo.'})
        lat, lng = attrs.get('latitude'), attrs.get('longitude')
        if lat is not None and not -90 <= lat <= 90 or lng is not None and not -180 <= lng <= 180:
            raise serializers.ValidationError({'latitude': 'Coordenada inválida.'})
        return attrs


class TransferenciaSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False)
    foto_bomba = FotoSegura(required=False, allow_null=True, write_only=True)
    tem_foto = serializers.SerializerMethodField()
    usuario_nome = serializers.SerializerMethodField()
    destino_nome = serializers.CharField(source='destino.nome', read_only=True)
    origem_nome = serializers.SerializerMethodField()
    abastecimento_situacao = serializers.CharField(source='abastecimento.get_situacao_display', read_only=True, default='')
    abastecimento_uuid = serializers.UUIDField(source='abastecimento.uuid', read_only=True, default=None)
    abastecimento_bloqueado = serializers.BooleanField(source='abastecimento.bloqueado', read_only=True, default=False)
    abastecimento_alertas = serializers.JSONField(source='abastecimento.alertas', read_only=True, default=list)

    class Meta:
        model = Transferencia
        fields = ['id', 'uuid', 'origem', 'origem_nome', 'destino', 'destino_nome', 'transferido_em', 'litros',
                  'encerrante_inicial', 'encerrante_final', 'funcionario', 'funcionario_nome', 'foto_bomba', 'tem_foto',
                  'observacao', 'situacao', 'motivo_cancelamento', 'usuario_nome', 'criado_em', 'abastecimento_uuid',
                  'abastecimento_situacao', 'abastecimento_bloqueado', 'abastecimento_alertas']
        read_only_fields = ['funcionario_nome', 'situacao', 'motivo_cancelamento', 'criado_em']

    def get_tem_foto(self, obj):
        return bool(obj.foto_bomba)

    def get_usuario_nome(self, obj):
        return (obj.usuario.get_full_name() or obj.usuario.username) if obj.usuario else ''

    def get_origem_nome(self, obj):
        return obj.origem.nome if obj.origem else 'Posto externo'

    def validate(self, attrs):
        destino, origem = attrs['destino'], attrs.get('origem')
        if destino.tipo != Tanque.COMBOIO:
            raise serializers.ValidationError({'destino': 'O destino é um comboio.'})
        if origem:
            if origem.tipo != Tanque.FIXO:
                raise serializers.ValidationError({'origem': 'A origem é um tanque fixo.'})
            if origem.produto != destino.produto:
                raise serializers.ValidationError({'origem': 'Tanque e comboio com combustíveis diferentes.'})
            if not destino.envia_ao_sga and destino.equipamento and not attrs.get('funcionario'):
                # Vira abastecimento do caminhão no SGA, que recusa sem funcionário identificado.
                raise serializers.ValidationError({'funcionario': 'Informe quem operou a bomba.'})
        if attrs['litros'] <= 0:
            raise serializers.ValidationError({'litros': 'Quantidade precisa ser maior que zero.'})
        ini, fim = attrs.get('encerrante_inicial'), attrs.get('encerrante_final')
        if ini is not None and fim is not None and fim < ini:
            raise serializers.ValidationError({'encerrante_final': 'Encerrante final menor que o inicial.'})
        return attrs


class LoteSerializer(serializers.ModelSerializer):
    criado_por_nome = serializers.SerializerMethodField()
    situacao_label = serializers.CharField(source='get_situacao_display', read_only=True)

    class Meta:
        model = LoteIntegracao
        fields = ['id', 'formato', 'situacao', 'situacao_label', 'nome_arquivo', 'sha256', 'quantidade', 'litros',
                  'criado_por_nome', 'criado_em', 'atualizado_em']

    def get_criado_por_nome(self, obj):
        u = obj.criado_por
        return (u.get_full_name() or u.username) if u else ''


class ChaveSerializer(serializers.ModelSerializer):
    valida = serializers.BooleanField(read_only=True)
    criado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = ChaveIntegracao
        fields = ['id', 'nome', 'prefixo', 'pode_confirmar', 'ips_permitidos', 'ativa', 'valida', 'expira_em',
                  'ultimo_uso_em', 'ultimo_ip', 'usos', 'criado_por_nome', 'criado_em', 'revogada_em']
        read_only_fields = ['prefixo', 'ativa', 'ultimo_uso_em', 'ultimo_ip', 'usos', 'criado_em', 'revogada_em']

    def get_criado_por_nome(self, obj):
        u = obj.criado_por
        return (u.get_full_name() or u.username) if u else ''

    def validate_ips_permitidos(self, texto):
        import ipaddress
        for linha in (texto or '').splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                ipaddress.ip_network(linha, strict=False)
            except ValueError:
                raise serializers.ValidationError(f'"{linha}" não é um IP ou rede válida.')
        return texto


class LubrificacaoSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(required=False)
    foto = FotoSegura(required=False, allow_null=True, write_only=True)
    tem_foto = serializers.SerializerMethodField()
    usuario_nome = serializers.SerializerMethodField()
    tipo_nome = serializers.CharField(source='get_tipo_display', read_only=True)
    compartimento_nome = serializers.CharField(source='get_compartimento_display', read_only=True)

    class Meta:
        model = Lubrificacao
        fields = ['id', 'uuid', 'atendimento', 'lubrificado_em', 'equipamento', 'equipamento_nome', 'tipo', 'tipo_nome', 'compartimento',
                  'compartimento_nome', 'produto', 'produto_nome', 'unidade', 'quantidade', 'horimetro', 'km', 'funcionario',
                  'funcionario_nome', 'foto', 'tem_foto', 'observacao', 'situacao', 'motivo_cancelamento', 'usuario_nome', 'criado_em']
        read_only_fields = ['atendimento', 'equipamento_nome', 'produto_nome', 'unidade', 'funcionario_nome', 'situacao',
                            'motivo_cancelamento', 'criado_em']

    def get_tem_foto(self, obj):
        return bool(obj.foto)

    def get_usuario_nome(self, obj):
        return (obj.usuario.get_full_name() or obj.usuario.username) if obj.usuario else ''

    def validate(self, attrs):
        if attrs['quantidade'] <= 0:
            raise serializers.ValidationError({'quantidade': 'Quantidade precisa ser maior que zero.'})
        if attrs['quantidade'] > 2000:
            raise serializers.ValidationError({'quantidade': 'Quantidade acima de 2.000: confira a unidade.'})
        h = attrs.get('horimetro')
        if h is not None and h < 0:
            raise serializers.ValidationError({'horimetro': 'Horímetro negativo.'})
        quando = attrs.get('lubrificado_em')
        if quando and quando > timezone.now() + timedelta(minutes=10):
            raise serializers.ValidationError({'lubrificado_em': 'Data no futuro.'})
        return attrs
