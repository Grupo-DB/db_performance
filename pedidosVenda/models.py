"""
Pedido de venda montado pelo vendedor externo e lançado no ERP pelo interno.

O ERP é só leitura para nós (usuário DBCONSULTA): o pedido nasce aqui, com os
dados já na forma que o interno digita lá — preço de tabela, % sobre a tabela no
mesmo sinal do `IPEDDIFTABPRECO`, prazo em texto como o `PEDPGTOPRAZOST` — e só
volta a cruzar com o ERP quando o interno informa o número do pedido lançado.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models

# Unidade de expedição = PRCFIL/PEDFIL do ERP. O preço e até o código do produto
# mudam por unidade (a ATM tem códigos próprios), então o catálogo do pedido
# depende dela.
FILIAL_CHOICES = [
    (0, 'Matriz'),
    (1, 'F07 - CD MPA'),
    (3, 'F08 - UP ATM'),
    (5, 'F09 - CD MFL'),
]

FRETE_CHOICES = [
    ('CIF', 'CIF — por nossa conta'),
    ('FOB', 'FOB — por conta do cliente'),
]

COBRANCA_CHOICES = [
    ('BOLETO', 'Boleto'),
    ('PIX', 'Pix'),
    ('DEPOSITO', 'Depósito'),
    ('CARTEIRA', 'Carteira'),
]


class VendedorPerfil(models.Model):
    """
    Liga o usuário do ManagerDB aos códigos de vendedor do ERP.

    Uma pessoa pode ter vários REPCOD — o ERP abre um código por região
    (Rodrigo Planalto 42 / Fronteira 38) —, por isso a lista e não uma FK.
    """

    TIPO_CHOICES = [
        ('EXTERNO', 'Vendedor externo'),
        ('INTERNO', 'Vendedor interno'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil_vendas')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='EXTERNO')
    repcods = models.JSONField(default=list, blank=True, help_text='Códigos REPRESENTANTE (REPCOD) do ERP')
    filial_padrao = models.IntegerField(choices=FILIAL_CHOICES, default=0)
    desconto_maximo = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0'),
        help_text='Desconto máximo (%) sobre a tabela sem precisar de aprovação do gestor',
    )
    interno = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='externos',
        limit_choices_to={'tipo': 'INTERNO'},
        help_text='Vendedor interno que recebe os pedidos deste externo',
    )
    telefone_whatsapp = models.CharField(max_length=30, blank=True, default='')
    avisar_whatsapp = models.BooleanField(default=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Perfil de vendedor'
        verbose_name_plural = 'Perfis de vendedor'
        ordering = ['tipo', 'user__first_name', 'user__username']

    def __str__(self):
        return f'{self.nome} ({self.get_tipo_display()})'

    @property
    def nome(self) -> str:
        return self.user.get_full_name() or self.user.username


class PedidoVenda(models.Model):
    STATUS_CHOICES = [
        ('RASCUNHO', 'Rascunho'),
        ('AGUARDANDO_APROVACAO', 'Aguardando aprovação'),
        ('ENVIADO', 'Enviado'),
        ('EM_LANCAMENTO', 'Em lançamento'),
        ('LANCADO', 'Lançado no ERP'),
        ('DEVOLVIDO', 'Devolvido'),
        ('CANCELADO', 'Cancelado'),
    ]
    # Só nesses o vendedor ainda mexe no conteúdo.
    STATUS_EDITAVEIS = ('RASCUNHO', 'DEVOLVIDO')

    vendedor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='pedidos_venda')
    interno = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_venda_recebidos',
    )
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='RASCUNHO', db_index=True)

    repcod = models.IntegerField(null=True, blank=True, help_text='PEDREP — código do vendedor no ERP')
    filial = models.IntegerField(choices=FILIAL_CHOICES, default=0)

    # Cliente do ERP (CLICOD) ou pré-cadastro em `cliente_novo` — nunca os dois vazios
    # num pedido enviado. Nome/documento/cidade ficam copiados para a lista não
    # depender do ERP no ar.
    cliente_cod = models.IntegerField(null=True, blank=True)
    cliente_nome = models.CharField(max_length=120, blank=True, default='')
    cliente_fantasia = models.CharField(max_length=120, blank=True, default='')
    cliente_documento = models.CharField(max_length=20, blank=True, default='')
    cliente_cidade = models.CharField(max_length=80, blank=True, default='')
    cliente_novo = models.JSONField(null=True, blank=True)

    endereco_entrega_cod = models.IntegerField(null=True, blank=True, help_text='ECLICOD do ERP')
    endereco_entrega = models.CharField(max_length=255, blank=True, default='')

    prazo_pagamento = models.CharField(max_length=60, blank=True, default='', help_text='Ex.: 30/60/90 (PEDPGTOPRAZOST)')
    forma_cobranca = models.CharField(max_length=15, choices=COBRANCA_CHOICES, blank=True, default='BOLETO')
    frete = models.CharField(max_length=3, choices=FRETE_CHOICES, default='CIF')
    data_entrega = models.DateField(null=True, blank=True)
    observacoes = models.TextField(blank=True, default='')

    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    # Maior desconto (%) entre os itens, positivo = abaixo da tabela.
    maior_desconto = models.DecimalField(max_digits=8, decimal_places=3, default=Decimal('0'))
    justificativa_desconto = models.TextField(blank=True, default='')

    numero_erp = models.IntegerField(null=True, blank=True, help_text='PEDNUM do pedido lançado')
    motivo_devolucao = models.TextField(blank=True, default='')
    aprovado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_venda_aprovados',
    )
    aprovado_em = models.DateTimeField(null=True, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    lancado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Pedido de venda'
        verbose_name_plural = 'Pedidos de venda'
        ordering = ['-criado_em']

    def __str__(self):
        return f'{self.numero} — {self.cliente_nome or "sem cliente"}'

    @property
    def numero(self) -> str:
        return f'PV-{self.pk:05d}' if self.pk else 'PV-novo'

    def recalcular_totais(self):
        itens = list(self.itens.all())
        self.total = sum((i.total for i in itens), Decimal('0'))
        descontos = [i.desconto_perc for i in itens if i.desconto_perc is not None]
        self.maior_desconto = max(descontos, default=Decimal('0'))


class ItemPedidoVenda(models.Model):
    pedido = models.ForeignKey(PedidoVenda, on_delete=models.CASCADE, related_name='itens')
    ordem = models.PositiveIntegerField(default=0)
    produto_cod = models.IntegerField(help_text='ESTQCOD do ERP')
    descricao = models.CharField(max_length=150)
    unidade = models.CharField(max_length=10, blank=True, default='')
    quantidade = models.DecimalField(max_digits=14, decimal_places=3)
    preco_tabela = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    preco_unitario = models.DecimalField(max_digits=14, decimal_places=4)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    observacao = models.CharField(max_length=80, blank=True, default='')

    class Meta:
        ordering = ['ordem', 'id']

    @property
    def dif_tabela_perc(self):
        """% sobre a tabela no sinal do ERP (IPEDDIFTABPRECO): 90 sobre 95 → −5,26316."""
        if not self.preco_tabela:
            return None
        return (self.preco_unitario / self.preco_tabela - 1) * 100

    @property
    def desconto_perc(self):
        dif = self.dif_tabela_perc
        return None if dif is None else -dif

    def save(self, *args, **kwargs):
        self.total = (self.quantidade * self.preco_unitario).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


class PedidoVendaEvento(models.Model):
    """Linha do tempo do pedido (quem fez o quê, e por quê)."""

    TIPO_CHOICES = [
        ('CRIADO', 'Criado'),
        ('ENVIADO', 'Enviado ao interno'),
        ('APROVACAO_SOLICITADA', 'Aprovação de desconto solicitada'),
        ('APROVADO', 'Desconto aprovado'),
        ('REPROVADO', 'Desconto reprovado'),
        ('ASSUMIDO', 'Lançamento iniciado'),
        ('LANCADO', 'Lançado no ERP'),
        ('DEVOLVIDO', 'Devolvido ao vendedor'),
        ('CANCELADO', 'Cancelado'),
        ('COMENTARIO', 'Comentário'),
    ]

    pedido = models.ForeignKey(PedidoVenda, on_delete=models.CASCADE, related_name='eventos')
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    texto = models.TextField(blank=True, default='')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['criado_em', 'id']


class PedidoVendaNotificacao(models.Model):
    """Aviso do sino do ManagerDB."""

    TIPO_CHOICES = [
        ('NOVO_PEDIDO', 'Novo pedido para lançar'),
        ('APROVACAO_SOLICITADA', 'Desconto aguardando aprovação'),
        ('APROVADO', 'Desconto aprovado'),
        ('REPROVADO', 'Desconto reprovado'),
        ('LANCADO', 'Pedido lançado no ERP'),
        ('DEVOLVIDO', 'Pedido devolvido'),
        ('CANCELADO', 'Pedido cancelado'),
    ]

    pedido = models.ForeignKey(PedidoVenda, on_delete=models.CASCADE, related_name='notificacoes')
    usuario_notificado = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notificacoes_pedido_venda')
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    mensagem = models.TextField()
    lido = models.BooleanField(default=False, db_index=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']
