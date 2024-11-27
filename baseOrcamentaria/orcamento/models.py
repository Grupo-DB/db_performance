from django.db import models
from django.contrib.auth.models import Group, Permission
from django.dispatch import receiver
from django.db.models.signals import pre_save
from avaliacoes.management.models import Ambiente, Area, Colaborador, Empresa, Filial, Setor

class Gestor(Colaborador):
    class Meta:
        verbose_name = 'Gestor'
        verbose_name_plural = 'Gestores'

class RaizAnalitica(models.Model):
    id = models.AutoField(primary_key=True)
    raiz_contabil = models.CharField(max_length=80, null=False, blank=False, unique=True) #entrada pelo user 9 ultimos #unique
    descricao = models.CharField(max_length=555, null=False, blank=False) # concatenação n5 e n6 where = raiz fornecida
    gestor = models.ForeignKey(Gestor, on_delete=models.RESTRICT, related_name='gestores')# listar gestors
    class Meta:
        verbose_name = 'Raiz Analitica'
        verbose_name_plural = 'Raizes Analiticas'
  

class CentroCustoPai(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, blank=False, null=False) #input do user
    empresa = models.ForeignKey(Empresa, on_delete=models.RESTRICT, related_name='gestores_empresas+')#cascata
    filial = models.ForeignKey(Filial, on_delete=models.RESTRICT, related_name='gestores_filiais+')
    area = models.ForeignKey(Area, on_delete=models.RESTRICT, related_name='gestores_areas')
    setor = models.ForeignKey(Setor, on_delete=models.RESTRICT, related_name='orcamentos_setores+')
    ambiente = models.ForeignKey(Ambiente, on_delete=models.RESTRICT, related_name='orcamentos_ambientes+')
    class Meta:
        verbose_name = 'CentroCustoPai'
        verbose_name_plural = 'CentrosCustoPai'

#importar depois
class CentroCusto(models.Model):
    id = models.AutoField(primary_key=True)
    codigo = models.CharField(max_length=80, blank=False, null=False)
    nome = models.CharField(max_length=555, blank=False, null=False)
    cc_pai = models.ForeignKey(CentroCustoPai, on_delete=models.RESTRICT, related_name='cc_pai') 
    gestor = models.ForeignKey(Gestor, on_delete=models.RESTRICT, related_name='Centros de Custo Pai+')
    class Meta:
        verbose_name = 'Centro de Custo'
        verbose_name_plural = 'Centros de Custos'

class RaizSintetica(models.Model):
    id = models.AutoField(primary_key=True)
    raiz_contabil = models.CharField(max_length=80 ,null=False, blank=False) #input from user  4primeiros dig
    descricao = models.CharField(max_length=555, blank=False, null=False) #nome n3 where 4 primeiros dig conta contabil = input 
    natureza = models.CharField(max_length=80, blank=False, null=False) # primeiro caracter da raiz contabil
    centro_custo = models.OneToOneField(CentroCusto,on_delete=models.RESTRICT, related_name='raiz_sintetica+') 
    
    class Meta:
        verbose_name = 'Raiz Sintetica'
        verbose_name_plural = 'Raizes Sinteticas'

class ContaContabil(models.Model):
    id = models.AutoField(primary_key=True)
    nivel_1_conta = models.CharField(max_length=1,blank=True, null=True)
    nivel_1_nome = models.CharField(max_length=255, blank=True, null=True)
    nivel_2_conta = models.CharField(max_length=2, blank=True, null=True)
    nivel_2_nome = models.CharField(max_length=255, blank=True, null=True)
    nivel_3_conta = models.CharField(max_length=4 ,blank=True, null=True)
    nivel_3_nome = models.CharField(max_length=255, blank=True, null=True)
    nivel_4_conta = models.CharField(max_length=6, blank=True, null=True)
    nivel_4_nome = models.CharField(max_length=255, blank=True, null=True)
    nivel_5_conta = models.CharField(max_length=7, blank=True, null=True)
    nivel_5_nome = models.CharField(max_length=255, blank=True, null=True)
    nivel_analitico_conta = models.CharField(max_length=13, blank=True, null=True)
    nivel_analitico_nome = models.CharField(max_length=255, blank=True, null=True)
    class Meta:
        verbose_name = 'Conta Contabil'
        verbose_name_plural = 'Contas Contabeis'

