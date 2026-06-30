from django.db import models


class Regiao(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=455, null=False, blank=False)

    class Meta:
        verbose_name = "Região"
        verbose_name_plural = "Regiões"


class Representante(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=455, null=False, blank=False)
    empresa = models.CharField(max_length=455, null=True, blank=True)
    vendededor_externo = models.CharField(max_length=455, null=True, blank=True)
    vendedor_interno = models.CharField(max_length=455, null=True, blank=True)
    regiao = models.ForeignKey(Regiao, on_delete=models.RESTRICT, related_name='regiao_representante', null=True, blank=True)
    segmento = models.CharField(max_length=455, null=True, blank=True)
    email = models.CharField(max_length=255, null=True, blank=True)
    telefone = models.CharField(max_length=255, null=True, blank=True)
    cpf = models.CharField(max_length=255, null=True, blank=True)
    cnpj = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Representante"
        verbose_name_plural = "Representantes"


class Meta(models.Model):
    id = models.AutoField(primary_key=True)
    regiao = models.ForeignKey(Regiao, on_delete=models.RESTRICT, related_name='regiao_meta', null=True, blank=True)
    representante = models.ForeignKey(Representante, on_delete=models.RESTRICT, related_name='representante_meta', null=True, blank=True)
    segmento = models.CharField(max_length=455, null=True, blank=True)
    grupo = models.CharField(max_length=50, null=True, blank=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    periodo = models.CharField(max_length=455, null=True, blank=True)
    data_meta = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Meta"
        verbose_name_plural = "Metas"


class Comissao(models.Model):
    id = models.AutoField(primary_key=True)
    representante = models.ForeignKey(Representante, on_delete=models.RESTRICT, related_name='representante_comissao', null=True, blank=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    periodo = models.CharField(max_length=455, null=True, blank=True)
    data_pagamento = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Comissão"
        verbose_name_plural = "Comissões"


class ParametroComissao(models.Model):
    chave = models.CharField(max_length=100, unique=True)
    descricao = models.CharField(max_length=455)
    taxa = models.DecimalField(max_digits=15, decimal_places=6)
    ativo = models.BooleanField(default=True)
    vigencia_inicio = models.DateField(null=True, blank=True)
    vigencia_fim = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Parâmetro de Comissão"
        verbose_name_plural = "Parâmetros de Comissão"
        ordering = ['chave']


class VinculoRepresentante(models.Model):
    SEGMENTO_CHOICES = [
        ('CC', 'Construção Civil'),
        ('ATM', 'Filial ATM'),
        ('AGRO', 'Agronegócio'),
    ]

    representante_externo = models.ForeignKey(
        Representante, on_delete=models.CASCADE,
        related_name='vinculos_como_externo'
    )
    representante_interno = models.ForeignKey(
        Representante, on_delete=models.CASCADE,
        related_name='vinculos_como_interno',
        null=True, blank=True
    )
    segmento = models.CharField(max_length=10, choices=SEGMENTO_CHOICES, default='CC')
    apenas_filial_atm = models.BooleanField(
        default=False,
        help_text='Se True, o vínculo ATM só considera vendas expedidas pela filial ATM'
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Vínculo de Representante"
        verbose_name_plural = "Vínculos de Representantes"
        unique_together = [('representante_externo', 'segmento')]
        ordering = ['segmento', 'representante_externo__nome']


class MapeamentoMunicipio(models.Model):
    cidade_estado = models.CharField(
        max_length=255,
        help_text='Formato: CIDADE-UF, ex: ALECRIM-RS (em maiúsculas, sem acentos)'
    )
    representante = models.ForeignKey(
        Representante, on_delete=models.RESTRICT,
        related_name='municipios_mapeados'
    )
    segmento = models.CharField(max_length=50, default='AGRONEGOCIO')

    class Meta:
        verbose_name = "Mapeamento de Município"
        verbose_name_plural = "Mapeamentos de Municípios"
        unique_together = [('cidade_estado', 'segmento')]
        ordering = ['cidade_estado']


# ─── Fase 3: Motor de Regras ───────────────────────────────────────────────────

class RegraComissao(models.Model):
    """Define como calcular a comissão de um representante."""

    BASE_CHOICES = [
        ('VALOR_PRODUTO', 'Valor do Produto'),
        ('VALOR_TOTAL', 'Valor Total (com ICMS/Frete)'),
    ]
    SEGMENTO_CHOICES = [
        ('CC', 'Construção Civil'),
        ('AGRO', 'Agronegócio'),
        ('AMBOS', 'Ambos'),
    ]
    TIPO_CHOICES = [
        ('PERCENTUAL_FIXO', 'Percentual fixo sobre base'),
        ('PERCENTUAL_POR_GRUPO', 'Percentual por grupo de produto'),
        ('ESCADA_META', 'Escada de meta (faixas de % atingido)'),
        ('FIXO', 'Valor fixo (R$)'),
        ('PERCENTUAL_DE_COMISSOES', 'Percentual sobre comissões de outros'),
    ]

    representante = models.ForeignKey(
        Representante, on_delete=models.CASCADE,
        related_name='regras_comissao'
    )
    descricao = models.CharField(max_length=455, help_text='Descrição legível da regra')
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    base_calculo = models.CharField(max_length=20, choices=BASE_CHOICES, default='VALOR_PRODUTO')
    segmento_produto = models.CharField(max_length=10, choices=SEGMENTO_CHOICES, default='CC')
    taxa = models.DecimalField(
        max_digits=10, decimal_places=6, default=0,
        help_text='Taxa principal (usada em PERCENTUAL_FIXO e PERCENTUAL_DE_COMISSOES)'
    )
    valor_fixo = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Valor fixo em R$ (usado em FIXO)'
    )
    multiplicador = models.DecimalField(
        max_digits=8, decimal_places=4, default=1,
        help_text='Multiplicador final aplicado ao resultado (ex: 1.05 para +5%)'
    )
    ordem = models.PositiveSmallIntegerField(default=0, help_text='Ordem de exibição/aplicação')
    ativo = models.BooleanField(default=True)

    # Filtros opcionais — restringe a quais linhas a regra se aplica
    filtro_filial_contem = models.CharField(
        max_length=100, blank=True,
        help_text='Se preenchido, aplica apenas a linhas onde EMPRESAFILIAL contém esse texto (ex: ATM)'
    )
    filtro_cliente_contem = models.CharField(
        max_length=100, blank=True,
        help_text='Se preenchido, aplica apenas a linhas onde CLIENTE_NOME contém esse texto (ex: QUERO QUERO)'
    )
    filtro_grupo_comercial_contem = models.CharField(
        max_length=100, blank=True,
        help_text='Se preenchido, aplica apenas a linhas onde GRUPO_COMERCIAL contém esse texto (ex: CARBOMAX)'
    )
    filtro_cidade_sufixo = models.CharField(
        max_length=10, blank=True,
        help_text='Se preenchido, aplica apenas a linhas onde CIDADE_FATURAMENTO termina com esse sufixo (ex: -SC, -RS)'
    )

    class Meta:
        verbose_name = "Regra de Comissão"
        verbose_name_plural = "Regras de Comissão"
        ordering = ['representante__nome', 'ordem']


class RegraComissaoGrupo(models.Model):
    """Taxas por grupo de produto dentro de uma RegraComissao do tipo PERCENTUAL_POR_GRUPO."""

    regra = models.ForeignKey(RegraComissao, on_delete=models.CASCADE, related_name='grupos')
    grupo = models.CharField(max_length=50, help_text='Ex: CB, PRIMOR, PRIMEX, FINALIZA')
    taxa = models.DecimalField(max_digits=10, decimal_places=6)
    taxa_potencializador = models.DecimalField(
        max_digits=10, decimal_places=6, default=0,
        help_text='Adicional aplicado quando a meta do grupo é atingida'
    )

    class Meta:
        verbose_name = "Grupo da Regra"
        verbose_name_plural = "Grupos da Regra"
        unique_together = [('regra', 'grupo')]
        ordering = ['grupo']


class RegraComissaoFaixa(models.Model):
    """Faixas de meta para regras do tipo ESCADA_META (ex: Adriano Born)."""

    regra = models.ForeignKey(RegraComissao, on_delete=models.CASCADE, related_name='faixas')
    pct_minimo = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='% mínimo de atingimento da meta para esta faixa entrar (ex: 50 = 50%)'
    )
    pct_maximo = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text='% máximo de atingimento (null = sem limite superior)'
    )
    taxa = models.DecimalField(max_digits=10, decimal_places=6, help_text='Taxa aplicada nessa faixa')

    class Meta:
        verbose_name = "Faixa da Regra"
        verbose_name_plural = "Faixas da Regra"
        ordering = ['pct_minimo']
