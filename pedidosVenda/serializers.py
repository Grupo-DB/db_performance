from decimal import Decimal

from django.contrib.auth.models import Group
from django.db import transaction
from rest_framework import serializers

from . import fluxo, fotos
from .models import (
    FILIAL_CHOICES,
    FotoProduto,
    ItemPedidoVenda,
    PedidoVenda,
    PedidoVendaEvento,
    PedidoVendaNotificacao,
    VendedorPerfil,
)

FILIAIS = dict(FILIAL_CHOICES)
# Grupo que libera o módulo no menu (app.menu.ts / mobile-shell.ts).
GRUPO_POR_TIPO = {'EXTERNO': 'vendasPedidos', 'INTERNO': 'vendasInterno'}


def _nome(user):
    return (user.get_full_name() or user.username) if user else None


class VendedorPerfilSerializer(serializers.ModelSerializer):
    nome = serializers.SerializerMethodField()
    username = serializers.CharField(source='user.username', read_only=True)
    filial_nome = serializers.SerializerMethodField()
    interno_nome = serializers.SerializerMethodField()

    class Meta:
        model = VendedorPerfil
        fields = [
            'id', 'user', 'nome', 'username', 'tipo', 'repcods', 'filial_padrao', 'filial_nome',
            'desconto_maximo', 'interno', 'interno_nome', 'telefone_whatsapp', 'avisar_whatsapp',
            'ativo', 'criado_em', 'atualizado_em',
        ]
        read_only_fields = ['criado_em', 'atualizado_em']

    def get_nome(self, obj):
        return obj.nome

    def get_filial_nome(self, obj):
        return FILIAIS.get(obj.filial_padrao)

    def get_interno_nome(self, obj):
        return obj.interno.nome if obj.interno else None

    def validate_repcods(self, valor):
        try:
            return sorted({int(v) for v in (valor or [])})
        except (TypeError, ValueError):
            raise serializers.ValidationError('Códigos de vendedor do Minerion/SGA precisam ser números.')

    def validate_desconto_maximo(self, valor):
        if valor < 0 or valor > 100:
            raise serializers.ValidationError('Use um percentual entre 0 e 100.')
        return valor

    def validate(self, attrs):
        tipo = attrs.get('tipo', getattr(self.instance, 'tipo', 'EXTERNO'))
        interno = attrs.get('interno', getattr(self.instance, 'interno', None))
        if interno and interno.tipo != 'INTERNO':
            raise serializers.ValidationError({'interno': 'Escolha um vendedor interno.'})
        if tipo == 'INTERNO':
            attrs['interno'] = None
        return attrs

    def save(self, **kwargs):
        perfil = super().save(**kwargs)
        # O menu do front decide pelo grupo; mantê-lo em dia aqui evita o gestor
        # ter de ir ao admin depois de cadastrar o perfil.
        for tipo, nome_grupo in GRUPO_POR_TIPO.items():
            grupo, _ = Group.objects.get_or_create(name=nome_grupo)
            if perfil.ativo and perfil.tipo == tipo:
                perfil.user.groups.add(grupo)
            else:
                perfil.user.groups.remove(grupo)
        return perfil


class ItemPedidoVendaSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    desconto_perc = serializers.SerializerMethodField()
    dif_tabela_perc = serializers.SerializerMethodField()

    class Meta:
        model = ItemPedidoVenda
        fields = [
            'id', 'ordem', 'produto_cod', 'descricao', 'unidade', 'quantidade', 'preco_tabela',
            'preco_unitario', 'total', 'desconto_perc', 'dif_tabela_perc', 'observacao',
        ]
        read_only_fields = ['total']

    def _arred(self, valor, casas):
        return None if valor is None else round(float(valor), casas)

    def get_desconto_perc(self, obj):
        return self._arred(obj.desconto_perc, 3)

    def get_dif_tabela_perc(self, obj):
        return self._arred(obj.dif_tabela_perc, 5)

    def validate(self, attrs):
        if attrs.get('quantidade') is not None and attrs['quantidade'] <= 0:
            raise serializers.ValidationError({'quantidade': 'Quantidade precisa ser maior que zero.'})
        if attrs.get('preco_unitario') is not None and attrs['preco_unitario'] <= 0:
            raise serializers.ValidationError({'preco_unitario': 'Preço precisa ser maior que zero.'})
        return attrs


class PedidoVendaEventoSerializer(serializers.ModelSerializer):
    usuario_nome = serializers.SerializerMethodField()
    tipo_label = serializers.CharField(source='get_tipo_display', read_only=True)

    class Meta:
        model = PedidoVendaEvento
        fields = ['id', 'tipo', 'tipo_label', 'texto', 'usuario', 'usuario_nome', 'criado_em']

    def get_usuario_nome(self, obj):
        return _nome(obj.usuario)


