from django.db import models
from baseOrcamentaria.dre.models import Produto
from controleQualidade.ordem.models import Ordem, OrdemExpressa

class TipoAmostra(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=355, null=False, blank=False)
    natureza = models.CharField(max_length=355, null=True, blank=True)
    material = models.CharField(max_length=255, null=True, blank=True)
    class meta:
        verbose_name = 'Tipo de Amostra'
        verbose_name_plural = 'Tipos de Amostra'

class ProdutoAmostra(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    registro_empresa = models.CharField(max_length=255, null=True, blank=True)
    registro_produto = models.CharField(max_length=255, null=True, blank=True)
    material = models.CharField(max_length=255, null=False, blank=False)
    cod_db = models.CharField(max_length=255, null=True, blank=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    subtipo = models.CharField(max_length=255, null=True, blank=True)
    class meta:
        verbose_name = 'Produto'
        verbose_name_plural = 'Produtos'


# def upload_image_amostra(amostra,filename):
#         return f"{amostra.id}-{filename}"

def upload_image_amostra(instance, filename):
    return f"amostra_{instance.amostra.id}/{filename}"

class Amostra(models.Model):
    id = models.AutoField(primary_key=True)
    material = models.CharField(max_length=255, null=False, blank=False) #add os 10 tipos
    finalidade = models.CharField(max_length=255, null=True, blank=True) #(sac, controle de qualidade, desenvolvimento de produtos)
    numero_sac = models.CharField(max_length=255, null=True, blank=True) #numero do sac quando for da finalidade sac
    data_envio = models.DateField(null=True, blank=True) #data de envio
    destino_envio = models.CharField(max_length=255, null=True, blank=True) #destino do envio
    data_recebida = models.DateField(null=True, blank=True) #data de recebimento    
    reter = models.BooleanField(default=True) #se a amostra foi retida ou não
    data_coleta = models.DateField(null=False, blank=False)
    data_entrada = models.DateField(null=False, blank=False)
    numero = models.CharField(max_length=255, null=False, blank=False)
    tipo_amostra = models.CharField(max_length=255, null=True, blank=True)
    subtipo = models.CharField(max_length=255, null=True, blank=True)
    produto_amostra = models.ForeignKey(ProdutoAmostra, null=True, blank=True, on_delete=models.RESTRICT, related_name='amostra') 
    cod_db = models.CharField(max_length=255, null=True, blank=True)
    fornecedor = models.CharField(max_length=255, null=True, blank=True)
    periodo_hora = models.CharField(max_length=255, null=True, blank=True)
    periodo_turno = models.CharField(max_length=255, null=True, blank=True)
    tipo_amostragem = models.CharField(max_length=255, null=True, blank=True)
    local_coleta = models.CharField(max_length=255, null=True, blank=True)
    registro_ep = models.CharField(max_length=255, null=True, blank=True)
    registro_produto = models.CharField(max_length=255, null=True, blank=True)
    numero_lote = models.CharField(max_length=255, null=True, blank=True)
    representatividade_lote = models.CharField(max_length=255, null=True, blank=True)
    identificacao_complementar = models.CharField(max_length=955, null=True, blank=True)
    observacoes = models.CharField(max_length=955, null=True, blank=True)
    complemento = models.CharField(max_length=955,null=True, blank=True)
    ordem = models.OneToOneField(Ordem, null=True, blank=True, on_delete=models.RESTRICT, related_name='amostra')
    expressa = models.OneToOneField(OrdemExpressa, null=True, blank=True, on_delete=models.RESTRICT, related_name='amostra')
    digitador = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=255, null=False, blank=False)
    class Meta:
        verbose_name = 'Amostra'
        verbose_name_plural = 'Amostras'

class AmostraImagem(models.Model):
    id = models.AutoField(primary_key=True)
    amostra = models.ForeignKey(Amostra, on_delete=models.CASCADE, related_name='imagens')
    image = models.FileField(upload_to=upload_image_amostra, blank=False, null=False)
    descricao = models.CharField(max_length=255, null=True, blank=True)
    data_upload = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Imagem da Amostra'
        verbose_name_plural = 'Imagens da Amostra'        