from django.db import models

class RegistroHoraExtra(models.Model):
    id = models.AutoField(primary_key=True)
    colaborador = models.CharField(max_length=200, null=False, blank=False)
    data = models.DateField(null=False, blank=False)
    hora_inicial = models.TimeField(null=False, blank=False)
    hora_final = models.TimeField(null=False, blank=False)
    horas = models.DecimalField(max_digits=5, decimal_places=2, null=False, blank=False)
    motivo = models.TextField(null=True, blank=True)
    responsavel = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        verbose_name = 'Registro de Hora Extra'
        verbose_name_plural = 'Registros de Hora Extra'
