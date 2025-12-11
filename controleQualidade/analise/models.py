from django.db import models
from controleQualidade.amostra.models import Amostra
from controleQualidade.ensaio.models import Ensaio

class Analise(models.Model):
    id = models.AutoField(primary_key=True)
    data = models.DateTimeField(auto_created=True, auto_now=True, null=False, blank=False)
    amostra = models.ForeignKey(Amostra, null=True, blank=True, on_delete=models.RESTRICT, related_name='analise')
    estado = models.CharField(max_length=255, null=False, blank=False)
    finalizada = models.BooleanField(default=False, blank=True)
    finalizada_at = models.DateField(null=True, blank=True)  
    laudo = models.BooleanField(default=False, blank=True)  
    aprovada = models.BooleanField(default=False, blank=True)  
    aprovada_at = models.DateField(null=True)
    metodo_modelagem = models.CharField(max_length=255, null=True, blank=True)
    metodo_muro = models.CharField(max_length=255, null=True, blank=True)
    observacoes_muro = models.TextField(null=True, blank=True)
    material_organico = models.TextField(null=True, blank=True)
    parecer = models.JSONField(null=True, blank=True)
    substrato = models.JSONField(null=True, blank=True)
    superficial = models.JSONField(null=True, blank=True)
    retracao = models.JSONField(null=True, blank=True)
    elasticidade = models.JSONField(null=True, blank=True)
    flexao = models.JSONField(null=True, blank=True)
    compressao = models.JSONField(null=True, blank=True)
    peneiras = models.JSONField(null=True, blank=True)
    peneiras_umidas = models.JSONField(null=True, blank=True)
    laboratorio_atual = models.CharField(max_length=255, null=True, blank=True)
    variacao_dimensional = models.JSONField(null=True, blank=True)
    variacao_massa = models.JSONField(null=True, blank=True)
    tracao_normal = models.JSONField(null=True, blank=True)
    tracao_submersa = models.JSONField(null=True, blank=True)
    tracao_estufa = models.JSONField(null=True, blank=True)
    tracao_tempo_aberto = models.JSONField(null=True, blank=True)
    modulo_elasticidade = models.JSONField(null=True, blank=True)
    deslizamento = models.JSONField(null=True, blank=True)
    classificacao = models.CharField(max_length=255, null=True, blank=True)

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
    laboratorio = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Análise de Cálculo'
        verbose_name_plural = 'Análises de Cálculo' 
