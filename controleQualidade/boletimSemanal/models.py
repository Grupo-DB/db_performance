"""
Boletim Semanal da Qualidade — acompanhamento por semana ISO dos indicadores que
antes viviam na planilha "Controle de Qualidade - Boletim Semanal.xlsx".

Duas ideias sustentam o desenho:

1. O indicador é CADASTRO, não código. Cada linha da planilha (CO₂ do CV-C, RI da
   hidráulica, PN da Fábrica II...) virou um `IndicadorBoletim` que diz *como* achar
   o número nas análises já lançadas: qual ensaio, de que material/produto, colhido
   onde. Assim o laboratório corrige um mapeamento errado no admin, sem deploy — o
   que importa num domínio em que id de ensaio muda e descrição é digitada por gente.

2. O valor calculado pode ser substituído. A planilha traz células como
   "equip. manut." e "sem atualizaçao": às vezes o número não existe, ou existe e
   está errado. `ResultadoBoletim` guarda essa correção por semana sem apagar o
   cálculo, que continua visível ao lado.
"""
from django.contrib.auth.models import User
from django.db import models

from controleQualidade.amostra.models import ProdutoAmostra
from controleQualidade.ensaio.models import Ensaio


class IndicadorBoletim(models.Model):
    AGREGACAO_MEDIA = 'MEDIA'
    AGREGACAO_PONDERADO = 'PONDERADO'
    AGREGACAO_CHOICES = [
        (AGREGACAO_MEDIA, 'Média das análises da semana'),
        (AGREGACAO_PONDERADO, 'Ponderado pela produção dos componentes'),
    ]

    LIMITE_MAX = 'MAX'
    LIMITE_MIN = 'MIN'
    LIMITE_META = 'META'
    LIMITE_NENHUM = 'NENHUM'
    LIMITE_CHOICES = [
        (LIMITE_MAX, 'Limite máximo (acima está fora)'),
        (LIMITE_MIN, 'Limite mínimo (abaixo está fora)'),
        (LIMITE_META, 'Meta (referência, não reprova)'),
        (LIMITE_NENHUM, 'Sem limite'),
    ]

    # A data que joga a análise numa semana. `Analise.data` é auto_now — ela muda a
    # cada gravação, então NÃO serve de data do ensaio. A coleta é o que interessa
    # ao boletim: é a semana em que o material foi produzido.
    DATA_COLETA = 'data_coleta'
    DATA_ENTRADA = 'data_entrada'
    DATA_FINALIZADA = 'finalizada_at'
    DATA_CHOICES = [
        (DATA_COLETA, 'Data de coleta da amostra (com queda para entrada/finalização)'),
        (DATA_ENTRADA, 'Data de entrada da amostra'),
        (DATA_FINALIZADA, 'Data de finalização da análise'),
    ]

    bloco = models.CharField(
        max_length=60,
        help_text='Agrupador na tela e no PDF (ex.: "CO2", "RI", "NAO_HIDRATADOS"). '
                  'Indicadores do mesmo bloco aparecem na mesma tabela.',
    )
    bloco_titulo = models.CharField(
        max_length=160,
        help_text='Título do bloco como sai no relatório (ex.: "Resíduo Insolúvel — produto final").',
    )
    nome = models.CharField(max_length=160, help_text='Nome da linha (ex.: "RI - Hidratada CH-II").')
    ordem = models.PositiveIntegerField(default=0, help_text='Ordem dentro do bloco.')
    ativo = models.BooleanField(default=True, help_text='Desligado sai da tela e do PDF, mas guarda o histórico.')

    # ── Como achar o valor ───────────────────────────────────────────────────
    agregacao = models.CharField(max_length=12, choices=AGREGACAO_CHOICES, default=AGREGACAO_MEDIA)
    pai = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='componentes',
        help_text='Preenchido nos componentes de um indicador ponderado (ex.: Fábrica I dentro do PN). '
                  'Componente não aparece como linha própria: entra no cálculo do pai.',
    )
    ensaio = models.ForeignKey(
        Ensaio, null=True, blank=True, on_delete=models.SET_NULL, related_name='indicadores_boletim',
        help_text='Ensaio do catálogo. Tem precedência sobre o nome.',
    )
    ensaio_nome = models.CharField(
        max_length=255, blank=True,
        help_text='Alternativa ao ensaio: trecho da descrição (sem diferenciar maiúsculas). '
                  'Também encontra CÁLCULO composto, que não existe na tabela de ensaios — '
                  'é o caso do CO₂ e dos óxidos não hidratados.',
    )
    preferir_calculo = models.BooleanField(
        default=False,
        help_text='Procura primeiro no CÁLCULO composto e só depois no ensaio. Ligue quando o '
                  'ensaio existe mas nasce zerado, servindo apenas de espaço para o cálculo — '
                  'é o caso do CO₂: o ensaio "(Composto) - CO₂" fica em 0 e o valor real está '
                  'no cálculo "(Análise) - CO₂".',
    )
    campo_especial = models.CharField(
        max_length=60, blank=True,
        help_text='Para valores que não são ensaio nem cálculo, e sim campo JSON da análise '
                  '(ex.: peneiras_secas). Use com malha e métrica.',
    )
    peneira_malha = models.CharField(max_length=120, blank=True)
    peneira_metrica = models.CharField(max_length=30, blank=True, help_text='retido | passante | acumulado | passante_acumulado')

    # ── De quais amostras ────────────────────────────────────────────────────
    # Texto e não FK de propósito (menos os produtos): a base tem 'Cal', 'Calcário',
    # 'HIDRÁULICA', 'Fábrica II' digitados na amostra, e a comparação é por trecho.
    material = models.CharField(max_length=120, blank=True, help_text='Ex.: Cal, Calcário, Argamassa.')
    tipo_amostra = models.CharField(max_length=120, blank=True, help_text='Ex.: VIRGEM, CH-II, HIDRÁULICA.')
    local_coleta = models.CharField(max_length=120, blank=True, help_text='Ex.: Fábrica I, Silo 06, Saco.')
    finalidade = models.CharField(max_length=120, blank=True, help_text='Ex.: Controle de Qualidade.')
    produtos = models.ManyToManyField(
        ProdutoAmostra, blank=True, related_name='indicadores_boletim',
        help_text='Restringe a produtos específicos. Vazio = qualquer produto que passe nos '
                  'demais filtros (mais seguro, porque o nome do produto na amostra varia).',
    )
    campo_data = models.CharField(max_length=20, choices=DATA_CHOICES, default=DATA_COLETA)

    # ── Como apresentar e cobrar ─────────────────────────────────────────────
    unidade = models.CharField(max_length=20, blank=True, default='%')
    casas_decimais = models.PositiveSmallIntegerField(default=2)
    tipo_limite = models.CharField(max_length=8, choices=LIMITE_CHOICES, default=LIMITE_NENHUM)
    valor_limite = models.FloatField(
        null=True, blank=True,
        help_text='Na MESMA unidade do resultado. A planilha mostrava 0,05 porque a célula '
                  'era formatada em %; aqui o valor é 5.',
    )

    # ── Produção, para o pai ponderar ────────────────────────────────────────
    producao_codigos = models.CharField(
        max_length=120, blank=True,
        help_text='Códigos de estoque do ERP (ESTQCOD) separados por vírgula, somados como a '
                  'produção deste componente. Ex.: 2737 (CH-II), 2738 (hidráulica).',
    )
    producao_etapa = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Etapa de produção no ERP (BPROEP). Cal: 2 calcinação, 3 beneficiamento, 5 ensacamento.',
    )

    observacao = models.CharField(
        max_length=255, blank=True,
        help_text='Nota interna sobre o mapeamento (ex.: "confirmar se RI (arg) é coleta na Fábrica Argamassa").',
    )

    class Meta:
        verbose_name = 'Indicador do boletim semanal'
        verbose_name_plural = 'Indicadores do boletim semanal'
        ordering = ['bloco', 'ordem', 'nome']

    def __str__(self):
        return self.nome

    @property
    def eh_componente(self) -> bool:
        return self.pai_id is not None

    def codigos_producao(self) -> list[int]:
        codigos = []
        for parte in (self.producao_codigos or '').split(','):
            parte = parte.strip()
            if parte.isdigit():
                codigos.append(int(parte))
        return codigos


