from django.db import models

# Create your models here.
class Regiao(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=455, null=False, blank=False)
    class Meta:
        verbose_name = "Região"
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