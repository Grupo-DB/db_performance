from datetime import date

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models


TEMAS = [
    ('AMBIENTAL', 'Meio ambiente'),
    ('SST', 'Saúde e segurança do trabalho'),
    ('MINERARIO', 'Mineração'),
    ('TRABALHISTA', 'Trabalhista'),
    ('TRIBUTARIO', 'Tributário'),
    ('SANITARIO', 'Sanitário / produto'),
    ('OUTRO', 'Outro'),
]


class Norma(models.Model):
    """
    Documento de onde as obrigações saem: uma lei, uma NR, mas também a licença
    de operação, a outorga ou um TAC — para a conformidade os quatro funcionam
    igual (têm número, órgão e geram requisitos), e as licenças têm vencimento.
    """

    TIPOS = [
        ('LEI', 'Lei'),
        ('DECRETO', 'Decreto'),
        ('RESOLUCAO', 'Resolução'),
        ('PORTARIA', 'Portaria'),
        ('INSTRUCAO_NORMATIVA', 'Instrução Normativa'),
        ('NR', 'Norma Regulamentadora'),
        ('NORMA_TECNICA', 'Norma técnica (ABNT)'),
        ('LICENCA', 'Licença ambiental'),
        ('OUTORGA', 'Outorga / autorização'),
        ('TAC', 'TAC / condicionante'),
        ('OUTRO', 'Outro'),
    ]
    ESFERAS = [
        ('FEDERAL', 'Federal'),
        ('ESTADUAL', 'Estadual'),
        ('MUNICIPAL', 'Municipal'),
        ('INTERNA', 'Interna / contratual'),
    ]
    SITUACOES = [
        ('VIGENTE', 'Vigente'),
        ('ALTERADA', 'Vigente com alterações'),
        ('REVOGADA', 'Revogada'),
    ]

    tipo = models.CharField(max_length=30, choices=TIPOS, default='LEI')
    numero = models.CharField(max_length=60, blank=True, default='')
    ano = models.PositiveSmallIntegerField(null=True, blank=True)
    orgao = models.CharField(max_length=120, blank=True, default='', help_text='Ex.: CONAMA, MTE, FEPAM, ANM.')
    esfera = models.CharField(max_length=10, choices=ESFERAS, default='FEDERAL')
    tema = models.CharField(max_length=15, choices=TEMAS, default='AMBIENTAL')
    ementa = models.TextField()
    link = models.URLField(max_length=500, blank=True, default='')
    data_publicacao = models.DateField(null=True, blank=True)
    # Só faz sentido em licença/outorga/TAC: o fim da validade é ele próprio
    # um requisito (renovar com antecedência), e aparece no painel.
    validade = models.DateField(null=True, blank=True)
    situacao = models.CharField(max_length=10, choices=SITUACOES, default='VIGENTE')
    arquivo = models.FileField(upload_to='conformidade/normas/%Y/', blank=True, null=True)
    observacao = models.TextField(blank=True, default='')
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['tema', 'tipo', '-ano', 'numero']
        verbose_name = 'Norma / documento legal'
        verbose_name_plural = 'Normas / documentos legais'

    def __str__(self):
        return self.identificacao

    @property
    def identificacao(self) -> str:
        """'Resolução CONAMA nº 430/2011' — como as pessoas citam a norma."""
        partes = [self.get_tipo_display()]
        if self.orgao:
            partes.append(self.orgao)
        if self.numero:
            partes.append(f'nº {self.numero}' + (f'/{self.ano}' if self.ano else ''))
        elif self.ano:
            partes.append(str(self.ano))
        return ' '.join(partes)


