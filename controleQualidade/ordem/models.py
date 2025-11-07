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

class OrdemExpressa(models.Model):
    id = models.AutoField(primary_key=True)
    numero = models.CharField(max_length=255, null=False, blank=False)
    data = models.DateField(null=False, blank=False)
    
    # Tabela intermediária para ensaios
    ensaios = models.ManyToManyField(
        Ensaio, 
        through='OrdemExpressaEnsaio',
        blank=True,
        related_name='expressa_ensaio'
    )
    
    # Tabela intermediária para cálculos
    calculos_ensaio = models.ManyToManyField(
        CalculoEnsaio,
        through='OrdemExpressaCalculo',
        blank=True,
        related_name='expressa_calculo'
    )
    
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    digitador = models.CharField(max_length=355, null=True, blank=True)
    classificacao = models.CharField(max_length=255, null=True, blank=True)
    
    class Meta:
        verbose_name = 'Ordem Expressa'
        verbose_name_plural = 'Ordens Expressas'


class OrdemExpressaEnsaio(models.Model):
    """Tabela intermediária para permitir duplicatas de ensaios"""
    ordem_expressa = models.ForeignKey(
        OrdemExpressa, 
        on_delete=models.CASCADE,
        related_name='ensaios_intermediarios'
    )
    ensaio = models.ForeignKey(Ensaio, on_delete=models.CASCADE)
    ordem = models.IntegerField(default=0)
    
    # RESTAURAR campos de laboratório
    laboratorio = models.CharField(max_length=10, null=True, blank=True)  # Lab atual que pode editar
    
    class Meta:
        ordering = ['ordem']
        verbose_name = 'Ensaio da Ordem Expressa'
        verbose_name_plural = 'Ensaios da Ordem Expressa'


class OrdemExpressaCalculo(models.Model):
    """Tabela intermediária para permitir duplicatas de cálculos"""
    ordem_expressa = models.ForeignKey(
        OrdemExpressa, 
        on_delete=models.CASCADE,
        related_name='calculos_intermediarios'
    )
    calculo = models.ForeignKey(CalculoEnsaio, on_delete=models.CASCADE)
    ordem = models.IntegerField(default=0)
    
    # RESTAURAR campos de laboratório
    laboratorio = models.CharField(max_length=10, null=True, blank=True)  # Lab atual que pode editar
    
    class Meta:
        ordering = ['ordem']
        verbose_name = 'Cálculo da Ordem Expressa'
        verbose_name_plural = 'Cálculos da Ordem Expressa'
   