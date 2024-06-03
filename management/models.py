from django.db import models
from django.contrib.auth.models import User, AbstractUser,Group,Permission


class PerfilUsuario(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=120)

    def __str__(self):
        return self.user.username


def upload_image_colaborador(colaborador,filename):
        return f"{colaborador.id}-{filename}"


# class Empresa
class Empresa(models.Model):
    id = models.AutoField(primary_key=True,)
    nome = models.CharField(max_length=50, null=False, blank=False)
    cnpj = models.CharField(max_length=25, null=False, blank=False)
    endereco = models.CharField(max_length=50,null=False, blank=False)
    cidade = models.CharField(max_length=30,null=False, blank=False)
    estado = models.CharField(max_length=2,null=False, blank=False)
    codigo = models.CharField(max_length=2,null=False, blank=False)
    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"

class Filial(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='filiais')
    nome = models.CharField(max_length=50, null=False,blank=False)
    cnpj = models.CharField(max_length=23,null=False,blank=False)
    endereco = models.CharField(max_length=50,null=False, blank=False)
    cidade = models.CharField(max_length=50,null=False, blank=False)
    estado = models.CharField(max_length=2,null=False, blank=False)
    codigo = models.CharField(max_length=2,null=False, blank=False)
    class Meta:
        verbose_name = "Filial"
        verbose_name_plural = "Filiais"

class Area(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='areas')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='areas')
    nome = models.CharField(max_length=20, null=False, blank=False)
    class Meta:
        verbose_name = "Area"
        verbose_name_plural = "Areas"

class Setor(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='setores')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='setores')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='setores')
    nome = models.CharField(max_length=20, null=False, blank=False)
    class Meta:
        verbose_name = "Setor"
        verbose_name_plural = "Setores"

class Ambiente(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='ambientes')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='ambientes')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='ambientes')
    setor = models.ForeignKey(Setor,on_delete=models.CASCADE,related_name='ambientes')
    nome = models.CharField(max_length=20, null=False, blank=False)
    class Meta:
        verbose_name = "Ambiente"
        verbose_name_plural = "Ambientes"

class Cargo(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='cargos')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='cargos')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='cargos')
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, related_name='cargos')
    ambiente = models.ForeignKey(Ambiente, on_delete=models.CASCADE, related_name='cargos')
    nome = models.CharField(max_length=20, null=False, blank=False)
    class Meta:
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"

class TipoContrato(models.Model):
    id = models.AutoField(primary_key=True,)
    empresa = models.ForeignKey(Empresa,on_delete=models.CASCADE,related_name='tiposcontratos')
    filial = models.ForeignKey(Filial,on_delete=models.CASCADE,related_name='tiposcontratos')
    area = models.ForeignKey(Area,on_delete=models.CASCADE,related_name='tiposcontratos')
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, related_name='tiposcontratos')
    cargo = models.ForeignKey(Cargo, on_delete=models.CASCADE, related_name='tiposcontratos')
    ambiente = models.ForeignKey(Ambiente, on_delete=models.CASCADE, related_name='tiposcontratos')
    nome = models.CharField(max_length=20, null=False, blank=False)
    class Meta:
        verbose_name = "TipoContrato"
        verbose_name_plural = "TiposContratos"

class Formulario(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=80, null=False, blank=False)
    perguntas = models.ManyToManyField('Pergunta',related_name='formularios')
    class Meta:
        verbose_name = "Formulario"
        verbose_name_plural = "Formularios"

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
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='colaborador')  # Campo opcional para o usuário
    class Meta:
        verbose_name = "Colaborador"
        verbose_name_plural = "Colaboradores"
    

class Avaliador(Colaborador):
    avaliados = models.ManyToManyField('Avaliado', related_name='avaliadores')
    class Meta:
        verbose_name = "Avaliador"
        verbose_name_plural = "Avaliadores"

class Avaliado(Colaborador):
    tipoAvaliacao = models.ManyToManyField('TipoAvaliacao',  related_name='avaliados')

    class Meta:
        verbose_name = "Avaliado"
        verbose_name_plural = "Avaliados"


class TipoAvaliacao(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=60, null=False, blank=False)
    formulario = models.ForeignKey(Formulario, on_delete=models.CASCADE,null=True,blank=True,related_name='TiposAvaliacoes')
    class Meta:
        verbose_name = "TipoAvaliacao"
        verbose_name_plural = "TipoAvaliacoes"

class Pergunta(models.Model):
    texto = models.CharField(max_length=255)
    legenda = models.TextField(max_length=1000)
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
    observacoes = models.TextField(max_length=500, null=True, blank=True)
    create_at = models.DateTimeField(auto_now_add=True)
    feedback = models.BooleanField(default=False, blank=True, null=False)
    finished_at = models.DateField( null=True)
    class Meta:
        verbose_name = "Avaliacao"
        verbose_name_plural = "Avaliacoes"


