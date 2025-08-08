from django.db import models
from controleQualidade.ensaio.models import Ensaio

class CalculoEnsaio(models.Model):
    id = models.AutoField(primary_key=True)
    descricao = models.CharField(max_length=900, null=False, blank=False)
    funcao = models.CharField(max_length=500, null=False, blank=False)
    ensaios = models.ManyToManyField(Ensaio, related_name='calculos_ensaios')
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    unidade = models.CharField(max_length=255, null=True, blank=True)
    valor = models.FloatField(null=True, blank=True)
    class Meta:
        verbose_name = 'Cálculo de Ensaio'
        verbose_name_plural = 'Cálculos de Ensaio'