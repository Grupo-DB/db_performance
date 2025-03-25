from django.db import models
from django.contrib.auth.models import Group, Permission

from baseOrcamentaria.dre.models import Produto
from baseOrcamentaria.orcamento.models import CentroCustoPai

class CustoProducao(models.Model):
    id = models.AutoField(primary_key=True)
    produto = models.ForeignKey(Produto, null=True, blank=True, on_delete=models.RESTRICT, related_name='produtos+')
    centro_custo_pai = models.ForeignKey(CentroCustoPai, null=True, blank=True, on_delete=models.RESTRICT, related_name='centro_custo_pai+')
    fabrica = models.CharField(max_length=255, null=True, blank=True)
    periodo = models.CharField(max_length=2, null=True, blank=True)
    ano = models.CharField(max_length=6, blank=False, null=False)
    quantidade = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, default=0.00, verbose_name='Quantidade+')

    class Meta:
        verbose_name = 'Custo de Produção'
        verbose_name_plural = 'Custos de Produção'