class Requisito(models.Model):
    """Uma obrigação concreta tirada de uma norma, avaliada periodicamente."""

    APLICABILIDADES = [
        ('EM_ANALISE', 'Em análise'),
        ('APLICAVEL', 'Aplicável'),
        ('NAO_APLICAVEL', 'Não aplicável'),
    ]
    SITUACOES = [
        ('NAO_AVALIADO', 'Não avaliado'),
        ('ATENDIDO', 'Atendido'),
        ('PARCIAL', 'Atendido parcialmente'),
        ('NAO_ATENDIDO', 'Não atendido'),
    ]
    ORIGENS = [('MANUAL', 'Cadastro manual'), ('IA', 'Sugerido pela IA')]

    # PROTECT: apagar a norma levaria junto o histórico de verificações, que é
    # justamente a evidência pedida em auditoria. Revogar é o caminho.
    norma = models.ForeignKey(Norma, on_delete=models.PROTECT, related_name='requisitos')
    referencia = models.CharField(max_length=120, blank=True, default='', help_text='Ex.: Art. 16, § 2º / Condicionante 7.')
    descricao = models.TextField(help_text='O que precisa ser feito, em linguagem de quem executa.')
    tema = models.CharField(max_length=15, choices=TEMAS, default='AMBIENTAL')
    aplicabilidade = models.CharField(max_length=15, choices=APLICABILIDADES, default='EM_ANALISE')
    justificativa = models.TextField(blank=True, default='', help_text='Por que se aplica (ou não) à empresa.')
    unidade = models.CharField(max_length=120, blank=True, default='', help_text='Unidade, filial ou setor onde se aplica.')
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='requisitos_legais'
    )
    # 0 = verificação única (obrigação que se cumpre uma vez).
    periodicidade_meses = models.PositiveSmallIntegerField(default=12)
    # Prazo legal fixo, quando a norma dá uma data (ex.: entregar relatório até 31/03).
    prazo_legal = models.DateField(null=True, blank=True)

    # Estado derivado da última verificação — gravado para filtrar e contar sem
    # subconsulta. Só `Verificacao.aplicar_no_requisito` escreve aqui.
    situacao = models.CharField(max_length=15, choices=SITUACOES, default='NAO_AVALIADO')
    ultima_verificacao = models.DateField(null=True, blank=True)
    proxima_verificacao = models.DateField(null=True, blank=True)

    origem = models.CharField(max_length=10, choices=ORIGENS, default='MANUAL')
    # Trecho literal do documento de onde a obrigação foi tirada; a IA só pode
    # sugerir com citação, e quem aprova confere aqui.
    trecho_fonte = models.TextField(blank=True, default='')
    pagina_fonte = models.PositiveIntegerField(null=True, blank=True)

    ativo = models.BooleanField(default=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['norma_id', 'id']
        indexes = [
            models.Index(fields=['aplicabilidade', 'situacao']),
            models.Index(fields=['proxima_verificacao']),
        ]

    def __str__(self):
        ref = f' {self.referencia}' if self.referencia else ''
        return f'{self.norma}{ref}'

    def recalcular_situacao(self):
        """Repõe o estado a partir da verificação mais recente (ou do zero)."""
        ultima = self.verificacoes.order_by('-data', '-id').first()
        if ultima is None:
            self.situacao = 'NAO_AVALIADO'
            self.ultima_verificacao = None
            self.proxima_verificacao = self.prazo_legal
        else:
            self.situacao = ultima.resultado
            self.ultima_verificacao = ultima.data
            self.proxima_verificacao = proxima_data(ultima.data, self.periodicidade_meses)
        self.save(update_fields=['situacao', 'ultima_verificacao', 'proxima_verificacao', 'atualizado_em'])


def proxima_data(base: date, meses: int):
    return base + relativedelta(months=meses) if meses else None


class Verificacao(models.Model):
    """Verificação de Conformidade Legal (VCL): alguém olhou e registrou a evidência."""

    RESULTADOS = [
        ('ATENDIDO', 'Atendido'),
        ('PARCIAL', 'Atendido parcialmente'),
        ('NAO_ATENDIDO', 'Não atendido'),
    ]

    requisito = models.ForeignKey(Requisito, on_delete=models.CASCADE, related_name='verificacoes')
    data = models.DateField(default=date.today)
    resultado = models.CharField(max_length=15, choices=RESULTADOS)
    evidencia = models.TextField(blank=True, default='', help_text='O que foi visto: documento, registro, inspeção.')
    observacao = models.TextField(blank=True, default='')
    verificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data', '-id']
        verbose_name = 'Verificação de conformidade'
        verbose_name_plural = 'Verificações de conformidade'

    def __str__(self):
        return f'{self.requisito} — {self.get_resultado_display()} em {self.data:%d/%m/%Y}'


class EvidenciaAnexo(models.Model):
    verificacao = models.ForeignKey(Verificacao, on_delete=models.CASCADE, related_name='anexos')
    nome = models.CharField(max_length=255, blank=True, default='')
    arquivo = models.FileField(upload_to='conformidade/evidencias/%Y/%m/')
    tamanho = models.PositiveIntegerField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.nome and self.arquivo:
            self.nome = self.arquivo.name
        if self.arquivo and not self.tamanho:
            self.tamanho = self.arquivo.size
        super().save(*args, **kwargs)


class PlanoAcao(models.Model):
    """
    O que fazer para sair do "não atendido". O acompanhamento do dia a dia é no
    Kanban: o plano pode gerar uma tarefa, e a conclusão da tarefa conclui o plano.
    """

    requisito = models.ForeignKey(Requisito, on_delete=models.CASCADE, related_name='planos')
    verificacao = models.ForeignKey(
        Verificacao, null=True, blank=True, on_delete=models.SET_NULL, related_name='planos'
    )
    descricao = models.TextField()
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='planos_acao_legais'
    )
    prazo = models.DateField(null=True, blank=True)
    tarefa = models.ForeignKey(
        'kanban.KanbanTask', null=True, blank=True, on_delete=models.SET_NULL, related_name='planos_conformidade'
    )
    concluido_em = models.DateTimeField(null=True, blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['concluido_em', 'prazo', 'id']
        verbose_name = 'Plano de ação'
        verbose_name_plural = 'Planos de ação'

    def __str__(self):
        return self.descricao[:80]

    @property
    def concluido(self) -> bool:
        return bool(self.concluido_em or (self.tarefa_id and self.tarefa.concluido_em))

    @property
    def status(self) -> str:
        if self.concluido:
            return 'CONCLUIDO'
        if self.prazo and self.prazo < date.today():
            return 'ATRASADO'
        return 'ABERTO'


class ExtracaoIA(models.Model):
    """
    Uma leitura do arquivo da norma pela IA. Guarda as sugestões cruas; nada
    vira requisito sem alguém aprovar na tela de revisão (que chama
    `requisitos/criar-lote/`).
    """

    STATUS = [('PROCESSANDO', 'Processando'), ('CONCLUIDA', 'Concluída'), ('ERRO', 'Erro')]

    norma = models.ForeignKey(Norma, on_delete=models.CASCADE, related_name='extracoes')
    status = models.CharField(max_length=12, choices=STATUS, default='PROCESSANDO')
    itens = models.JSONField(default=list, blank=True)
    resumo = models.TextField(blank=True, default='')
    erro = models.TextField(blank=True, default='')
    # Páginas do PDF que a IA leu, na numeração do original ("20-21, 24-35");
    # vazio = o documento inteiro. db_default: a coluna nasce com DEFAULT no banco,
    # então o código antigo continua inserindo enquanto o deploy não termina.
    paginas = models.CharField(max_length=200, blank=True, default='', db_default='')
    # Normas técnicas (ABNT NBR) citadas no documento — ver normas_tecnicas.py.
    # null = leitura anterior a 15/10/2026; a tela preenche pela regex na primeira vez que abre.
    normas_citadas = models.JSONField(null=True, blank=True)
    modelo = models.CharField(max_length=80, blank=True, default='')
    tokens_entrada = models.PositiveIntegerField(default=0)
    tokens_saida = models.PositiveIntegerField(default=0)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Extração por IA'
        verbose_name_plural = 'Extrações por IA'

    def __str__(self):
        return f'{self.norma} — {self.get_status_display()} ({self.criado_em:%d/%m/%Y %H:%M})'


class PublicacaoMonitorada(models.Model):
    """
    Publicação de diário oficial que pode interessar à empresa (fase 3).

    A coleta diária (monitor.py) só grava o que passou pelo filtro de órgão, tipo e
    palavras-chave; a IA dá uma relevância com o motivo; quem decide é a equipe —
    descartar ou cadastrar como norma. Nada aqui vira obrigação sozinho.
    """

    FONTES = [('DOE_RS', 'Diário Oficial do RS'), ('DOU', 'Diário Oficial da União')]
    STATUS = [('NOVA', 'Para avaliar'), ('DESCARTADA', 'Descartada'), ('CADASTRADA', 'Cadastrada como norma')]
    RELEVANCIAS = [('ALTA', 'Alta'), ('MEDIA', 'Média'), ('BAIXA', 'Baixa'), ('NENHUMA', 'Não se aplica')]

    fonte = models.CharField(max_length=10, choices=FONTES)
    id_externo = models.CharField(max_length=64, help_text='Id da matéria na fonte (evita gravar duas vezes).')
    data_publicacao = models.DateField()
    orgao = models.CharField(max_length=255, blank=True, default='')
    tipo = models.CharField(max_length=120, blank=True, default='')
    titulo = models.CharField(max_length=500, blank=True, default='')
    texto = models.TextField(blank=True, default='')
    link = models.URLField(max_length=500, blank=True, default='')
    pagina = models.PositiveIntegerField(null=True, blank=True)
    palavras = models.JSONField(default=list, blank=True, help_text='Palavras-chave que fizeram a publicação entrar.')
    origem = models.CharField(max_length=120, blank=True, default='', db_default='',
                              help_text='Órgão/consulta do monitor que trouxe a publicação.')

    relevancia = models.CharField(max_length=10, choices=RELEVANCIAS, blank=True, default='')
    analise = models.TextField(blank=True, default='', help_text='Por que a IA acha que interessa (ou não).')
    tema_sugerido = models.CharField(max_length=15, choices=TEMAS, blank=True, default='')
    analisada_em = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=12, choices=STATUS, default='NOVA')
    norma = models.ForeignKey(Norma, null=True, blank=True, on_delete=models.SET_NULL, related_name='publicacoes')
    motivo_descarte = models.TextField(blank=True, default='')
    avaliado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    avaliado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_publicacao', '-id']
        constraints = [models.UniqueConstraint(fields=['fonte', 'id_externo'], name='publicacao_unica_por_fonte')]
        indexes = [models.Index(fields=['status', 'data_publicacao'])]
        verbose_name = 'Publicação monitorada'
        verbose_name_plural = 'Publicações monitoradas'

    def __str__(self):
        return f'{self.get_fonte_display()} {self.data_publicacao:%d/%m/%Y} — {self.titulo[:80]}'


