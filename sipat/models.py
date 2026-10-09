from django.conf import settings
from django.db import models


TURNO_MANHA = 'M'
TURNO_TARDE = 'T'
TURNOS = [(TURNO_MANHA, 'Manhã'), (TURNO_TARDE, 'Tarde')]


class Evento(models.Model):
    """Uma edição da SIPAT (ex.: 27ª SIPATMIN)."""

    nome = models.CharField(max_length=150)
    data_inicio = models.DateField()
    data_fim = models.DateField()
    # Dias que contam presença, em 'AAAA-MM-DD'. Nasce com os dias úteis do
    # intervalo e pode ser editado (feriado no meio da semana, sábado com palestra).
    dias = models.JSONField(default=list, blank=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_inicio', '-id']
        verbose_name = 'Evento SIPAT'
        verbose_name_plural = 'Eventos SIPAT'

    def __str__(self):
        return self.nome


class Participante(models.Model):
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='participantes')
    # Chave da importação: quando vazia, o nome normalizado faz o papel.
    matricula = models.CharField(max_length=50, blank=True, default='')
    nome = models.CharField(max_length=200)
    setor = models.CharField(max_length=150, blank=True, default='')
    empresa = models.CharField(max_length=150, blank=True, default='')
    # Desligar tira do sorteio sem apagar presença nem histórico.
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        indexes = [models.Index(fields=['evento', 'matricula'])]

    def __str__(self):
        return self.nome


class Presenca(models.Model):
    participante = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name='presencas')
    data = models.DateField()
    turno = models.CharField(max_length=1, choices=TURNOS)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    registrado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('participante', 'data', 'turno')
        ordering = ['data', 'turno']


class Premio(models.Model):
    CATEGORIA_MAIOR = 'MAIOR'
    CATEGORIA_MENOR = 'MENOR'
    CATEGORIAS = [(CATEGORIA_MAIOR, 'Prêmio maior'), (CATEGORIA_MENOR, 'Prêmio menor')]

    # Quem concorre ao prêmio.
    REGRA_SEMANA = 'SEMANA'      # presente em todos os dias do evento (qualquer turno)
    REGRA_DIA = 'DIA'            # presente no dia (e turno, se informado) do prêmio
    REGRA_QUALQUER = 'QUALQUER'  # ao menos uma presença no evento
    REGRAS = [
        (REGRA_SEMANA, 'Presentes a semana inteira'),
        (REGRA_DIA, 'Presentes no dia'),
        (REGRA_QUALQUER, 'Qualquer presença'),
    ]

    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='premios')
    descricao = models.CharField(max_length=200)
    categoria = models.CharField(max_length=10, choices=CATEGORIAS, default=CATEGORIA_MENOR)
    regra = models.CharField(max_length=10, choices=REGRAS, default=REGRA_QUALQUER)
    data = models.DateField(null=True, blank=True)
    turno = models.CharField(max_length=1, choices=TURNOS, blank=True, default='')
    quantidade = models.PositiveIntegerField(default=1)
    ordem = models.PositiveIntegerField(default=0)
    patrocinador = models.CharField(max_length=150, blank=True, default='')

    class Meta:
        ordering = ['ordem', 'id']

    def __str__(self):
        return self.descricao


class Sorteio(models.Model):
    STATUS_GANHADOR = 'GANHADOR'
    # Sorteado que não estava lá para receber: libera a unidade do prêmio para
    # novo sorteio, mas a pessoa continua fora dos próximos.
    STATUS_AUSENTE = 'AUSENTE'
    STATUS = [(STATUS_GANHADOR, 'Ganhador'), (STATUS_AUSENTE, 'Ausente na hora')]

    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='sorteios')
    premio = models.ForeignKey(Premio, on_delete=models.CASCADE, related_name='sorteios')
    participante = models.ForeignKey(Participante, on_delete=models.PROTECT, related_name='sorteios')
    status = models.CharField(max_length=10, choices=STATUS, default=STATUS_GANHADOR)
    # Tamanho da urna no momento do sorteio — prova de que a regra foi aplicada.
    total_concorrentes = models.PositiveIntegerField(default=0)
    sorteado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    sorteado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sorteado_em', '-id']
        # Garante no banco a regra "quem foi sorteado não concorre de novo".
        unique_together = ('evento', 'participante')