class PedidoVendaListSerializer(serializers.ModelSerializer):
    numero = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    filial_nome = serializers.SerializerMethodField()
    vendedor_nome = serializers.SerializerMethodField()
    interno_nome = serializers.SerializerMethodField()
    qtd_itens = serializers.IntegerField(read_only=True)
    cliente_pre_cadastro = serializers.SerializerMethodField()

    class Meta:
        model = PedidoVenda
        fields = [
            'id', 'numero', 'status', 'status_label', 'cliente_cod', 'cliente_nome', 'cliente_fantasia',
            'cliente_cidade', 'cliente_pre_cadastro', 'filial', 'filial_nome', 'total', 'maior_desconto',
            'qtd_itens', 'vendedor', 'vendedor_nome', 'interno', 'interno_nome', 'numero_erp',
            'motivo_devolucao', 'criado_em', 'atualizado_em', 'enviado_em', 'lancado_em',
        ]

    def get_filial_nome(self, obj):
        return FILIAIS.get(obj.filial)

    def get_vendedor_nome(self, obj):
        return _nome(obj.vendedor)

    def get_interno_nome(self, obj):
        return _nome(obj.interno)

    def get_cliente_pre_cadastro(self, obj):
        return bool(obj.cliente_novo) and not obj.cliente_cod


class PedidoVendaSerializer(PedidoVendaListSerializer):
    itens = ItemPedidoVendaSerializer(many=True, required=False)
    eventos = PedidoVendaEventoSerializer(many=True, read_only=True)
    aprovado_por_nome = serializers.SerializerMethodField()
    acoes = serializers.SerializerMethodField()
    teto_desconto = serializers.SerializerMethodField()

    class Meta(PedidoVendaListSerializer.Meta):
        fields = PedidoVendaListSerializer.Meta.fields + [
            'repcod', 'cliente_documento', 'cliente_novo', 'endereco_entrega_cod', 'endereco_entrega',
            'prazo_pagamento', 'forma_cobranca', 'frete', 'data_entrega', 'paletizado', 'frete_valor_ton', 'observacoes',
            'justificativa_desconto', 'aprovado_por', 'aprovado_por_nome', 'aprovado_em',
            'itens', 'eventos', 'acoes', 'teto_desconto',
        ]
        read_only_fields = [
            'vendedor', 'interno', 'status', 'total', 'maior_desconto', 'numero_erp', 'motivo_devolucao',
            'aprovado_por', 'aprovado_em', 'enviado_em', 'lancado_em',
        ]

    def get_aprovado_por_nome(self, obj):
        return _nome(obj.aprovado_por)

    def _perfil_vendedor(self, obj):
        cache = self.context.setdefault('_perfis', {})
        if obj.vendedor_id not in cache:
            cache[obj.vendedor_id] = VendedorPerfil.objects.filter(user_id=obj.vendedor_id).first()
        return cache[obj.vendedor_id]

    def get_teto_desconto(self, obj):
        perfil = self._perfil_vendedor(obj)
        return float(perfil.desconto_maximo) if perfil else 0.0

    def get_acoes(self, obj):
        """O que o usuário da requisição pode fazer agora — o front só mostra o botão."""
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return {}
        dono = obj.vendedor_id == user.pk
        gestor = fluxo.eh_gestor(user)
        perfil = fluxo.perfil_de(user)
        lancador = gestor or bool(perfil and perfil.tipo == 'INTERNO')
        na_fila = obj.status in ('ENVIADO', 'EM_LANCAMENTO')
        ocupado = obj.status == 'EM_LANCAMENTO' and obj.interno_id not in (None, user.pk)
        return {
            'editar': dono and obj.status in PedidoVenda.STATUS_EDITAVEIS,
            'enviar': dono and obj.status in PedidoVenda.STATUS_EDITAVEIS,
            'excluir': dono and obj.status == 'RASCUNHO',
            'cancelar': (dono or gestor) and obj.status not in ('LANCADO', 'CANCELADO'),
            'aprovar': gestor and obj.status == 'AGUARDANDO_APROVACAO',
            'assumir': lancador and obj.status == 'ENVIADO',
            'lancar': lancador and na_fila and not ocupado,
            'devolver': lancador and na_fila and not ocupado,
            'duplicar': dono or gestor,
        }

    def validate(self, attrs):
        if self.instance and self.instance.status not in PedidoVenda.STATUS_EDITAVEIS:
            raise serializers.ValidationError('Pedido enviado não pode mais ser alterado. Peça a devolução ao interno.')
        if 'filial' in attrs and attrs['filial'] not in FILIAIS:
            raise serializers.ValidationError({'filial': 'Unidade inválida.'})
        return attrs

    def _gravar_itens(self, pedido, itens):
        pedido.itens.all().delete()
        for ordem, dados in enumerate(itens):
            dados.pop('id', None)
            dados['ordem'] = ordem
            ItemPedidoVenda.objects.create(pedido=pedido, **dados)
        pedido.recalcular_totais()
        pedido.save(update_fields=['total', 'maior_desconto', 'atualizado_em'])

    @transaction.atomic
    def create(self, validated_data):
        itens = validated_data.pop('itens', [])
        pedido = PedidoVenda.objects.create(**validated_data)
        PedidoVendaEvento.objects.create(pedido=pedido, usuario=pedido.vendedor, tipo='CRIADO')
        self._gravar_itens(pedido, itens)
        return pedido

    @transaction.atomic
    def update(self, instance, validated_data):
        itens = validated_data.pop('itens', None)
        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)
        instance.save()
        if itens is not None:
            self._gravar_itens(instance, itens)
        return instance


