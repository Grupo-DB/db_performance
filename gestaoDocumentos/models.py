from django.db import models

class Diretorio(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=True, blank=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    descricao = models.TextField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Diretório'
        verbose_name_plural = 'Diretórios'

class Atas(models.Model):
    id = models.AutoField(primary_key=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    data_reuniao = models.DateField(null=True, blank=True)
    participantes = models.TextField(null=True, blank=True)
    pauta = models.TextField(null=True, blank=True)
    deliberacoes = models.TextField(null=True, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    anexo = models.FileField(upload_to='atas/', null=True, blank=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='atas')
    # Campos gerais:
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Ata'
        verbose_name_plural = 'Atas'

class Societario(models.Model):
    id = models.AutoField(primary_key=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    data_assinatura = models.DateField(null=True, blank=True)
    orgao_registro = models.CharField(max_length=255, null=True, blank=True)
    administadores = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    anexo = models.FileField(upload_to='societarios/', null=True, blank=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='contratos.diretorio+')
     # Campos gerais:
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Societário'
        verbose_name_plural = 'Societários'

class Seguro(models.Model):
    id = models.AutoField(primary_key=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    seguradora = models.CharField(max_length=255, null=True, blank=True)
    numero_apolice = models.CharField(max_length=255, null=True, blank=True)
    empresa_segurada = models.CharField(max_length=255, null=True, blank=True)
    bem_segurado = models.CharField(max_length=255, null=True, blank=True)
    valor_seguro = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    vigencia = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='seguros')
    anexo = models.FileField(upload_to='seguros/', null=True, blank=True)
    # Campos gerais:    
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Seguro'
        verbose_name_plural = 'Seguros'


class Contrato(models.Model):
    id = models.AutoField(primary_key=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    numero = models.CharField(max_length=255, null=True, blank=True)
    contratado = models.CharField(max_length=400, null=True, blank=True)
    contratante = models.CharField(max_length=400, null=True, blank=True)
    objeto_contrato = models.CharField(max_length=400, null=True, blank=True)
    valor_contrato = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    vigencia = models.CharField(max_length=255, null=True, blank=True)
    prazo_aviso = models.CharField(max_length=255, null=True, blank=True)
    responsavel_contratante = models.CharField(max_length=855, null=True, blank=True)
    responsavel_contratado = models.CharField(max_length=855, null=True, blank=True)
    multa_recisao = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    reajuste = models.CharField(max_length=255, null=True, blank=True)
    forma_pagamento = models.CharField(max_length=255, null=True, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    renovacao = models.BooleanField(default=False)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='contratos.diretorio+')
    anexo = models.FileField(upload_to='contratos/', null=True, blank=True)
    # Campos gerais:    
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Contrato'
        verbose_name_plural = 'Contratos'

class ProcessoInterno(models.Model):
    id = models.AutoField(primary_key=True)
    tag = models.CharField(max_length=255, null=True, blank=True)
    titulo = models.CharField(max_length=255, null=True, blank=True)
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
    observacoes = models.TextField(null=True, blank=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='processos')
    anexo = models.FileField(upload_to='processos_internos/', null=True, blank=True)
     # Campos gerais:
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Processo Interno'
        verbose_name_plural = 'Processos Internos'

class ProcessoExterno(models.Model):
    id = models.AutoField(primary_key=True)        
    tipo = models.CharField(max_length=255, null=True, blank=True)
    numero = models.CharField(max_length=255, null=True, blank=True)
    empresa_envolvida = models.CharField(max_length=400, null=True, blank=True)
    parte_contraria = models.CharField(max_length=400, null=True, blank=True)
    orgao_foro = models.CharField(max_length=400, null=True, blank=True)
    vara_instancia = models.CharField(max_length=400, null=True, blank=True)
    objeto_processo = models.TextField(null=True, blank=True)
    valor_causa = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    escritorio_juridico = models.CharField(max_length=400, null=True, blank=True)
    advogado_responsavel = models.CharField(max_length=400, null=True, blank=True)
    andamento = models.TextField(null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='processos_externos')
    anexo = models.FileField(upload_to='processos_externos/', null=True, blank=True)
    # Campos gerais:
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Processo Externo'
        verbose_name_plural = 'Processos Externos'

class Veiculo(models.Model):
    id = models.AutoField(primary_key=True)
    placa = models.CharField(max_length=20, null=True, blank=True)
    modelo_veiculo = models.CharField(max_length=400, null=True, blank=True)
    tipo_documento = models.CharField(max_length=255, null=True, blank=True)
    situacao_veiculo = models.CharField(max_length=255, null=True, blank=True)
    data_emissao = models.DateField(null=True, blank=True)
    data_vencimento = models.DateField(null=True, blank=True)
    vigencia = models.CharField(max_length=255, null=True, blank=True)
    ano_exercicio = models.CharField(max_length=255, null=True, blank=True)
    valor_ipva = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    situacao_pagamento = models.CharField(max_length=255, null=True, blank=True)
    data_pagamento = models.DateField(null=True, blank=True)
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='veiculos')
    anexo = models.FileField(upload_to='veiculos/', null=True, blank=True)
    # Campos gerais:
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    
    created_by = models.CharField(max_length=255, null=True, blank=True)    
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Veículo'
        verbose_name_plural = 'Veículos'

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
    # Campos gerais:
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Ação'
        verbose_name_plural = 'Ações'

class Alvara(models.Model):
    id = models.AutoField(primary_key=True)
    empresa_titular = models.CharField(max_length=255, null=True, blank=True)
    tipo_alvara = models.CharField(max_length=255, null=True, blank=True)
    numero_alvara = models.CharField(max_length=255, null=True, blank=True)
    orgao_emissor = models.CharField(max_length=255, null=True, blank=True)
    responsavel_alvara = models.CharField(max_length=255, null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    vigencia = models.CharField(max_length=255, null=True, blank=True)
    ultima_atualizacao = models.DateField(null=True, blank=True)
    renovavel = models.BooleanField(default=False)
    prazo_renovacao = models.CharField(max_length=255, null=True, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='alvaras')
    anexo = models.FileField(upload_to='alvaras/', null=True, blank=True)
    # Campos gerais:
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Alvará'
        verbose_name_plural = 'Alvarás'

class Procuracao(models.Model):
    id = models.AutoField(primary_key=True)
    outorgante = models.CharField(max_length=255, null=True, blank=True)
    outorgado = models.CharField(max_length=255, null=True, blank=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    poderes = models.TextField(null=True, blank=True)
    finalidade = models.CharField(max_length=255, null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    vigencia = models.CharField(max_length=255, null=True, blank=True)
    substabelecer = models.BooleanField(default=False)
    substabelecimento_vinculado = models.BooleanField(default=False)
    observacoes = models.TextField(null=True, blank=True)
    status = models.BooleanField(default=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='procuracoes')
    anexo = models.FileField(upload_to='procuracoes/', null=True, blank=True)
    # Campos gerais:
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Procuração'
        verbose_name_plural = 'Procurações'

class Patrimonial(models.Model):
    id = models.AutoField(primary_key=True)
    titular = models.CharField(max_length=255, null=True, blank=True)
    tipo_bem = models.CharField(max_length=255, null=True, blank=True)
    descricao_bem = models.CharField(max_length=255, null=True, blank=True)
    cod_interno = models.CharField(max_length=255, null=True, blank=True)
    situacao_bem = models.CharField(max_length=255, null=True, blank=True)
    data_aquisicao = models.DateField(null=True, blank=True)
    forma_aquisicao = models.CharField(max_length=400, null=True, blank=True)
    responsavel_bem = models.CharField(max_length=255, null=True, blank=True)
    # localização
    localizacao_tipo = models.CharField(max_length=255, null=True, blank=True)
    endereco = models.CharField(max_length=255, null=True, blank=True)
    bairro = models.CharField(max_length=255, null=True, blank=True)
    cidade = models.CharField(max_length=255, null=True, blank=True)
    estado = models.CharField(max_length=255, null=True, blank=True)
    cep = models.CharField(max_length=20, null=True, blank=True)
    distrito = models.CharField(max_length=255, null=True, blank=True)
    coordenadas = models.CharField(max_length=255, null=True, blank=True)
    codigo_cartorio = models.CharField(max_length=255, null=True, blank=True)
    # registro
    matricula = models.CharField(max_length=255, null=True, blank=True)
    comarca = models.CharField(max_length=255, null=True, blank=True)
    zona = models.CharField(max_length=255, null=True, blank=True)
    cartorio = models.CharField(max_length=255, null=True, blank=True)
    insc_municipal = models.CharField(max_length=255, null=True, blank=True)
    insc_estadual = models.CharField(max_length=255, null=True, blank=True)
    # benfeitorias
    valor_contabil = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_venal = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_avaliado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    benfeitoria = models.CharField(max_length=255, null=True, blank=True)
    area_privativa = models.CharField(max_length=255, null=True, blank=True)
    area_total = models.CharField(max_length=255, null=True, blank=True)
    tipo_construcao = models.CharField(max_length=255, null=True, blank=True)
    estado_conservacao = models.CharField(max_length=255, null=True, blank=True)
    padrao_construtivo = models.CharField(max_length=255, null=True, blank=True)
    idade = models.CharField(max_length=255, null=True, blank=True)
    # obs
    observacoes = models.TextField(null=True, blank=True)
    status = models.BooleanField(default=True)
    diretorio = models.ForeignKey(Diretorio, on_delete=models.SET_NULL, null=True, blank=True, related_name='patrimoniais')
    anexo = models.FileField(upload_to='patrimoniais/', null=True, blank=True)
    # Campos gerais:
    empresa_grupo = models.CharField(max_length=400, null=True, blank=True)
    setor_interessado = models.CharField(max_length=255, null=True, blank=True)
    responsavel_interno = models.CharField(max_length=255, null=True, blank=True)
    data_cadastro = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)
    updated_by = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Patrimonial'
        verbose_name_plural = 'Patrimoniais'