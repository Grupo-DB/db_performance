from django.db import models
from django.contrib.auth.models import User, AbstractUser,Group,Permission


class PerfilUsuario(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=120)

    def __str__(self):
        return self.user.username


def upload_image_colaborador(Colaborador,filename):
        return f"{Colaborador.id} - {filename}"


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
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='setores')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='setores')
    nome = models.CharField(max_length=20, null=False, blank=False)

class Ambiente(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='ambientes')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='ambientes')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='ambientes')
    setor = models.ForeignKey(Setor,on_delete=models.CASCADE,related_name='ambientes')
    nome = models.CharField(max_length=20, null=False, blank=False)

class Cargo(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='cargos')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='cargos')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='cargos')
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, related_name='cargos')
    ambiente = models.ForeignKey(Ambiente, on_delete=models.CASCADE, related_name='cargos')
    nome = models.CharField(max_length=20, null=False, blank=False)

class TipoContrato(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='tiposcontratos')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='tiposcontratos')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='tiposcontratos')
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, related_name='tiposcontratos')
    cargo = models.ForeignKey(Cargo, on_delete=models.CASCADE, related_name='tiposcontratos')
    ambiente = models.ForeignKey(Ambiente, on_delete=models.CASCADE, related_name='tiposcontratos')
    nome = models.CharField(max_length=20, null=False, blank=False)

class Formulario(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=80, null=False, blank=False)
    perguntas = models.ManyToManyField('Pergunta',related_name='formularios', blank=True, null=True)


class Colaborador(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='colaboradores')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='colaboradores')
    setor = models.ForeignKey(Setor,on_delete=models.CASCADE,related_name='colaboradores')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='colaboradores')
    cargo = models.ForeignKey(Cargo, on_delete=models.CASCADE,related_name='colaboradores')
    ambiente = models.ForeignKey(Ambiente,on_delete=models.CASCADE,related_name='colaboradores')
    tipocontrato = models.ForeignKey(TipoContrato, on_delete=models.CASCADE,related_name='colaboradores')
    nome = models.CharField(max_length=100,blank=False,null=False)
    data_admissao = models.DateTimeField(blank=True,null=True)
    situacao = models.BooleanField(blank=True,null=True)
    genero = models.CharField(max_length=15,null=True,blank=True)
    estado_civil = models.CharField(max_length=15,blank=True,null=True)
    data_nascimento = models.DateTimeField(blank=True,null=True)
    data_troca_setor = models.DateTimeField(blank=True,null=True)
    data_troca_cargo = models.DateTimeField(blank=True,null=True)
    data_demissao = models.DateTimeField(blank=True,null=True)
    create_at = models.DateTimeField(auto_now_add=True)
    image = models.FileField(upload_to=upload_image_colaborador,blank=True,null=True)
    class Meta:
        verbose_name = "Colaborador"
        verbose_name_plural = "Colaboradores"


class Avaliador(Colaborador):
    #colaborador = models.ForeignKey(Colaborador, on_delete=models.CASCADE,related_name='avaliadores')
    usuario = models.OneToOneField(User,on_delete=models.CASCADE,related_name='avaliadores')
    avaliados = models.ManyToManyField('Avaliado', related_name='avaliadores')
    class Meta:
        verbose_name = "Avaliador"
        verbose_name_plural = "Avaliadores"

class Avaliado(Colaborador):
    formulario = models.ForeignKey(Formulario, on_delete=models.CASCADE, related_name='avaliados')

    class Meta:
        verbose_name = "Avaliado"
        verbose_name_plural = "Avaliados"


class TipoAvaliacao(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=60, null=False, blank=False)



class Pergunta(models.Model):
    texto = models.CharField(max_length=255)
    class Meta:
        verbose_name = "Pergunta"
        verbose_name_plural = "Perguntas"




class Avaliacao(models.Model):
    id = models.AutoField(primary_key=True)
    tipoavaliacao = models.ForeignKey(TipoAvaliacao, on_delete=models.CASCADE, related_name='avaliacoes')
    avaliador = models.ForeignKey(Avaliador, on_delete=models.CASCADE, related_name='avaliacoes_avaliador')
    avaliado = models.ForeignKey(Avaliado, on_delete=models.CASCADE, related_name='avaliacoes_avaliado')
    periodo = models.CharField(max_length=60, null=True, blank=True)
    perguntasRespostas = models.JSONField(null=True,blank=True)
    feedback = models.CharField(max_length=60, null=True, blank=True)
    create_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(auto_now=True,blank=True, null=True)
    deleted_at = models.DateTimeField(auto_now=True,blank=True, null=True)

class Respondido(models.Model):
    avaliacao = models.OneToOneField(Avaliacao, on_delete=models.CASCADE, related_name='respondidos')
    pergunta = models.ForeignKey('Pergunta',on_delete=models.CASCADE,related_name='respondidos')
    resposta = models.CharField(max_length=255,blank=True,null=True)
    justificativa = models.CharField(max_length=255,blank=True,null=True)


