from django.db import models

from django.db import models

# class Empresa
class Empresa(models.Model):
    id = models.AutoField(primary_key=True,)
    nome = models.CharField(max_length=20, null=False, blank=False)
    cnpj = models.CharField(max_length=14, null=False, blank=False)
    endereco = models.CharField(max_length=50,null=False, blank=False)
    cidade = models.CharField(max_length=30,null=False, blank=False)
    estado = models.CharField(max_length=2,null=False, blank=False)
    codigo = models.CharField(max_length=2,null=False, blank=False)