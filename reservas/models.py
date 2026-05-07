from django.db import models

# Create your models here.
class Objeto(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=455, null=False, blank=False)
    tipo = models.CharField(max_length=455, null=False, blank=False)
    descricao = models.CharField(max_length=455, null=True, blank=True)
    placa = models.CharField(max_length=455, null=True, blank=True)
    class Meta:
        verbose_name = 'Objeto'
        verbose_name_plural = 'Objetos'

class Reserva(models.Model):
    id = models.AutoField(primary_key=True)
    objeto = models.CharField(max_length=455, null=False, blank=False)
    data_inicio = models.DateField(null=False, blank=False)
    hora_inicio = models.TimeField(null=False, blank=False)
    data_fim = models.DateField(null=False, blank=False)
    hora_fim = models.TimeField(null=False, blank=False)
    tempo_total = models.CharField(max_length=455, null=True, blank=True)
    responsavel = models.CharField(max_length=455, null=False, blank=False)
    observacoes = models.TextField(null=True, blank=True)
    class Meta:
        verbose_name = 'Reserva'
        verbose_name_plural = 'Reservas'