class ResultadoBoletim(models.Model):
    """
    Correção manual de uma célula do boletim.

    Só existe quando alguém digitou algo: a ausência de registro significa "vale o
    calculado". `valor` e `texto` são exclusivos na prática — texto é para o caso em
    que não há número a apresentar ("equip. manut.", "sem amostra"), e é isso que a
    planilha fazia escrevendo a justificativa na célula do resultado.
    """
    indicador = models.ForeignKey(IndicadorBoletim, on_delete=models.CASCADE, related_name='resultados')
    ano = models.PositiveSmallIntegerField()
    semana = models.PositiveSmallIntegerField(help_text='Semana ISO (1 a 53).')
    valor = models.FloatField(null=True, blank=True)
    texto = models.CharField(max_length=120, blank=True, help_text='Justificativa no lugar do número.')
    producao = models.FloatField(
        null=True, blank=True,
        help_text='Produção da semana, em toneladas, quando não vem do ERP. '
                  'Usada pelo pai para ponderar.',
    )
    observacao = models.CharField(max_length=255, blank=True)
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Resultado do boletim semanal'
        verbose_name_plural = 'Resultados do boletim semanal'
        ordering = ['-ano', '-semana']
        constraints = [
            models.UniqueConstraint(
                fields=['indicador', 'ano', 'semana'], name='boletim_um_resultado_por_semana',
            ),
        ]
        indexes = [models.Index(fields=['ano', 'semana'])]

    def __str__(self):
        return f'{self.indicador} — {self.ano}/S{self.semana}'
