"""
Recrutamento e Seleção -- substitui a planilha "Gestão DB | RH V.2.0".

Diferenças em relação à planilha de origem:

* As 23 colunas de "área de interesse" (CONTABIL, FINANCEIRO, ...) viraram a
  tabela ``AreaInteresse`` + M2M, para que o RH cadastre novas áreas sem
  precisar de migração.
* As abas ``Recrutamento`` e ``Seleção`` foram unificadas em ``Processo``.
  Na planilha a aba Seleção só repetia vaga/candidato/contratado do
  Recrutamento (a coluna PARECER dela estava 100% vazia nas 1.072 linhas),
  o que obrigava a digitar tudo duas vezes. A tela de Seleção agora é uma
  leitura de ``Processo`` agrupada por vaga.
* ``Processo.etapa`` é derivada das datas preenchidas, o que permite o
  acompanhamento em funil/kanban que a planilha não tinha.
"""

from datetime import date

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class AreaInteresse(models.Model):
    """Área/setor em que o candidato tem interesse ou experiência."""

    nome = models.CharField(max_length=80, unique=True)
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Área de interesse'
        verbose_name_plural = 'Áreas de interesse'
        ordering = ['ordem', 'nome']

    def __str__(self):
        return self.nome


class Candidato(models.Model):
    """Currículo do banco de talentos (aba Cad_Currículos)."""

    SEXO_CHOICES = [('MASCULINO', 'Masculino'), ('FEMININO', 'Feminino')]
    ESTADO_CIVIL_CHOICES = [
        ('SOLTEIRO(A)', 'Solteiro(a)'),
        ('UNIÃO ESTÁVEL', 'União estável'),
        ('CASADO(A)', 'Casado(a)'),
        ('SEPARADO(A)', 'Separado(a)'),
        ('DIVORCIADO(A)', 'Divorciado(a)'),
        ('VIÚVO(A)', 'Viúvo(a)'),
    ]
    ESCOLARIDADE_CHOICES = [
        ('ENSINO FUNDAMENTAL INCOMPLETO', 'Ensino fundamental incompleto'),
        ('ENSINO FUNDAMENTAL COMPLETO', 'Ensino fundamental completo'),
        ('ENSINO MÉDIO INCOMPLETO', 'Ensino médio incompleto'),
        ('ENSINO MÉDIO COMPLETO', 'Ensino médio completo'),
        ('TÉCNICO', 'Técnico'),
        ('TECNÓLOGO', 'Tecnólogo'),
        ('ENSINO SUPERIOR INCOMPLETO', 'Ensino superior incompleto'),
        ('ENSINO SUPERIOR COMPLETO', 'Ensino superior completo'),
        ('PÓS GRADUAÇÃO', 'Pós-graduação'),
        ('MESTRADO', 'Mestrado'),
        ('DOUTORADO', 'Doutorado'),
        ('PÓS-DOUTORADO', 'Pós-doutorado'),
    ]
    NIVEL_CHOICES = [('BÁSICO', 'Básico'), ('INTERMEDIÁRIO', 'Intermediário'), ('AVANÇADO', 'Avançado')]
    TURNO_CHOICES = [
        ('MANHÃ', 'Manhã'), ('TARDE', 'Tarde'), ('NOITE', 'Noite'),
        ('MANHÃ E TARDE', 'Manhã e tarde'), ('TARDE E NOITE', 'Tarde e noite'),
    ]

    # --- identificação ---
    id_legado = models.PositiveIntegerField(
        null=True, blank=True, unique=True, db_index=True,
        help_text='ID_CADCV da planilha de origem.',
    )
    nome = models.CharField(max_length=255, db_index=True)
    data_recebimento = models.DateField(null=True, blank=True, help_text='Data de recebimento do currículo.')
    data_nascimento = models.DateField(null=True, blank=True)
    ano_nascimento = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1920), MaxValueValidator(2100)],
        help_text='Usado quando só o ano é conhecido (boa parte do acervo legado).',
    )
    sexo = models.CharField(max_length=20, choices=SEXO_CHOICES, blank=True)
    estado_civil = models.CharField(max_length=20, choices=ESTADO_CIVIL_CHOICES, blank=True)

    # --- contato ---
    endereco = models.CharField(max_length=255, blank=True)
    cidade = models.CharField(max_length=120, blank=True, db_index=True)
    telefone_principal = models.CharField(max_length=30, blank=True)
    telefone_contato = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    # --- documentos (dados sensíveis: só RHGestor/Admin/Master enxergam) ---
    tem_ctps = models.BooleanField(null=True, blank=True)
    ctps_numero = models.CharField(max_length=40, blank=True)
    identidade = models.CharField(max_length=40, blank=True)
    cpf = models.CharField(max_length=20, blank=True, db_index=True)
    titulo_eleitor = models.CharField(max_length=40, blank=True)
    certificado_reservista = models.CharField(max_length=40, blank=True)
    cnh_categoria = models.CharField(max_length=5, blank=True)
    cnh_numero = models.CharField(max_length=40, blank=True)
    pis = models.CharField(max_length=40, blank=True)

    # --- família ---
    numero_dependentes = models.PositiveSmallIntegerField(null=True, blank=True)
    nome_conjuge = models.CharField(max_length=255, blank=True)
    nascimento_conjuge = models.DateField(null=True, blank=True)
    profissao_conjuge = models.CharField(max_length=120, blank=True)
    nome_pai = models.CharField(max_length=255, blank=True)
    nascimento_pai = models.DateField(null=True, blank=True)
    profissao_pai = models.CharField(max_length=120, blank=True)
    nome_mae = models.CharField(max_length=255, blank=True)
    nascimento_mae = models.DateField(null=True, blank=True)
    profissao_mae = models.CharField(max_length=120, blank=True)

    # --- experiência ---
    ultima_empresa = models.CharField(max_length=180, blank=True)
    ultima_empresa_periodo = models.CharField(max_length=80, blank=True)
    ultima_empresa_funcao = models.CharField(max_length=180, blank=True)
    penultima_empresa = models.CharField(max_length=180, blank=True)
    penultima_empresa_periodo = models.CharField(max_length=80, blank=True)
    penultima_empresa_funcao = models.CharField(max_length=180, blank=True)

    # --- formação ---
    escolaridade = models.CharField(max_length=40, choices=ESCOLARIDADE_CHOICES, blank=True, db_index=True)
    instituicao_ensino = models.CharField(max_length=180, blank=True)
    data_conclusao = models.CharField(max_length=40, blank=True)
    estuda_atualmente = models.BooleanField(null=True, blank=True)
    local_estudo = models.CharField(max_length=180, blank=True)
    turno_estudo = models.CharField(max_length=20, choices=TURNO_CHOICES, blank=True)
    curso_1 = models.CharField(max_length=180, blank=True)
    curso_1_local = models.CharField(max_length=180, blank=True)
    curso_1_ano = models.CharField(max_length=20, blank=True)
    curso_2 = models.CharField(max_length=180, blank=True)
    curso_2_local = models.CharField(max_length=180, blank=True)
    curso_2_ano = models.CharField(max_length=20, blank=True)
    nivel_office = models.CharField(max_length=20, choices=NIVEL_CHOICES, blank=True)
    nivel_internet = models.CharField(max_length=20, choices=NIVEL_CHOICES, blank=True)
    outros_conhecimentos = models.TextField(blank=True)
    complemento_escolaridade = models.CharField(max_length=255, blank=True)

    # --- interesses / triagem ---
    areas_interesse = models.ManyToManyField(AreaInteresse, blank=True, related_name='candidatos')
    funcao_desejada = models.CharField(max_length=255, blank=True, db_index=True)
    pretensao_salarial = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    pcd = models.BooleanField(null=True, blank=True, verbose_name='Pessoa com deficiência')
    pcd_descricao = models.CharField(max_length=255, blank=True)
    conhece_funcionario = models.CharField(max_length=255, blank=True)
    ja_trabalhou_db = models.BooleanField(null=True, blank=True)

    # --- referências ---
    referencia_1 = models.CharField(max_length=180, blank=True)
    referencia_1_telefone = models.CharField(max_length=30, blank=True)
    referencia_2 = models.CharField(max_length=180, blank=True)
    referencia_2_telefone = models.CharField(max_length=30, blank=True)

    # --- arquivo ---
    pasta_arquivo = models.CharField(max_length=180, blank=True, help_text='Onde o currículo físico/digital está guardado.')
    anexo = models.FileField(upload_to='recrutamento/curriculos/', null=True, blank=True)
    observacoes = models.TextField(blank=True)
    ativo = models.BooleanField(default=True, help_text='Desmarque para arquivar sem perder o histórico.')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Candidato'
        verbose_name_plural = 'Candidatos'
        ordering = ['nome']
        indexes = [models.Index(fields=['nome', 'cidade'])]

    def __str__(self):
        return self.nome

    @property
    def idade(self):
        """Idade em anos; cai para o ano de nascimento quando não há data completa."""
        hoje = date.today()
        if self.data_nascimento:
            return hoje.year - self.data_nascimento.year - (
                (hoje.month, hoje.day) < (self.data_nascimento.month, self.data_nascimento.day)
            )
        if self.ano_nascimento:
            return hoje.year - self.ano_nascimento
        return None