class PedidoVendaNotificacaoSerializer(serializers.ModelSerializer):
    pedido_numero = serializers.CharField(source='pedido.numero', read_only=True)
    cliente_nome = serializers.CharField(source='pedido.cliente_nome', read_only=True)
    pedido_status = serializers.CharField(source='pedido.status', read_only=True)

    class Meta:
        model = PedidoVendaNotificacao
        fields = ['id', 'pedido', 'pedido_numero', 'cliente_nome', 'pedido_status', 'tipo', 'mensagem', 'lido', 'criado_em']


class FotoProdutoSerializer(serializers.ModelSerializer):
    imagem_url = serializers.SerializerMethodField()
    miniatura_url = serializers.SerializerMethodField()
    enviado_por_nome = serializers.SerializerMethodField()
    arquivo = serializers.FileField(write_only=True, required=False)

    class Meta:
        model = FotoProduto
        fields = [
            'id', 'codigos', 'descricao', 'arquivo', 'imagem_url', 'miniatura_url',
            'enviado_por', 'enviado_por_nome', 'atualizado_em',
        ]
        read_only_fields = ['enviado_por', 'atualizado_em']

    def get_imagem_url(self, obj):
        return obj.caminho()

    def get_miniatura_url(self, obj):
        return obj.caminho(miniatura=True)

    def get_enviado_por_nome(self, obj):
        return _nome(obj.enviado_por)

    def to_internal_value(self, data):
        # Multipart manda tudo como texto: "codigos" chega "[2743, 11598]" ou "2743,11598".
        if hasattr(data, 'getlist'):
            data = {k: data.get(k) for k in data.keys()}
        codigos = data.get('codigos')
        if isinstance(codigos, str):
            data = {**data, 'codigos': [c.strip() for c in codigos.strip().strip('[]').split(',') if c.strip()]}
        return super().to_internal_value(data)

    def validate_codigos(self, valor):
        try:
            codigos = sorted({int(c) for c in (valor or [])})
        except (TypeError, ValueError):
            raise serializers.ValidationError('Códigos de produto precisam ser números.')
        if not codigos:
            raise serializers.ValidationError('Escolha ao menos um produto para a foto.')
        outras = FotoProduto.objects.exclude(pk=getattr(self.instance, 'pk', None))
        em_uso = {c for f in outras for c in f.codigos} & set(codigos)
        if em_uso:
            raise serializers.ValidationError(
                f'Já têm foto: {", ".join(str(c) for c in sorted(em_uso))}. Troque a foto deles em vez de criar outra.'
            )
        return codigos

    def validate(self, attrs):
        if not self.instance and not attrs.get('arquivo'):
            raise serializers.ValidationError({'arquivo': 'Envie a foto.'})
        return attrs

    def _aplicar_arquivo(self, attrs):
        arquivo = attrs.pop('arquivo', None)
        if arquivo is None:
            return None
        try:
            imagem, miniatura = fotos.processar(arquivo)
        except fotos.FotoInvalida as exc:
            raise serializers.ValidationError({'arquivo': str(exc)})
        return imagem, miniatura

    def create(self, validated_data):
        imagem, miniatura = self._aplicar_arquivo(validated_data)
        return FotoProduto.objects.create(imagem=imagem, miniatura=miniatura, **validated_data)

    def update(self, instance, validated_data):
        novos = self._aplicar_arquivo(validated_data)
        if novos:
            antigos = (instance.imagem, instance.miniatura)
            instance.imagem, instance.miniatura = novos
            for arq in antigos:
                arq.delete(save=False)
        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)
        instance.save()
        return instance
