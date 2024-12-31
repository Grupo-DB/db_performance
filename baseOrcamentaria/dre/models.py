from django.db import models
from django.contrib.auth.models import Group, Permission
from django.dispatch import receiver
from django.db.models.signals import pre_save




class Produto(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    aliquota = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, default=0.00, verbose_name='Aliquota')
    class Meta:
        verbose_name = 'Produto'
        verbose_name_plural = 'Produtos'

class Linha(models.Model):
    id = models.AutoField(primary_key=True)
    produto = models.ForeignKey(Produto, null=True, blank=True, on_delete=models.RESTRICT, related_name='produtos')
    preco_medio_venda = models.DecimalField(max_digits=10, decimal_places=2, null=False, blank=False, default=0.00, verbose_name='Preço Médio Venda')
    custo_medio_variavel = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0.00, verbose_name='Custo Médio Variável')
    periodo = models.CharField(max_length=2, null=True, blank=True)
    ano = models.CharField(max_length=6, blank=False, null=False)
    quantidade_carregada =models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, default=0.00, verbose_name='Toneladas Carregadas')
    class Meta:
        verbose_name = ' DRE Linha de Produtos'
        verbose_name_plural = ' DRE Linhas de Produtos'


