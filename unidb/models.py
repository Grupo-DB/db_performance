"""
UNIDB — Universidade Corporativa Dagoberto Barcellos.

Porte da planilha `Quadro_de_avaliacao_UNIDB_-_Versao_2.0.xlsx`, que o RH mantinha à
mão. O mapeamento aba → modelo é:

    CAD_FUNC              → Aluno
    CAD_CURSOS            → Curso (o que se repete) + Turma (cada realização)
    CAD_MATRICULAS        → Matricula
    REG_TREINAMENTOS_NOVO → AvaliacaoTreinamento (a ficha "mod. novo")

A planilha guarda numa linha só o curso e a turma: `CÓDIGO DO CURSO` 594 com
`CÓDIGO DO MÓDULO` 594.1, datas, instrutor e número de pessoas. Aqui isso virou dois
modelos (decisão do usuário, 19/08/2026): o que não muda de uma turma para outra —
área, validade, pesos, nota mínima — fica no Curso, e cada realização é uma Turma. Sem
isso, o nome e a validade de um mesmo treinamento se repetiriam em dezenas de linhas e
divergiriam com o tempo.
"""
from django.db import models


class Aluno(models.Model):
    """
    Quem faz treinamento. Inclui gente de fora (`origem` EXTERNO), que o cadastro de
    colaboradores do módulo de avaliações não cobre.

    `colaborador` é o vínculo OPCIONAL com esse cadastro: quando o aluno é funcionário,
    dá para chegar em empresa/filial/área sem repetir o dado aqui. Fica nulo para
    externo e para funcionário que ainda não foi casado.
    """
    ORIGEM_CHOICES = [('INTERNO', 'Interno'), ('EXTERNO', 'Externo')]

    id = models.AutoField(primary_key=True)
    # Chapa do ERP. Texto e não inteiro: a planilha tem matrícula com zero à esquerda e
    # aluno externo com código próprio (20000).
    matricula = models.CharField(max_length=20, unique=True)
    nome = models.CharField(max_length=255)
    cargo = models.CharField(max_length=255, blank=True, null=True)
    setor = models.CharField(max_length=255, blank=True, null=True)
    data_admissao = models.DateField(blank=True, null=True)
    # Quando entrou na UNIDB — é diferente da admissão e é o que o RH usa como início
    # da vida escolar do aluno.
    data_matricula_unidb = models.DateField(blank=True, null=True)
    # Coluna "GRUPO ALVO - CARGO" da planilha: agrupa cargos que compartilham a mesma
    # grade obrigatória de treinamentos.
    grupo_alvo = models.CharField(max_length=50, blank=True, null=True)
    origem = models.CharField(max_length=10, choices=ORIGEM_CHOICES, default='INTERNO')
    colaborador = models.ForeignKey(
        'management.Colaborador', on_delete=models.SET_NULL, blank=True, null=True,
        related_name='alunos_unidb',
    )
    ativo = models.BooleanField(default=True)
    observacoes = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Aluno'
        verbose_name_plural = 'Alunos'
        ordering = ['nome']

    def __str__(self):
        return f'{self.matricula} — {self.nome}'


class Curso(models.Model):
    """
    O treinamento em si, independente de quando foi dado.

    Identidade é o NOME: a planilha não tem um código estável para o curso (o código é
    da realização), e é pelo nome que o RH reconhece ("NR-22 SEGURANÇA NA MINERAÇÃO").
    """
    STATUS_CHOICES = [('ATIVO', 'Ativo'), ('INATIVO', 'Inativo')]
    TIPO_CHOICES = [
        ('TEORICO', 'Teórico'),
        ('PRATICO', 'Prático'),
        ('TEORICO E PRATICO', 'Teórico e prático'),
        ('EAD', 'EAD'),
    ]

    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, unique=True)
    area = models.CharField(max_length=255, blank=True, null=True)
    tipo_treinamento = models.CharField(max_length=50, choices=TIPO_CHOICES, blank=True, null=True)
    # A planilha guarda SIM/NAO: se o treinamento tem prova.
    tem_avaliacao = models.BooleanField(default=True)
    pre_requisito = models.CharField(max_length=255, blank=True, null=True)
    publico_alvo = models.CharField(max_length=255, blank=True, null=True)
    aberto_publico_interno = models.BooleanField(default=False)
    aberto_publico_externo = models.BooleanField(default=False)

    # ── Regras de pontuação e vencimento (colunas da direita da CAD_CURSOS) ────
    # `validade_dias` alimenta a data de vencimento da turma; a planilha usa valores
    # grandes (18000) para o que na prática não vence.
    validade_dias = models.IntegerField(blank=True, null=True)
    periodicidade_meses = models.IntegerField(blank=True, null=True)
    pontuacao = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    alavanca_ni = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    nota_minima = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    peso_assiduidade = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    peso_avaliacao_comportamental = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    peso_avaliacao_tecnica = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ATIVO')
    observacao = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Curso'
        verbose_name_plural = 'Cursos'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Turma(models.Model):
    """
    Uma realização do curso: a linha da CAD_CURSOS com data, instrutor e vagas.

    `codigo` e `codigo_modulo` são os da planilha (594 e 594.1) e ficam como texto —
    são o que aparece na lista de presença e o que o RH usa para se localizar no
    histórico. Não são chave: turma nova pode nascer sem código.
    """
    id = models.AutoField(primary_key=True)
    curso = models.ForeignKey(Curso, on_delete=models.PROTECT, related_name='turmas')
    codigo = models.CharField(max_length=20, blank=True, null=True)
    codigo_modulo = models.CharField(max_length=20, blank=True, null=True)
    # O módulo costuma repetir o nome do treinamento, mas em curso dividido em partes
    # é ele que diz qual parte foi dada.
    modulo = models.CharField(max_length=255, blank=True, null=True)
    instrutor = models.CharField(max_length=255, blank=True, null=True)
    data_inicial = models.DateField(blank=True, null=True)
    data_final = models.DateField(blank=True, null=True)
    horas_aula = models.DecimalField(max_digits=7, decimal_places=2, blank=True, null=True)
    # "CARGA" da planilha: carga horária total quando difere das horas-aula.
    carga = models.DecimalField(max_digits=7, decimal_places=2, blank=True, null=True)
    # Vagas previstas ("NÚMERO DE PESSOAS"). Quantos foram de fato é a contagem de
    # matrículas — por isso não guardamos o realizado aqui.
    vagas = models.IntegerField(blank=True, null=True)
    data_vencimento = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=Curso.STATUS_CHOICES, default='ATIVO')
    observacao = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Turma'
        verbose_name_plural = 'Turmas'
        ordering = ['-data_inicial', '-id']

    def __str__(self):
        quando = self.data_inicial.strftime('%d/%m/%Y') if self.data_inicial else 'sem data'
        return f'{self.curso.nome} ({quando})'


