from django.db import models
from controleQualidade.amostra.models import Amostra
from controleQualidade.ensaio.models import Ensaio

class Analise(models.Model):
    id = models.AutoField(primary_key=True)
    data = models.DateTimeField(auto_created=True, auto_now=True, null=False, blank=False)
    amostra = models.ForeignKey(Amostra, null=True, blank=True, on_delete=models.RESTRICT, related_name='analise')
    estado = models.CharField(max_length=255, null=False, blank=False)

    class Meta:
        verbose_name = 'Análise'
        verbose_name_plural = 'Análises'

        

class AnaliseEnsaio(models.Model):
    id = models.AutoField(primary_key=True)
    analise = models.ForeignKey(Analise, null=True, blank=True, on_delete=models.RESTRICT, related_name='ensaios')
    ensaios = models.ForeignKey(Ensaio, null=True, blank=True, on_delete=models.RESTRICT, related_name='analise_ensaios')
    ensaios_utilizados = models.JSONField(null=True, blank=True) 
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    digitador = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Análise de Ensaio'
        verbose_name_plural = 'Análises de Ensaio'

class AnaliseCalculo(models.Model):
    id = models.AutoField(primary_key=True)
    analise = models.ForeignKey(Analise, null=True, blank=True, on_delete=models.RESTRICT, related_name='calculos')
    calculos = models.CharField(max_length=255, null=False, blank=False)
    resultados = models.FloatField(null=True, blank=True)
    ensaios_utilizados = models.JSONField(null=True, blank=True)
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    digitador = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Análise de Cálculo'
        verbose_name_plural = 'Análises de Cálculo' 