class ExecucaoMonitor(models.Model):
    """Uma coleta de um dia numa fonte. É daqui que sai o aviso de que a fonte parou de responder."""

    fonte = models.CharField(max_length=10, choices=PublicacaoMonitorada.FONTES)
    data_referencia = models.DateField()
    iniciado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    examinadas = models.PositiveIntegerField(default=0, help_text='Matérias vistas nas consultas.')
    novas = models.PositiveIntegerField(default=0, help_text='Gravadas como publicação para avaliar.')
    erro = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-iniciado_em']
        verbose_name = 'Execução do monitor'
        verbose_name_plural = 'Execuções do monitor'

    def __str__(self):
        return f'{self.fonte} {self.data_referencia:%d/%m/%Y} — {"ok" if self.ok else "erro"}'


# ── Configuração do monitor (editável na tela) ────────────────────────────
class PalavraChaveMonitor(models.Model):
    """
    Palavra-chave das Novidades legais. `termos`: um por linha, comparados ao texto
    sem acento e sem maiúsculas, como palavra/expressão inteira ("lavra" não casa
    com "palavra"). Termo começando com "re:" é expressão regular, para os casos que
    uma lista não cobre (ex.: "re:nr-? ?\\d{1,2}" pega NR-1 a NR-38).
    """

    rotulo = models.CharField(max_length=80, unique=True)
    termos = models.TextField(help_text='Um termo por linha.')
    ativo = models.BooleanField(default=True)
    # No DOU, dispara em ato de QUALQUER órgão (não só nos acompanhados) — é como as
    # NBRs citadas nas licenças são vigiadas: a Portaria do Inmetro que muda a NBR
    # não sai pela ANM nem pelo MMA. No DOE-RS a API só busca por órgão, então lá
    # continua valendo só nos órgãos da lista.
    qualquer_orgao = models.BooleanField(default=False, db_default=False)
    # De qual documento a palavra veio (NBR citada numa licença, por exemplo).
    norma_origem = models.ForeignKey('Norma', null=True, blank=True, on_delete=models.SET_NULL, related_name='palavras_monitor')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['rotulo']
        verbose_name = 'Palavra-chave do monitor'
        verbose_name_plural = 'Palavras-chave do monitor'

    def __str__(self):
        return self.rotulo

    def lista_termos(self) -> list[str]:
        """Um termo por linha; numa linha comum, vírgula também separa (exceto em "re:")."""
        termos = []
        for linha in self.termos.split('\n'):
            linha = linha.strip()
            if linha.startswith('re:'):
                termos.append(linha)
            elif linha:
                termos += [t.strip() for t in linha.split(',') if t.strip()]
        return termos


