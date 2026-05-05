from django.db import models

# Create your models here.
class Local(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    periodo = models.CharField(max_length=455, null=False, blank=False)
    data = models.DateField(null=False, blank=False)
    ponto = models.FloatField(null=True, blank=True)
    consumo = models.FloatField(null=True, blank=True)
    producao = models.FloatField(null=False, blank=False)
    produtividade = models.FloatField(null=False, blank=False)
    #custo = models.FloatField(null=True, blank=True)
    class Meta:
        verbose_name = 'Local'
        verbose_name_plural = 'Locais'

class Fatura(models.Model):
    id = models.AutoField(primary_key=True)
    periodo = models.CharField(max_length=455, null=False, blank=False)
    #fornecedor = models.CharField(max_length=455, null=False, blank=False)
    total_servico = models.FloatField(null=True, blank=True)
    total_produto = models.FloatField(null=True, blank=True)
    total_geral = models.FloatField(null=True, blank=True)
    class Meta:
        verbose_name = 'Fatura'
        verbose_name_plural = 'Faturas'

class Royalty(models.Model):
    id = models.AutoField(primary_key=True)
    periodo = models.CharField(max_length=455, null=False, blank=False)
    tn_britada = models.FloatField(null=True, blank=True)
    dif_tn_britada = models.FloatField(null=True, blank=True)
    tn_expedida = models.FloatField(null=True, blank=True)
    dif_tn_expedida = models.FloatField(null=True, blank=True)
    valor_unitario_tn = models.FloatField(null=True, blank=True)
    valor_total = models.FloatField(null=True, blank=True)
    referencia_entrada = models.FloatField(null=True, blank=True)
    class Meta:
        verbose_name = 'Royalty'
        verbose_name_plural = 'Royalties'
