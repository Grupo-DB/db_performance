from django.db import models
from baseOrcamentaria.dre.models import Linha
from controleQualidade.ordem.models import Ordem

class TipoAmostra(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=355, null=False, blank=False)
    natureza = models.CharField(max_length=355, null=False, blank=False)

    class meta:
        verbose_name = 'Tipo de Amostra'
        verbose_name_plural = 'Tipos de Amostra'

class Produto(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    registro_empresa = models.CharField(max_length=255, null=False, blank=False)
    registro_produto = models.CharField(max_length=255, null=False, blank=False)        
    class meta:
        verbose_name = 'Produto'
        verbose_name_plural = 'Produtos'

class Amostra(models.Model):
    id = models.AutoField(primary_key=True)
    data_coleta = models.DateField(null=False, blank=False)
    data_entrada = models.DateField(null=False, blank=False)
    material = models.ForeignKey(Linha, null=True, blank=True, on_delete=models.RESTRICT, related_name='amostra')
    numero = models.CharField(max_length=255, null=False, blank=False)
    tipo_amostra = models.ForeignKey(TipoAmostra, null=True, blank=True, on_delete=models.RESTRICT, related_name='amostra')
    subtipo = models.CharField(max_length=255, null=True, blank=True)
    produto_amostra = models.ForeignKey(Produto, null=True, blank=True, on_delete=models.RESTRICT, related_name='amostra') 
    fornecedor = models.CharField(max_length=255, null=True, blank=True)
    periodo_hora = models.CharField(max_length=255, null=True, blank=True)
    periodo_turno = models.CharField(max_length=255, null=True, blank=True)
    tipo_amostragem = models.CharField(max_length=255, null=True, blank=True)
    local_coleta = models.CharField(max_length=255, null=True, blank=True)
    representatividade_lote = models.CharField(max_length=255, null=True, blank=True)
    identificacao_complementar = models.CharField(max_length=955, null=True, blank=True)
    complemento = models.CharField(max_length=955,null=True, blank=True)
    ordem = models.OneToOneField(Ordem, null=True, blank=True, on_delete=models.RESTRICT, related_name='amostra')
    digitador = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=255, null=False, blank=False)
    class meta:
        verbose_name = 'Amostra'
        verbose_name_plural = 'Amostras'