from django.db import models
from django.contrib.auth.models import User, AbstractUser,Group,Permission


class PerfilUsuario(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=120)

    def __str__(self):
        return self.user.username
    





# class Empresa
class Empresa(models.Model):
    id = models.AutoField(primary_key=True,)
    nome = models.CharField(max_length=20, null=False, blank=False)
    cnpj = models.CharField(max_length=15, null=False, blank=False)
    endereco = models.CharField(max_length=50,null=False, blank=False)
    cidade = models.CharField(max_length=30,null=False, blank=False)
    estado = models.CharField(max_length=2,null=False, blank=False)
    codigo = models.CharField(max_length=2,null=False, blank=False)

class Filial(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='filiais')
    nome = models.CharField(max_length=20, null=False,blank=False)
    cnpj = models.CharField(max_length=13,null=False,blank=False)
    endereco = models.CharField(max_length=50,null=False, blank=False)
    estado = models.CharField(max_length=2,null=False, blank=False)
    codigo = models.CharField(max_length=2,null=False, blank=False)

class Setor(models.Model):
    id = models.AutoField(primary_key=True,)
    nome = models.CharField(max_length=20, null=False, blank=False)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='setores')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='setores')

class Area(models.Model):
    id = models.AutoField(primary_key=True,)
    nome = models.CharField(max_length=20, null=False, blank=False)

class Cargo(models.Model):
    id = models.AutoField(primary_key=True,)
    nome = models.CharField(max_length=20, null=False, blank=False)

class TipoContrato(models.Model):
    id = models.AutoField(primary_key=True,)
    nome = models.CharField(max_length=20, null=False, blank=False)

class Colaborador(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='colaboradores')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='colaboradores')
    setor = models.ForeignKey(Setor,on_delete=models.CASCADE,related_name='colaboradores')

def upload_image_colaborador(instance,filename):
    return f"{instance.id} - {filename}"


class Avaliador(models.Model):
    id = models.AutoField(primary_key=True,)
    colaborador = models.ForeignKey(Colaborador, on_delete=models.CASCADE,related_name='avaliadores')
    usuario = models.ForeignKey(User,on_delete=models.CASCADE,related_name='usuarios')
    image = models.ImageField(upload_to=upload_image_colaborador,blank=True,null=True)

class TipoAvaliacao(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=20, null=False, blank=False)       