class OrgaoMonitor(models.Model):
    """
    O que o monitor consulta em cada fonte. No DOE-RS a busca da API é por órgão
    (`entidade`, trecho do nome por extenso) ou por tipo de matéria (`tipoMateria`);
    no DOU é um trecho do órgão do ato (`artCategory`) mais o grupo de tipos aceito.
    """

    CAMPOS = [('entidade', 'Órgão (DOE-RS)'), ('tipoMateria', 'Tipo de matéria (DOE-RS)'), ('categoria', 'Órgão (DOU)')]
    TIPOS_DOU = [('NORMATIVOS', 'Atos normativos (lei, decreto, resolução, portaria, IN…)'),
                 ('LEIS', 'Só leis, decretos e medidas provisórias')]

    fonte = models.CharField(max_length=10, choices=PublicacaoMonitorada.FONTES)
    rotulo = models.CharField(max_length=80)
    campo = models.CharField(max_length=12, choices=CAMPOS)
    valor = models.CharField(max_length=200, help_text='Como aparece na fonte. Ex.: "Fundação Estadual de Proteção Ambiental".')
    exige_palavra = models.BooleanField(default=True, help_text='Desligado: entra todo ato desse órgão.')
    tipos_dou = models.CharField(max_length=12, choices=TIPOS_DOU, blank=True, default='NORMATIVOS')
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['fonte', 'ordem', 'id']
        verbose_name = 'Órgão acompanhado pelo monitor'
        verbose_name_plural = 'Órgãos acompanhados pelo monitor'

    def __str__(self):
        return f'{self.get_fonte_display()} — {self.rotulo}'


class ConfiguracaoMonitor(models.Model):
    """Registro único com o que a equipe ajusta sem deploy."""

    perfil_empresa = models.TextField(
        blank=True, default='',
        help_text='Atividades e unidades da empresa. A IA usa para julgar a relevância das publicações e para '
                  'apontar dúvidas de aplicabilidade na leitura de PDFs. Em branco, vale o do servidor (.env).',
    )
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração do monitor'
        verbose_name_plural = 'Configuração do monitor'

    @classmethod
    def atual(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
