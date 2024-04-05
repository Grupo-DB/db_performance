from django.db import models
from django.contrib.auth.models import User


class PerfilUsuario(models.Model):
    auth_user = models.OneToOneField(User, on_delete=models.CASCADE)
    funcao = models.CharField(max_length=100)

    def __str__(self):
        return self.user.username


# class Empresa
class Empresa(models.Model):
    id = models.AutoField(primary_key=True,)
    nome = models.CharField(max_length=20, null=False, blank=False)
    cnpj = models.CharField(max_length=14, null=False, blank=False)
    endereco = models.CharField(max_length=50,null=False, blank=False)
    cidade = models.CharField(max_length=30,null=False, blank=False)
    estado = models.CharField(max_length=2,null=False, blank=False)
    codigo = models.CharField(max_length=2,null=False, blank=False)