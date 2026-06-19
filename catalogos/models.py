from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from decimal import Decimal


def upload_image_fabricante(fabricante, filename):
    return f"fabricante_{fabricante.id}-{filename}"


def upload_image_produto(produto, filename):
    return f"produto_{produto.id}-{filename}"


def upload_catalogo_pdf(instance, filename):
    return f"catalogos/pdf/{instance.veiculo_id or 'geral'}/{filename}"


class Fabricante(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    image = models.FileField(upload_to=upload_image_fabricante, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Fabricante'
        verbose_name_plural = 'Fabricantes'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Equipamento(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False, unique=True)
    descricao = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Equipamento'
        verbose_name_plural = 'Equipamentos'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Veiculo(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    modelo = models.CharField(max_length=255, null=False, blank=False)
    fabricante = models.ForeignKey(Fabricante, on_delete=models.RESTRICT, related_name='veiculos')
    equipamento = models.ForeignKey(Equipamento, on_delete=models.RESTRICT, related_name='veiculos')
    descricao = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Veículo'
        verbose_name_plural = 'Veículos'
        ordering = ['nome']
        unique_together = [['fabricante', 'equipamento', 'modelo']]
        indexes = [
            models.Index(fields=['fabricante', 'equipamento']),
        ]

    def __str__(self):
        return f"{self.fabricante.nome} {self.nome} ({self.modelo})"


class Secao(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='secoes', null=True, blank=True)
    descricao = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Seção'
        verbose_name_plural = 'Seções'
        ordering = ['nome']
        indexes = [
            models.Index(fields=['veiculo', 'ativo']),
        ]

    def __str__(self):
        if self.veiculo:
            return f"{self.veiculo.nome} - {self.nome}"
        return self.nome


class Item(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=455, null=False, blank=False)
    apelido = models.CharField(max_length=255, blank=True, null=True)
    descricao = models.TextField(blank=True, null=True)
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='itens', null=True, blank=True)
    secao = models.ForeignKey(Secao, on_delete=models.RESTRICT, related_name='itens', null=True, blank=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    cod_catalogo = models.CharField(max_length=100, blank=True, null=True, unique=True)
    cod_minerion = models.CharField(max_length=100, blank=True, null=True, unique=True)
    referencia = models.CharField(max_length=255, blank=True, null=True)
    localizacao = models.CharField(max_length=255, blank=True, null=True)
    image = models.FileField(upload_to=upload_image_produto, blank=True, null=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Item'
        verbose_name_plural = 'Itens'
        ordering = ['nome']
        indexes = [
            models.Index(fields=['veiculo', 'ativo']),
            models.Index(fields=['secao', 'ativo']),
            models.Index(fields=['cod_catalogo']),
            models.Index(fields=['cod_minerion']),
        ]

    def __str__(self):
        return self.nome


class Pedido(models.Model):
    STATUS_CHOICES = [
        ('SOLICITADO', 'Solicitado'),
        ('ACEITO', 'Aceito'),
        ('REJEITADO', 'Rejeitado'),
        ('COTACAO', 'Em Cotação'),
        ('REALIZADO', 'Realizado'),
        ('EM_TRANSPORTE', 'Em Transporte'),
        ('FINALIZADO', 'Finalizado'),
    ]

    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pedidos')
    responsavel = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='pedidos_responsavel'
    )
    numero_referencia = models.CharField(max_length=50, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SOLICITADO')
    motivo_rejeicao = models.TextField(blank=True, null=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(Decimal('0.00'))])
    observacoes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Pedido'
        verbose_name_plural = 'Pedidos'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['usuario', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"Pedido {self.numero_referencia} - {self.usuario.username}"

    def calcular_total(self):
        total = sum(item.subtotal for item in self.itens_pedido.all())
        self.total = total
        self.save(update_fields=['total'])
        return total


class CatalogoPDF(models.Model):
    id = models.AutoField(primary_key=True)
    titulo = models.CharField(max_length=255)
    arquivo = models.FileField(upload_to=upload_catalogo_pdf)
    veiculo = models.ForeignKey(
        Veiculo, on_delete=models.SET_NULL, null=True, blank=True, related_name='catalogos_pdf'
    )
    descricao = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Catálogo PDF'
        verbose_name_plural = 'Catálogos PDF'
        ordering = ['-created_at']

    def __str__(self):
        return self.titulo


class ItemErpCatalogo(models.Model):
    """Mapeamento entre código do item no ERP (ESTQCOD) e código no catálogo PDF."""
    id = models.AutoField(primary_key=True)
    cod_erp = models.CharField(max_length=50, unique=True, db_index=True)
    nome_erp = models.CharField(max_length=455, blank=True, null=True)
    cod_catalogo = models.CharField(max_length=100, blank=True, null=True)
    catalogo = models.ForeignKey(
        CatalogoPDF, on_delete=models.SET_NULL, null=True, blank=True, related_name='itens_mapeados'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Mapeamento Item ERP → Catálogo'
        verbose_name_plural = 'Mapeamentos Item ERP → Catálogo'
        indexes = [
            models.Index(fields=['cod_erp']),
            models.Index(fields=['cod_catalogo']),
        ]

    def __str__(self):
        return f"ERP:{self.cod_erp} → Catálogo:{self.cod_catalogo or '-'}"


class ItemPedido(models.Model):
    id = models.AutoField(primary_key=True)
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='itens_pedido')
    # Item local (legado) — pode ser nulo quando o item vem do ERP
    item = models.ForeignKey(Item, on_delete=models.RESTRICT, null=True, blank=True)
    # Item do ERP — preenchido quando o produto vem da consulta ERP
    cod_erp = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    nome_produto = models.CharField(max_length=455, blank=True, null=True)
    quantidade = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Item do Pedido'
        verbose_name_plural = 'Itens do Pedido'
        indexes = [
            models.Index(fields=['pedido', 'item']),
            models.Index(fields=['pedido', 'cod_erp']),
        ]

    def __str__(self):
        nome = self.nome_produto or (self.item.nome if self.item else self.cod_erp or '?')
        return f"{nome} x{self.quantidade}"

    @property
    def subtotal(self):
        return self.quantidade * self.preco_unitario

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.pedido.calcular_total()


class PedidoNotificacao(models.Model):
    TIPO_CHOICES = [
        ('CRIACAO',          'Pedido Solicitado'),
        ('STATUS_RECEBIDO',  'Pedido Aceito'),
        ('STATUS_COTACAO',   'Pedido em Cotação'),
        ('STATUS_APROVADO',  'Pedido Aprovado'),
        ('STATUS_REJEITADO', 'Pedido Rejeitado'),
        ('STATUS_REALIZADO', 'Pedido Realizado/Transporte/Finalizado'),
        ('CANCELAMENTO',     'Pedido Cancelado'),
    ]

    id = models.AutoField(primary_key=True)
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='notificacoes')
    usuario_notificado = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notificacoes_pedidos')
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    mensagem = models.TextField()
    lido = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Notificação de Pedido'
        verbose_name_plural = 'Notificações de Pedido'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['usuario_notificado', '-created_at']),
            models.Index(fields=['usuario_notificado', 'lido']),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.pedido.numero_referencia}"