class GrupoItens(models.Model):
    id = models.AutoField(primary_key=True)
    codigo = models.IntegerField(blank=False, null=False)
    nome_completo = models.CharField(max_length=555, null=False, blank=False)
    nivel_1 = models.CharField(max_length=255, blank=True, null=True)
    nivel_2 = models.CharField(max_length=255, blank=True, null=True)
    nivel_3 = models.CharField(max_length=255, blank=True, null=True)
    nivel_4 = models.CharField(max_length=255, blank=True, null=True)
    nivel_5 = models.CharField(max_length=255, blank=True, null=True)
    nivel_6 = models.CharField(max_length=255, blank=True, null=True)
    nivel_7 = models.CharField(max_length=255, blank=True, null=True)
    gestor = models.ForeignKey(Gestor, on_delete=models.RESTRICT, null=True, related_name='gestores_grupos_de_itens')
    class Meta:
        verbose_name = 'Grupo de Itens'
        verbose_name_plural = 'Grupos de Itens'

class OrcamentoBase(models.Model):
    PERIODICIDADE_CHOICES = [
        ('anual', 'Anual'),
        ('mensal', 'Mensal'),
    ]
    MENSAL_CHOICES = [
        ('especifico', 'Mês Específico'),
        ('recorrente', 'Recorrente'),
    ]
    id = models.AutoField(primary_key=True)
    ano = models.CharField(max_length=255, blank=False, null=False)
    centro_de_custo_pai = models.ForeignKey(CentroCustoPai, on_delete=models.RESTRICT, related_name='orcamentosPai+')
    centro_custo_nome = models.ForeignKey(CentroCusto, on_delete=models.RESTRICT, related_name='orçamentos_ccs+') #cascata selecionavel
    gestor = models.CharField(max_length=255, blank=False, null=False) #cascata conforme o CC
    empresa = models.CharField(max_length=255, blank=False, null=False)#informações obtidas pelo cc pai apenas visivel
    filial = models.CharField(max_length=255, blank=False, null=False)
    area = models.CharField(max_length=255, blank=False, null=False)
    setor = models.CharField(max_length=255, blank=False, null=False)
    ambiente = models.CharField(max_length=255, blank=False, null=False)######
    raiz_sintetica = models.ForeignKey(RaizSintetica, on_delete=models.RESTRICT, related_name='orcamentos_raiz_sintetica+') # raiz pertencente ao centro de custo
    raiz_sintetica_desc = models.CharField(max_length=255, blank=False, null=False) # descrição da raiz sintetica informada #somente visivel a desc byCC
    raiz_analitica = models.ForeignKey(RaizAnalitica, on_delete=models.RESTRICT, related_name='orcamentos_raiz_analitica+') # listar da tabela do banco
    raiz_analitica_desc = models.CharField(max_length=555, blank=False, null=False) #descrição da raiz anatica informada #somente visivel a desc
    conta_contabil = models.CharField(max_length=255, blank=False, null=False) # concatenar codigos raiz sintetica e analitica #apenas gravar
    conta_contabil_descricao = models.CharField(max_length=555, blank=True, null=True) #apenas gravar N analiitico nome
    raiz_contabil_grupo_desc = models.CharField(max_length=555, blank=True, null=True) #n4 conta contabil informada apenas exibe
    periodicidade = models.CharField(max_length=255, null=False, blank=False) #mensal ou anual
    mensal_tipo = models.CharField(max_length=255, choices=MENSAL_CHOICES, blank=True)
    mes_especifico = models.IntegerField(blank=True)  # 1-12
    meses_recorrentes = models.CharField(max_length=255, blank=True)  # Ex: 1,2,3,4
    suplementacao = models.BooleanField(blank=False, null=True) #seleção na tela
    base_orcamento = models.CharField(max_length=555, blank=True, null=True) #lista na tela
    id_base = models.CharField(max_length=255, null=True, blank=True) #concatenar cod_cc + cod_conta_contabil completa informada #apenas grvar
    valor = models.DecimalField(max_digits=10, decimal_places=2, null=False, blank=False, default=0.00, verbose_name='Valor') #BRL
    valor_ajustado = models.DecimalField(max_digits=10,decimal_places=2, null=True,blank=True)
    class Meta:
        verbose_name = 'Orcamento Base'
        verbose_name_plural = 'Orcamentos Base'

