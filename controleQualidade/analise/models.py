from django.db import models
from controleQualidade.amostra.models import Amostra

class Analise(models.Model):
    id = models.AutoField(primary_key=True)
    data = models.DateTimeField(auto_created=True, auto_now=True, null=False, blank=False)
    amostra = models.ForeignKey(Amostra, null=True, blank=True, on_delete=models.RESTRICT, related_name='analise')
    estado = models.CharField(max_length=255, null=False, blank=False)

    class Meta:
        verbose_name = 'Análise'
        verbose_name_plural = 'Análises'