class Vaga(models.Model):
    """Vaga aberta pelo requisitante (aba Cad_Vagas)."""

    TIPO_INTERNA = 'INTERNA'
    TIPO_EXTERNA = 'EXTERNA'
    TIPO_CHOICES = [(TIPO_INTERNA, 'Interna'), (TIPO_EXTERNA, 'Externa')]

    STATUS_ABERTA = 'ABERTA'
    STATUS_STAND_BY = 'STAND BY'
    STATUS_CANCELADA = 'CANCELADA'
    STATUS_CONCLUIDA = 'CONCLUÍDA'
    # 90 vagas de 2021 vieram da planilha sem status nenhum. Marcá-las como
    # abertas inflaria o indicador de vagas em aberto (26 reais -> 116), então
    # elas ficam num status próprio, fora das contagens de andamento.
    STATUS_NAO_INFORMADO = 'NAO INFORM'
    STATUS_CHOICES = [
        (STATUS_ABERTA, 'Aberta'),
        (STATUS_STAND_BY, 'Stand by'),
        (STATUS_CANCELADA, 'Cancelada'),
        (STATUS_CONCLUIDA, 'Concluída'),
        (STATUS_NAO_INFORMADO, 'Não informado (legado)'),
    ]
    STATUS_EM_ANDAMENTO = [STATUS_ABERTA, STATUS_STAND_BY]

    id_legado = models.PositiveIntegerField(null=True, blank=True, unique=True, db_index=True)
    descricao = models.CharField(max_length=255, db_index=True, help_text='Cargo/função da vaga.')
    requisitante = models.CharField(max_length=180, blank=True, db_index=True)
    area = models.ForeignKey(
        AreaInteresse, null=True, blank=True, on_delete=models.SET_NULL, related_name='vagas',
    )
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default=TIPO_EXTERNA)
    quantidade_posicoes = models.PositiveSmallIntegerField(default=1)
    # Nulo permitido: 96 vagas do acervo legado (2021-2022) nunca tiveram a
    # data de abertura registrada, e 187 processos apontam para elas.
    data_abertura = models.DateField(null=True, blank=True, db_index=True)
    prazo_encerramento = models.DateField(null=True, blank=True, help_text='Prazo combinado com o requisitante.')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_ABERTA, db_index=True)
    data_retorno_requisitante = models.DateField(null=True, blank=True)
    observacoes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Vaga'
        verbose_name_plural = 'Vagas'
        ordering = ['-data_abertura', '-id']

    def __str__(self):
        return f'#{self.id_legado or self.id} - {self.descricao}'

    @property
    def tempo_retorno(self):
        """Dias entre a abertura e o retorno ao requisitante (coluna TEMPO_RETORNO_REQUI)."""
        if self.data_retorno_requisitante and self.data_abertura:
            return (self.data_retorno_requisitante - self.data_abertura).days
        return None

    @property
    def dias_em_aberto(self):
        """Dias corridos desde a abertura; congela na data de retorno quando encerrada."""
        if not self.data_abertura:
            return None
        fim = self.data_retorno_requisitante if self.status in (self.STATUS_CONCLUIDA, self.STATUS_CANCELADA) else None
        return ((fim or date.today()) - self.data_abertura).days

    @property
    def atrasada(self):
        return bool(
            self.prazo_encerramento
            and self.status in self.STATUS_EM_ANDAMENTO
            and self.prazo_encerramento < date.today()
        )

    @property
    def sem_data_abertura(self):
        """Sinaliza na tela as vagas legadas que precisam da data preenchida."""
        return self.data_abertura is None


