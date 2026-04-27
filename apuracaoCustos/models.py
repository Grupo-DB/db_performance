from django.db import models

# Create your models here.
class Local(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, unique=True, null=False, blank=False)
    periodo = models.CharField(max_length=455, null=False, blank=False)
    data = models.DateField(null=False, blank=False)
    ponto = models.DecimalField(null=False, blank=False)
    consumo = models.DecimalField(null=False, blank=False)
    producao = models.DecimalField(null=False, blank=False)
    produtividade = models.DecimalField(null=False, blank=False)
    custo = models.DecimalField(null=False, blank=False)
    class Meta:
        verbose_nome = 'Local'
        verbose_nome_plural = 'Locais'

class Fatura(models.Model):
    id = models.AutoField(primary_key=True)
    periodo = models.CharField(max_length=455, null=False, blank=False)
    fornecedor = models.CharField(max_length=455, null=False, blank=False)
    total_servico = models.DecimalField(null=False, blank=False)
    total_produto = models.DecimalField(null=False, blank=False)
    class Meta:
        verbose_name = 'Fatura'
        verbose_name_plural = 'Faturas'        

class Royalty(models.Model):
    id = models.AutoField(primary_key=True)
    periodo = models.CharField(max_length=455, null=False, blank=False)
    tn_britada = models.DecimalField(null=False, blank=False)
    dif_tn_britada = models.DecimalField(null=True, blank=True)
    tn_expedida = models.DecimalField(null=False, blank=False)
    dif_tn_expedida = models.DecimalField(null=True, blank=True)
    valor_unitario_tn = models.DecimalField(null=False, blank=False)
    valor_total = models.DecimalField(null=False, blank=False)
    referencia_entrada = models.DecimalField(null=True, blank=True)
    class Meta:
        verbose_nome = 'Royalty'
        verbose_nome_plural = 'Royalties'