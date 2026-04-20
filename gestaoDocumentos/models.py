from django.db import models

class Diretorio(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=True, blank=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    descricao = models.TextField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Diretório'
        verbose_name_plural = 'Diretórios'

class Contrato(models.Model):
    id = models.AutoField(primary_key=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    numero = models.CharField(max_length=255, null=True, blank=True)
    contratado = models.CharField(max_length=400, null=True, blank=True)
    contratante = models.CharField(max_length=400, null=True, blank=True)
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    objeto_contrato = models.CharField(max_length=400, null=True, blank=True)
    valor_contrato = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    vigencia = models.CharField(max_length=255, null=True, blank=True)
    prazo_aviso = models.CharField(max_length=255, null=True, blank=True)
    responsave_interno = models.CharField(max_length=255, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_contratante = models.CharField(max_length=855, null=True, blank=True)
    responsavel_contratado = models.CharField(max_length=855, null=True, blank=True)
    multa_recisao = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    reajuste = models.CharField(max_length=255, null=True, blank=True)
    forma_pagamento = models.CharField(max_length=255, null=True, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    renovacao = models.BooleanField(default=False)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='contratos')
    anexo = models.FileField(upload_to='contratos/', null=True, blank=True)
    class Meta:
        verbose_name = 'Contrato'
        verbose_name_plural = 'Contratos'

class Processo(models.Model):
    id = models.AutoField(primary_key=True)
    tag = models.CharField(max_length=255, null=True, blank=True)
    titulo = models.CharField(max_length=255, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_setor = models.CharField(max_length=255, null=True, blank=True)
    versao = models.CharField(max_length=255, null=True, blank=True)
    data_versao = models.DateField(null=True, blank=True)
    documento_citado = models.TextField(null=True, blank=True)
    copia_fisica_setores = models.CharField(max_length=255, null=True, blank=True)
    copia_digital_setores = models.CharField(max_length=255, null=True, blank=True)
    periodicidade_auditoria = models.CharField(max_length=255, null=True, blank=True)
    ultima_auditoria = models.DateField(null=True, blank=True)
    periodicidade_reciclagem = models.CharField(max_length=255, null=True, blank=True)
    ultimo_treinamento = models.DateField(null=True, blank=True)
    status = models.BooleanField(default=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='processos')
    anexo = models.FileField(upload_to='processos/', null=True, blank=True)
    class Meta:
        verbose_name = 'Processo'
        verbose_name_plural = 'Processos'


class Acao(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=True, blank=True)
    cpf = models.CharField(max_length=14, null=True, blank=True)
    especie = models.BooleanField(default=True)
    quantidade = models.IntegerField(null=True, blank=True)
    participacao = models.CharField(max_length=255, null=True, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    status = models.BooleanField(default=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='acoes')
    anexo = models.FileField(upload_to='acoes/', null=True, blank=True)
    class Meta:
        verbose_name = 'Ação'
        verbose_name_plural = 'Ações'

class Alvara(models.Model):
    id = models.AutoField(primary_key=True)
    empresa_titular = models.CharField(max_length=255, null=True, blank=True)
    tipo_alvara = models.CharField(max_length=255, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_setor = models.CharField(max_length=255, null=True, blank=True)
    responsavel_alvara = models.CharField(max_length=255, null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    vigencia = models.CharField(max_length=255, null=True, blank=True)
    status = models.BooleanField(default=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='alvaras')
    anexo = models.FileField(upload_to='alvaras/', null=True, blank=True)
    class Meta:
        verbose_name = 'Alvará'
        verbose_name_plural = 'Alvarás'

class Procuracao(models.Model):
    id = models.AutoField(primary_key=True)
    outorgante = models.CharField(max_length=255, null=True, blank=True)
    outorgado = models.CharField(max_length=255, null=True, blank=True)
    poderes = models.TextField(null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    vigencia = models.CharField(max_length=255, null=True, blank=True)
    status = models.BooleanField(default=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='procuracoes')
    anexo = models.FileField(upload_to='procuracoes/', null=True, blank=True)
    class Meta:
        verbose_name = 'Procuração'
        verbose_name_plural = 'Procurações'

class Patrimonial(models.Model):
    id = models.AutoField(primary_key=True)
    titular = models.CharField(max_length=255, null=True, blank=True)
    tipo_bem = models.CharField(max_length=255, null=True, blank=True)
    descricao_bem = models.CharField(max_length=255, null=True, blank=True)
    localizacao_tipo = models.CharField(max_length=255, null=True, blank=True)
    endereco = models.CharField(max_length=255, null=True, blank=True)
    bairro = models.CharField(max_length=255, null=True, blank=True)
    cidade = models.CharField(max_length=255, null=True, blank=True)
    estado = models.CharField(max_length=255, null=True, blank=True)
    cep = models.CharField(max_length=20, null=True, blank=True)
    distrito = models.CharField(max_length=255, null=True, blank=True)
    coordenadas = models.CharField(max_length=255, null=True, blank=True)
    codigo_cartorio = models.CharField(max_length=255, null=True, blank=True)
    matricula = models.CharField(max_length=255, null=True, blank=True)
    comarca = models.CharField(max_length=255, null=True, blank=True)
    zona = models.CharField(max_length=255, null=True, blank=True)
    valor_contabil = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    bemfeitoria = models.CharField(max_length=255, null=True, blank=True)
    area_privativa = models.CharField(max_length=255, null=True, blank=True)
    area_total = models.CharField(max_length=255, null=True, blank=True)
    tipo_construcao = models.CharField(max_length=255, null=True, blank=True)
    estado_conservacao = models.CharField(max_length=255, null=True, blank=True)
    padrao_construtivo = models.CharField(max_length=255, null=True, blank=True)
    idade = models.CharField(max_length=255, null=True, blank=True)
    status = models.BooleanField(default=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='patrimoniais')
    anexo = models.FileField(upload_to='patrimoniais/', null=True, blank=True)
    class Meta:
        verbose_name = 'Patrimonial'
        verbose_name_plural = 'Patrimoniais'