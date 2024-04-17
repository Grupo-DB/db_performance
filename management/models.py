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
    nome = models.CharField(max_length=50, null=False, blank=False)
    cnpj = models.CharField(max_length=25, null=False, blank=False)
    endereco = models.CharField(max_length=50,null=False, blank=False)
    cidade = models.CharField(max_length=30,null=False, blank=False)
    estado = models.CharField(max_length=2,null=False, blank=False)
    codigo = models.CharField(max_length=2,null=False, blank=False)

class Filial(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='filiais')
    nome = models.CharField(max_length=50, null=False,blank=False)
    cnpj = models.CharField(max_length=23,null=False,blank=False)
    endereco = models.CharField(max_length=50,null=False, blank=False)
    cidade = models.CharField(max_length=50,null=False, blank=False)
    estado = models.CharField(max_length=2,null=False, blank=False)
    codigo = models.CharField(max_length=2,null=False, blank=False)

class Area(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='areas')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='areas')
    nome = models.CharField(max_length=20, null=False, blank=False)

class Setor(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='setores')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='setores')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='setores')
    nome = models.CharField(max_length=20, null=False, blank=False)

class Cargo(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='cargos')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='cargos')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='cargos')
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, related_name='cargos')
    nome = models.CharField(max_length=20, null=False, blank=False)

class TipoContrato(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='tiposcontratos')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='tiposcontratos')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='tiposcontratos')
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, related_name='tiposcontratos')
    nome = models.CharField(max_length=20, null=False, blank=False)


def upload_image_colaborador(instance,filename):
        return f"{instance.id} - {filename}"

class Colaborador(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='colaboradores')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='colaboradores')
    setor = models.ForeignKey(Setor,on_delete=models.CASCADE,related_name='colaboradores')
    cargo = models.ForeignKey(Cargo, on_delete=models.CASCADE,related_name='colaboradores')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='colaboradores')
    tipocontrato = models.ForeignKey(TipoContrato, on_delete=models.CASCADE,related_name='colaboradores')
    nome = models.CharField(max_length=100,blank=False,null=False)
    data_admissao = models.DateField(blank=False,null=False)
    situacao = models.BooleanField(blank=False,null=False)
    genero = models.CharField(max_length=15,null=False,blank=False)
    estado_civil = models.CharField(max_length=15,blank=True,null=True)
    data_nascimento = models.DateField(blank=True,null=False)
    data_troca_setor = models.DateField(blank=True,null=True)
    data_troca_cargo = models.DateField(blank=True,null=False)
    data_demissao = models.DateField(blank=True,null=False)
    create_at = models.DateTimeField(auto_now_add=True)
    image = models.ImageField(upload_to=upload_image_colaborador,blank=True,null=True)
    


class Avaliador(models.Model):
    id = models.AutoField(primary_key=True,)
    colaborador = models.ForeignKey(Colaborador, on_delete=models.CASCADE,related_name='avaliadores')
    usuario = models.ForeignKey(User,on_delete=models.CASCADE,related_name='avaliadores')
    

class TipoAvaliacao(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=20, null=False, blank=False)

