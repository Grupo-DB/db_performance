from django.db import models


class TipoEnsaio(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    class meta:
        verbose_name = 'Tipo de Ensaio'
        verbose_name_plural = 'Tipos de Ensaio'

class Ensaio(models.Model):
    id = models.AutoField(primary_key=True)
    descricao = models.CharField(max_length=500, null=False, blank=False)
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    valor = models.FloatField(null=True, blank=True)
    tipo_ensaio = models.ForeignKey(TipoEnsaio, null=True, blank=True, on_delete=models.RESTRICT, related_name='ensaio')
    tempo_previsto = models.CharField(max_length=255, null=True, blank=True)
    class meta:
        verbose_name = 'Ensaio'
        verbose_name_plural = 'Ensaios'
