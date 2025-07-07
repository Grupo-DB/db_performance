from django.db import models
from controleQualidade.calculosEnsaio.models import CalculoEnsaio
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.plano.models import PlanoAnalise
from simple_history.models import HistoricalRecords
class Ordem(models.Model):
    id = models.AutoField(primary_key=True)
    numero = models.CharField(max_length=255, null=False, blank=False)
    data = models.DateField(null=False, blank=False)
    plano_analise = models.ManyToManyField(PlanoAnalise, blank=True, related_name='ordens')
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    digitador = models.CharField(max_length=355, null=True, blank=True)
    classificacao = models.CharField(max_length=255, null=True, blank=True)  # Exemplo: Controle de Qualidade, SAC, Desenvolvimento de Produtos
    
    history = HistoricalRecords()
    class Meta:
        verbose_name = 'Ordem'
        verbose_name_plural = 'Ordens'

    class Meta:
        verbose_name = 'Ordem'
        verbose_name_plural = 'Ordens'

class OrdemExpressa(models.Model):
    id = models.AutoField(primary_key=True)
    numero = models.CharField(max_length=255, null=False, blank=False)
    data = models.DateField(null=False, blank=False)
    ensaio = models.ForeignKey(Ensaio, null=True, blank=True, on_delete=models.RESTRICT, related_name='ordem_expressa')
    calculo = models.ForeignKey(CalculoEnsaio, null=True, blank=True, on_delete=models.RESTRICT, related_name='ordem_expressa')
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    digitador = models.CharField(max_length=355, null=True, blank=True)
    classificacao = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Ordem Expressa'
        verbose_name_plural = 'Ordens Expressas'