from django.db import models
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.calculosEnsaio.models import CalculoEnsaio
class PlanoAnalise(models.Model):
    id = models.AutoField(primary_key=True)
    descricao = models.CharField(max_length=900, null=False, blank=False)
    ensaios = models.ManyToManyField(Ensaio, blank=True, null=True, related_name='plano_ensaio')
    calculos_ensaio = models.ManyToManyField(CalculoEnsaio, blank=True,  null=True, related_name='plano_ensaio')
   
    class Meta:
        verbose_name = 'Plano de Analise'
        verbose_name_plural = 'Planos de Ensaio'
