from django.db import models
from controleQualidade.plano.models import PlanoAnalise
class Ordem(models.Model):
    id = models.AutoField(primary_key=True)
    numero = models.CharField(max_length=255, null=False, blank=False)
    data = models.DateField(null=False, blank=False)
    plano_analise = models.ForeignKey(PlanoAnalise, null=True, blank=True, on_delete=models.RESTRICT, related_name='ordem')
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    digitador = models.CharField(max_length=355, null=True, blank=True)
    modificacoes = models.TextField(null=True, blank=True)
    class Meta:
        verbose_name = 'Ordem'
        verbose_name_plural = 'Ordens'

    class Meta:
        verbose_name = 'Ordem'
        verbose_name_plural = 'Ordens'