class Processo(models.Model):
    """
    Um candidato dentro de um processo de recrutamento/seleção.

    Unifica as abas ``Recrutamento`` e ``Seleção``: a Seleção era apenas um
    recorte por vaga dos mesmos dados.
    """

    PARECER_INDICADO = 'INDICADO'
    PARECER_INDICADO_RESTRICOES = 'INDICADO_RESTRICOES'
    PARECER_CONTRAINDICADO = 'CONTRAINDICADO'
    PARECER_CHOICES = [
        (PARECER_INDICADO, 'Indicado(a)'),
        (PARECER_INDICADO_RESTRICOES, 'Indicado(a) com restrições'),
        (PARECER_CONTRAINDICADO, 'Contraindicado(a)'),
    ]

    # Etapas do funil, na ordem em que acontecem.
    ETAPA_TRIAGEM = 'TRIAGEM'
    ETAPA_CONTATO = 'CONTATO'
    ETAPA_ENTREVISTA = 'ENTREVISTA'
    ETAPA_PARECER = 'PARECER'
    ETAPA_RETORNO = 'RETORNO'
    ETAPA_CONTRATADO = 'CONTRATADO'
    ETAPA_ENCERRADO = 'ENCERRADO'
    ETAPA_CHOICES = [
        (ETAPA_TRIAGEM, 'Triagem'),
        (ETAPA_CONTATO, 'Contato realizado'),
        (ETAPA_ENTREVISTA, 'Entrevista'),
        (ETAPA_PARECER, 'Parecer emitido'),
        (ETAPA_RETORNO, 'Retorno ao candidato'),
        (ETAPA_CONTRATADO, 'Contratado'),
        (ETAPA_ENCERRADO, 'Encerrado'),
    ]

    id_legado = models.PositiveIntegerField(null=True, blank=True, unique=True, db_index=True)
    candidato = models.ForeignKey(Candidato, on_delete=models.PROTECT, related_name='processos')
    vaga = models.ForeignKey(Vaga, null=True, blank=True, on_delete=models.SET_NULL, related_name='processos')

    # --- contato ---
    data_contato = models.DateField(null=True, blank=True, db_index=True)
    responsavel_contato = models.CharField(max_length=120, blank=True, db_index=True)
    tentativas_contato = models.PositiveSmallIntegerField(null=True, blank=True)
    contato_com_sucesso = models.BooleanField(null=True, blank=True)

    # --- entrevista ---
    data_entrevista = models.DateField(null=True, blank=True, db_index=True)
    compareceu = models.BooleanField(null=True, blank=True)

    # --- parecer ---
    data_parecer = models.DateField(null=True, blank=True)
    parecer = models.CharField(max_length=25, choices=PARECER_CHOICES, blank=True, db_index=True)
    avaliador = models.CharField(max_length=120, blank=True, help_text='Psicólogo(a) responsável pela avaliação.')

    # --- retornos ---
    data_retorno_requisitante = models.DateField(null=True, blank=True)
    observacao_requisitante = models.TextField(blank=True)
    data_retorno_candidato = models.DateField(null=True, blank=True)
    observacao_candidato = models.TextField(blank=True)

    # --- desfecho ---
    contratado = models.BooleanField(null=True, blank=True, db_index=True)
    data_contratacao = models.DateField(null=True, blank=True, db_index=True)
    ex_funcionario = models.BooleanField(default=False)
    etapa = models.CharField(max_length=12, choices=ETAPA_CHOICES, default=ETAPA_TRIAGEM, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Processo de recrutamento'
        verbose_name_plural = 'Processos de recrutamento'
        ordering = ['-data_contato', '-id']
        indexes = [
            models.Index(fields=['vaga', 'contratado']),
            models.Index(fields=['etapa', 'data_contato']),
        ]

    def __str__(self):
        return f'{self.candidato.nome} - {self.vaga.descricao if self.vaga else "sem vaga"}'

    # -- métricas usadas nos indicadores -------------------------------------

    @property
    def tempo_para_entrevista(self):
        """Dias entre o recebimento do currículo e a entrevista (TEMPO_PARA_ENTREV)."""
        recebimento = self.candidato.data_recebimento
        if self.data_entrevista and recebimento:
            return (self.data_entrevista - recebimento).days
        return None

    @property
    def tempo_retorno_candidato(self):
        """Dias entre a entrevista e o retorno dado ao candidato (TEMPO_RET_CAND)."""
        if self.data_retorno_candidato and self.data_entrevista:
            return (self.data_retorno_candidato - self.data_entrevista).days
        return None

    def calcular_etapa(self):
        """Deriva a etapa do funil a partir do que já foi preenchido."""
        if self.contratado and self.data_contratacao:
            return self.ETAPA_CONTRATADO
        if self.contratado is False and self.data_retorno_candidato:
            return self.ETAPA_ENCERRADO
        if self.contato_com_sucesso is False and self.tentativas_contato:
            return self.ETAPA_ENCERRADO
        if self.data_retorno_candidato:
            return self.ETAPA_RETORNO
        if self.parecer or self.data_parecer:
            return self.ETAPA_PARECER
        if self.data_entrevista:
            return self.ETAPA_ENTREVISTA
        if self.data_contato:
            return self.ETAPA_CONTATO
        return self.ETAPA_TRIAGEM

    def save(self, *args, **kwargs):
        self.etapa = self.calcular_etapa()
        super().save(*args, **kwargs)