class Matricula(models.Model):
    """
    Aluno numa turma — a linha da CAD_MATRICULAS (8.458 na planilha).

    `presente` existe para a lista de presença virar dado: hoje a folha é assinada no
    papel e ninguém sabe depois quem faltou. Fica nulo enquanto a chamada não foi feita.
    """
    SITUACAO_CHOICES = [
        ('MATRICULADO', 'Matriculado'),
        ('CONCLUIDO', 'Concluído'),
        ('REPROVADO', 'Reprovado'),
        ('DESISTENTE', 'Desistente'),
    ]

    id = models.AutoField(primary_key=True)
    turma = models.ForeignKey(Turma, on_delete=models.CASCADE, related_name='matriculas')
    aluno = models.ForeignKey(Aluno, on_delete=models.PROTECT, related_name='matriculas')
    data_matricula = models.DateField(blank=True, null=True)
    presente = models.BooleanField(blank=True, null=True)
    nota = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    situacao = models.CharField(max_length=15, choices=SITUACAO_CHOICES, default='MATRICULADO')
    observacao = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Matrícula'
        verbose_name_plural = 'Matrículas'
        # O mesmo aluno não se matricula duas vezes na mesma turma — é isso que torna a
        # importação da planilha repetível sem duplicar as 8.458 linhas.
        unique_together = ('turma', 'aluno')
        ordering = ['aluno__nome']

    def __str__(self):
        return f'{self.aluno.nome} — {self.turma}'


class AvaliacaoTreinamento(models.Model):
    """
    Ficha "Avaliação pós-treinamento" (mod. novo), respondida pelos participantes.

    É ANÔNIMA por decisão do usuário (19/08/2026), como na planilha: a aba
    REG_TREINAMENTOS_NOVO não tem coluna de aluno. São várias respostas por turma.

    `nome_treinamento` e `instrutor` ficam gravados como texto além da FK porque a
    planilha só traz esses nomes: resposta antiga que não casou com nenhuma turma entra
    com `turma` nula e o texto preservado, em vez de ser descartada.
    """
    ESCALA_QUALIDADE = [
        ('EXCELENTE', 'Excelente'), ('BOM', 'Bom'),
        ('REGULAR', 'Regular'), ('RUIM', 'Ruim'),
    ]
    ESCALA_SIM = [
        ('SIM', 'Sim'), ('PARCIALMENTE', 'Parcialmente'), ('NAO', 'Não'),
    ]
    ESCALA_TEMPO = [
        ('ADEQUADO', 'Adequado'), ('MUITO CURTO', 'Muito curto'), ('MUITO LONGO', 'Muito longo'),
    ]

    id = models.AutoField(primary_key=True)
    turma = models.ForeignKey(Turma, on_delete=models.CASCADE, blank=True, null=True,
                              related_name='avaliacoes')
    nome_treinamento = models.CharField(max_length=255, blank=True, null=True)
    instrutor = models.CharField(max_length=255, blank=True, null=True)
    data_conclusao = models.DateField(blank=True, null=True)

    # ── As cinco perguntas fechadas do mod. novo ──────────────────────────────
    avaliacao_geral = models.CharField(max_length=15, choices=ESCALA_QUALIDADE, blank=True, null=True)
    conteudo_atendeu = models.CharField(max_length=15, choices=ESCALA_SIM, blank=True, null=True)
    didatica_instrutor = models.CharField(max_length=15, choices=ESCALA_QUALIDADE, blank=True, null=True)
    material_apoio = models.CharField(max_length=15, choices=ESCALA_SIM, blank=True, null=True)
    tempo_duracao = models.CharField(max_length=15, choices=ESCALA_TEMPO, blank=True, null=True)

    # ── As duas abertas ───────────────────────────────────────────────────────
    pontos_positivos = models.TextField(blank=True, null=True)
    pontos_melhoria = models.TextField(blank=True, null=True)

    # A ficha é anônima e uma resposta pode ser idêntica à outra, então não há chave
    # natural para reimportar sem duplicar: a aba é recarregada do zero. Esta marca
    # delimita o que a importação pode apagar — o que o RH digitar na tela fica.
    importada_da_planilha = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Avaliação de treinamento'
        verbose_name_plural = 'Avaliações de treinamento'
        ordering = ['-data_conclusao', '-id']

    def __str__(self):
        nome = self.nome_treinamento or (self.turma.curso.nome if self.turma else 'sem treinamento')
        return f'Avaliação — {nome}'
