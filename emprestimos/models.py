from decimal import Decimal, ROUND_DOWN

from dateutil.relativedelta import relativedelta
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Credor(models.Model):
    """Pessoa física que empresta dinheiro (aplicador/investidor)."""

    nome = models.CharField(max_length=255)
    cpf = models.CharField(max_length=18, unique=True)
    rg = models.CharField(max_length=20, blank=True)
    endereco = models.CharField(max_length=255, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=2, blank=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Credor'
        verbose_name_plural = 'Credores'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Empresa(models.Model):
    """Empresa do grupo que toma o empréstimo (mutuária)."""

    nome = models.CharField(max_length=255, unique=True)
    local = models.CharField(max_length=150, blank=True, help_text='Cidade / Estado')
    cnpj = models.CharField(max_length=20, blank=True)
    endereco = models.CharField(max_length=255, blank=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Banco(models.Model):
    codigo = models.CharField(max_length=10, unique=True)
    nome = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = 'Banco'
        verbose_name_plural = 'Bancos'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Aplicacao(models.Model):
    """Um empréstimo/aplicação de um credor para uma empresa do grupo."""

    STATUS_ATIVA = 'ativa'
    STATUS_RENOVADA = 'renovada'
    STATUS_RESGATE_PARCIAL = 'resgatada_parcial'
    STATUS_RESGATE_TOTAL = 'resgatada_total'
    STATUS_CHOICES = [
        (STATUS_ATIVA, 'Ativa'),
        (STATUS_RENOVADA, 'Renovada'),
        (STATUS_RESGATE_PARCIAL, 'Resgatada Parcialmente'),
        (STATUS_RESGATE_TOTAL, 'Resgatada Totalmente'),
    ]

    credor = models.ForeignKey(Credor, on_delete=models.PROTECT, related_name='aplicacoes')
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name='aplicacoes')
    banco = models.ForeignKey(Banco, on_delete=models.SET_NULL, null=True, blank=True, related_name='aplicacoes')

    data_aplicacao = models.DateField()
    data_renovacao = models.DateField(help_text='Data de referência usada para calcular o próximo vencimento do contrato')
    valor_aplicacao = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    taxa = models.DecimalField(max_digits=6, decimal_places=4, help_text='Ex.: 0.0150 para 1,50% ao mês')
    dia_vencimento = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(31)])

    agencia = models.CharField(max_length=30, blank=True)
    conta = models.CharField(max_length=30, blank=True)
    titular_conta = models.CharField(max_length=255, blank=True, help_text='Preencher apenas se diferente do credor')

    numero_contrato = models.CharField(max_length=20, unique=True, blank=True)
    ano_referencia = models.PositiveSmallIntegerField(blank=True, null=True)

    observacoes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ATIVA)

    juros = models.DecimalField(max_digits=12, decimal_places=2, editable=False, default=0)
    parcela_ajustada = models.DecimalField(max_digits=12, decimal_places=2, editable=False, default=0)
    liquido = models.DecimalField(max_digits=12, decimal_places=2, editable=False, default=0)
    irrf = models.DecimalField(max_digits=12, decimal_places=2, editable=False, default=0)
    descendio = models.PositiveSmallIntegerField(editable=False, default=1, help_text='Década de vencimento: 1 (1-10), 2 (11-20) ou 3 (21-31)')
    vencimento_contrato = models.DateField(editable=False, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Aplicação'
        verbose_name_plural = 'Aplicações'
        ordering = ['-data_aplicacao']

    def __str__(self):
        return f'{self.numero_contrato} - {self.credor.nome}'

    def _calcular_campos_derivados(self):
        aliquota_liquida = Decimal('0.775')
        aliquota_irrf = Decimal('0.225')

        self.juros = (self.valor_aplicacao * self.taxa).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        self.parcela_ajustada = (self.juros / aliquota_liquida).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        self.liquido = (self.parcela_ajustada * aliquota_liquida).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        self.irrf = (self.parcela_ajustada * aliquota_irrf).quantize(Decimal('0.01'), rounding=ROUND_DOWN)

        if self.dia_vencimento <= 10:
            self.descendio = 1
        elif self.dia_vencimento <= 20:
            self.descendio = 2
        else:
            self.descendio = 3

        if self.data_renovacao:
            self.vencimento_contrato = self.data_renovacao + relativedelta(years=1)

    def _gerar_numero_contrato(self):
        if self.numero_contrato:
            return
        ano = self.ano_referencia or self.data_aplicacao.year
        ultimo = (
            Aplicacao.objects.filter(ano_referencia=ano)
            .exclude(pk=self.pk)
            .order_by('-numero_contrato')
            .values_list('numero_contrato', flat=True)
            .first()
        )
        sequencial = int(ultimo[-5:]) + 1 if ultimo else 1
        self.numero_contrato = f'{ano}{sequencial:05d}'

    def save(self, *args, **kwargs):
        if not self.ano_referencia:
            self.ano_referencia = self.data_aplicacao.year
        self._gerar_numero_contrato()
        self._calcular_campos_derivados()
        super().save(*args, **kwargs)


class Resgate(models.Model):
    TIPO_PARCIAL = 'parcial'
    TIPO_TOTAL = 'total'
    TIPO_CHOICES = [
        (TIPO_PARCIAL, 'Parcial'),
        (TIPO_TOTAL, 'Total'),
    ]

    aplicacao = models.ForeignKey(Aplicacao, on_delete=models.PROTECT, related_name='resgates')
    data_resgate = models.DateField()
    valor_resgatado = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    juros_periodo = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='Juros pagos junto com este resgate')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Resgate'
        verbose_name_plural = 'Resgates'
        ordering = ['-data_resgate']

    def __str__(self):
        return f'Resgate {self.tipo} - {self.aplicacao.numero_contrato}'
