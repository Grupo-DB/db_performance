"""
Vistorias periódicas de veículos e equipamentos (escopo v2.1, nov/2026).

Fluxo: o Gerente Executivo Operacional (GEO) monta o programa anual → o avaliador executa a
ficha no celular → o GEO valida (abono/devolução) → o resultado vai ao Indicador mensal.
NC crítica confirmada suspende o equipamento NA HORA (antes de concluir a vistoria), manda
e-mail e só volta a operar depois da correção do PCM validada pelo SESMT ou pelo GEO.

Regras de histórico que moldam os modelos:
* ficha versionada: cada vistoria guarda a versão e uma CÓPIA das questões (Resposta);
* vínculo do equipamento (unidade, setor, gerente, ativo) tem histórico (VinculoEquipamento);
  a vistoria e o resultado mensal gravam o vínculo do dia — trocar o gerente não muda o passado;
* nada de exclusão física de vistoria, NC, suspensão ou resultado: tudo é situação/cancelamento.

Fotos e vídeos ficam FORA do MEDIA_ROOT (o nginx serve /media sem login): só saem pela API.
"""
import uuid as uuid_lib

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone

PRIVADO = FileSystemStorage(
    location=getattr(settings, 'VISTORIAS_PRIVADO', settings.BASE_DIR / 'privado' / 'vistorias'),
    base_url=None,
)

User = settings.AUTH_USER_MODEL

LEVE, MEDIA, CRITICA = 'LEVE', 'MEDIA', 'CRITICA'
CRITICIDADES = [(LEVE, 'Leve'), (MEDIA, 'Média'), (CRITICA, 'Crítica')]

SATISFATORIO, INSATISFATORIO, CRITICO = 'S', 'I', 'C'
RESULTADOS = [(SATISFATORIO, 'Satisfatório'), (INSATISFATORIO, 'Insatisfatório'), (CRITICO, 'Crítico')]

MENSAL, BIMESTRAL, TRIMESTRAL = 'MENSAL', 'BIMESTRAL', 'TRIMESTRAL'
PERIODICIDADES = [(MENSAL, 'Mensal'), (BIMESTRAL, 'Bimestral'), (TRIMESTRAL, 'Trimestral')]

HORIMETRO, ODOMETRO, NENHUMA = 'HORIMETRO', 'ODOMETRO', 'NENHUMA'
MEDICOES = [(HORIMETRO, 'Horímetro'), (ODOMETRO, 'Odômetro'), (NENHUMA, 'Nenhuma')]


def _caminho_midia(instancia, nome):
    agora = timezone.now()
    ext = (nome.rsplit('.', 1)[-1].lower() if '.' in nome else 'bin')[:5]
    return f'{agora:%Y/%m}/{uuid_lib.uuid4().hex}.{ext}'


# ── Cadastros ──────────────────────────────────────────────────────────────────
class Unidade(models.Model):
    sigla = models.CharField(max_length=20, unique=True)
    nome = models.CharField(max_length=120)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['sigla']

    def __str__(self):
        return self.sigla


class Setor(models.Model):
    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name='setores')
    codigo = models.CharField(max_length=20)
    nome = models.CharField(max_length=120)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['unidade__sigla', 'nome']
        unique_together = [('unidade', 'codigo')]

    def __str__(self):
        return f'{self.unidade.sigla} · {self.nome}'


class PerfilUsuario(models.Model):
    """Dados do usuário no módulo. Os PERFIS são grupos do Django (ver permissions.py)."""
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil_vistoria')
    cargo = models.CharField(max_length=120, blank=True, default='')
    unidades = models.ManyToManyField(Unidade, blank=True, related_name='+',
                                      help_text='Vazio = todas as unidades')
    atualizado_em = models.DateTimeField(auto_now=True)


class Ficha(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    descricao = models.CharField(max_length=300, blank=True, default='')
    ativa = models.BooleanField(default=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome

    def versao_atual(self):
        return self.versoes.order_by('-numero').first()


class FichaVersao(models.Model):
    """Toda alteração gera uma versão nova; as questões antigas ficam onde estavam."""
    ficha = models.ForeignKey(Ficha, on_delete=models.PROTECT, related_name='versoes')
    numero = models.PositiveIntegerField()
    vigente_desde = models.DateTimeField(default=timezone.now)
    observacao = models.CharField(max_length=300, blank=True, default='')
    criada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['ficha', '-numero']
        unique_together = [('ficha', 'numero')]

    def __str__(self):
        return f'{self.ficha.nome} v{self.numero}'


class Questao(models.Model):
    versao = models.ForeignKey(FichaVersao, on_delete=models.PROTECT, related_name='questoes')
    codigo = models.CharField(max_length=12)
    grupo = models.CharField(max_length=80)
    descricao = models.CharField(max_length=300)
    criticidade = models.CharField(max_length=8, choices=CRITICIDADES)
    permite_na = models.BooleanField(default=True)
    permite_abono = models.BooleanField(default=False, help_text='Só NC estética de funilaria e pintura')
    ordem = models.PositiveIntegerField(default=0)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['versao', 'ordem', 'id']


class TipoEquipamento(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    descricao = models.CharField(max_length=120)
    ficha = models.ForeignKey(Ficha, on_delete=models.PROTECT, related_name='tipos')
    medicao = models.CharField(max_length=10, choices=MEDICOES, default=HORIMETRO)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['descricao']

    def __str__(self):
        return self.descricao


class Equipamento(models.Model):
    tag = models.CharField(max_length=30, unique=True)
    descricao = models.CharField(max_length=160)
    tipo = models.ForeignKey(TipoEquipamento, on_delete=models.PROTECT, related_name='equipamentos')
    marca_modelo = models.CharField(max_length=120, blank=True, default='')
    placa = models.CharField(max_length=10, blank=True, default='')
    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name='equipamentos')
    setor = models.ForeignKey(Setor, on_delete=models.PROTECT, related_name='equipamentos')
    gerente = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='equipamentos_vistoria')
    periodicidade = models.CharField(max_length=10, choices=PERIODICIDADES, default=MENSAL)
    ativo = models.BooleanField(default=True)
    # Informativa: não suspende, não libera e não mexe no Indicador (9.4). PCM ou GEO marcam.
    em_manutencao = models.BooleanField(default=False)
    sga_codigo = models.PositiveIntegerField(null=True, blank=True, help_text='EQPCOD do SGA, quando importado de lá')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['tag']

    def __str__(self):
        return self.tag


class VinculoEquipamento(models.Model):
    """Fotografia do vínculo a partir de ``desde``. A linha mais recente com desde <= data vale para a data."""
    equipamento = models.ForeignKey(Equipamento, on_delete=models.CASCADE, related_name='vinculos')
    desde = models.DateTimeField(default=timezone.now)
    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name='+')
    setor = models.ForeignKey(Setor, on_delete=models.PROTECT, related_name='+')
    gerente = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    tipo = models.ForeignKey(TipoEquipamento, on_delete=models.PROTECT, related_name='+')
    periodicidade = models.CharField(max_length=10, choices=PERIODICIDADES)
    ativo = models.BooleanField(default=True)
    alterado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['equipamento', '-desde', '-id']


class DestinatarioNotificacao(models.Model):
    """E-mails do GEO, SESMT e PCM por unidade (vazio = todas). O gerente vem do equipamento."""
    GEO, SESMT, PCM, OUTRO = 'GEO', 'SESMT', 'PCM', 'OUTRO'
    PAPEIS = [(GEO, 'Gerente Executivo Operacional'), (SESMT, 'SESMT'), (PCM, 'PCM'), (OUTRO, 'Outro')]
    unidade = models.ForeignKey(Unidade, on_delete=models.CASCADE, null=True, blank=True, related_name='destinatarios')
    papel = models.CharField(max_length=6, choices=PAPEIS)
    nome = models.CharField(max_length=120, blank=True, default='')
    email = models.EmailField()
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['unidade__sigla', 'papel', 'nome']


# ── Programa ───────────────────────────────────────────────────────────────────
class ProgramaItem(models.Model):
    """Uma vistoria prevista (equipamento × mês). Situação P/R/V/A/I é calculada, não guardada."""
    PROGRAMADA, DISPENSADA, REPROGRAMADA, CANCELADA = 'PROGRAMADA', 'DISPENSADA', 'REPROGRAMADA', 'CANCELADA'
    SITUACOES = [(PROGRAMADA, 'Programada'), (DISPENSADA, 'Dispensada'),
                 (REPROGRAMADA, 'Reprogramada'), (CANCELADA, 'Cancelada')]
    equipamento = models.ForeignKey(Equipamento, on_delete=models.CASCADE, related_name='programa')
    ano = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    situacao = models.CharField(max_length=12, choices=SITUACOES, default=PROGRAMADA)
    justificativa = models.CharField(max_length=500, blank=True, default='')
    decidido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    decidido_em = models.DateTimeField(null=True, blank=True)
    origem = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='reprogramacoes')
    manual = models.BooleanField(default=False, help_text='Incluído à mão pelo GEO (fora do ciclo)')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['ano', 'mes', 'equipamento__tag']
        indexes = [models.Index(fields=['ano', 'mes']), models.Index(fields=['equipamento', 'ano'])]


class Impedimento(models.Model):
    PENDENTE, DISPENSADA, REPROGRAMADA, MANTIDA = 'PENDENTE', 'DISPENSADA', 'REPROGRAMADA', 'MANTIDA'
    DECISOES = [(PENDENTE, 'Aguardando decisão'), (DISPENSADA, 'Vistoria dispensada'),
                (REPROGRAMADA, 'Vistoria reprogramada'), (MANTIDA, 'Vistoria mantida')]
    item = models.ForeignKey(ProgramaItem, on_delete=models.CASCADE, related_name='impedimentos')
    motivo = models.CharField(max_length=500)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    registrado_em = models.DateTimeField(auto_now_add=True)
    decisao = models.CharField(max_length=12, choices=DECISOES, default=PENDENTE)
    decidido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    decidido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-registrado_em']


# ── Vistoria ───────────────────────────────────────────────────────────────────
class Vistoria(models.Model):
    ANDAMENTO, CONCLUIDA, VALIDADA = 'ANDAMENTO', 'CONCLUIDA', 'VALIDADA'
    STATUS = [(ANDAMENTO, 'Em andamento'), (CONCLUIDA, 'Aguardando validação'), (VALIDADA, 'Validada')]
    PROGRAMADA, EXTRAORDINARIA = 'PROGRAMADA', 'EXTRAORDINARIA'
    TIPOS = [(PROGRAMADA, 'Programada'), (EXTRAORDINARIA, 'Extraordinária')]

    uuid = models.UUIDField(unique=True, default=uuid_lib.uuid4)
    equipamento = models.ForeignKey(Equipamento, on_delete=models.PROTECT, related_name='vistorias')
    item = models.ForeignKey(ProgramaItem, on_delete=models.PROTECT, null=True, blank=True, related_name='vistorias')
    tipo = models.CharField(max_length=15, choices=TIPOS, default=PROGRAMADA)
    motivo_extraordinaria = models.CharField(max_length=300, blank=True, default='')
    ficha_versao = models.ForeignKey(FichaVersao, on_delete=models.PROTECT, related_name='vistorias')
    # vínculo do dia (3.4): não muda se o cadastro mudar depois
    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name='+')
    setor = models.ForeignKey(Setor, on_delete=models.PROTECT, related_name='+')
    gerente = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    avaliador = models.ForeignKey(User, on_delete=models.PROTECT, related_name='vistorias_avaliadas')
    iniciada_em = models.DateTimeField(default=timezone.now)
    concluida_em = models.DateTimeField(null=True, blank=True)
    medicao_tipo = models.CharField(max_length=10, choices=MEDICOES, default=NENHUMA)
    medicao = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True)
    medicao_anterior = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True)
    medicao_menor_confirmada = models.BooleanField(default=False)
    acompanhante_nome = models.CharField(max_length=120, blank=True, default='')
    acompanhante_cargo = models.CharField(max_length=120, blank=True, default='')
    observacoes = models.TextField(blank=True, default='')
    status = models.CharField(max_length=10, choices=STATUS, default=ANDAMENTO)
    resultado_inicial = models.CharField(max_length=1, choices=RESULTADOS, blank=True, default='')
    resultado_final = models.CharField(max_length=1, choices=RESULTADOS, blank=True, default='')
    validada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    validada_em = models.DateTimeField(null=True, blank=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-iniciada_em']
        indexes = [models.Index(fields=['equipamento', 'concluida_em']), models.Index(fields=['status'])]

    def __str__(self):
        return f'{self.equipamento.tag} {self.iniciada_em:%d/%m/%Y}'

    @property
    def realizada_em(self):
        """Data que conta para o mês: a da conclusão (a vistoria atrasada "passa a valer a partir de então")."""
        return self.concluida_em

    @property
    def resultado_vigente(self):
        return self.resultado_final or self.resultado_inicial


class Resposta(models.Model):
    """Cópia da questão no momento da execução + a resposta. NC é a própria Resposta com valor NC."""
    C, NC, NA = 'C', 'NC', 'NA'
    VALORES = [(C, 'Conforme'), (NC, 'Não conforme'), (NA, 'Não aplicável')]

    vistoria = models.ForeignKey(Vistoria, on_delete=models.PROTECT, related_name='respostas')
    questao = models.ForeignKey(Questao, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    codigo = models.CharField(max_length=12)
    grupo = models.CharField(max_length=80)
    descricao = models.CharField(max_length=300)
    criticidade = models.CharField(max_length=8, choices=CRITICIDADES)
    permite_na = models.BooleanField(default=True)
    permite_abono = models.BooleanField(default=False)
    ordem = models.PositiveIntegerField(default=0)

    valor = models.CharField(max_length=2, choices=VALORES, blank=True, default='')
    descricao_problema = models.TextField(blank=True, default='')
    respondida_em = models.DateTimeField(null=True, blank=True)
    # NC crítica confirmada: já suspendeu e mandou e-mail — o avaliador não muda mais.
    critica_confirmada_em = models.DateTimeField(null=True, blank=True)
    cancelada = models.BooleanField(default=False)
    cancelamento_justificativa = models.CharField(max_length=500, blank=True, default='')
    cancelada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cancelada_em = models.DateTimeField(null=True, blank=True)
    abonada = models.BooleanField(default=False)
    abono_justificativa = models.CharField(max_length=500, blank=True, default='')
    abonada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    abonada_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['vistoria', 'ordem', 'id']
        unique_together = [('vistoria', 'codigo')]

    @property
    def travada(self):
        return self.critica_confirmada_em is not None and not self.cancelada


class Evidencia(models.Model):
    """Foto ou vídeo de uma NC (ou do adesivo / da correção). ``uuid`` vem do aparelho: reenvio não duplica."""
    FOTO, VIDEO = 'FOTO', 'VIDEO'
    TIPOS = [(FOTO, 'Foto'), (VIDEO, 'Vídeo')]
    NC, ADESIVO, CORRECAO = 'NC', 'ADESIVO', 'CORRECAO'
    FINALIDADES = [(NC, 'Não conformidade'), (ADESIVO, 'Adesivo de operação suspensa'), (CORRECAO, 'Correção')]

    uuid = models.UUIDField(unique=True, default=uuid_lib.uuid4)
    finalidade = models.CharField(max_length=10, choices=FINALIDADES, default=NC)
    vistoria = models.ForeignKey(Vistoria, on_delete=models.PROTECT, null=True, blank=True, related_name='evidencias')
    resposta = models.ForeignKey(Resposta, on_delete=models.PROTECT, null=True, blank=True, related_name='evidencias')
    suspensao = models.ForeignKey('Suspensao', on_delete=models.PROTECT, null=True, blank=True, related_name='evidencias')
    nc_critica = models.ForeignKey('NCCritica', on_delete=models.PROTECT, null=True, blank=True, related_name='evidencias')
    tipo = models.CharField(max_length=5, choices=TIPOS, default=FOTO)
    arquivo = models.FileField(upload_to=_caminho_midia, storage=PRIVADO)
    content_type = models.CharField(max_length=60, default='image/jpeg')
    tamanho = models.PositiveIntegerField(default=0)
    enviada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['criada_em']


class Devolucao(models.Model):
    """GEO devolve ao avaliador por erro de preenchimento (TAG, horímetro…)."""
    vistoria = models.ForeignKey(Vistoria, on_delete=models.CASCADE, related_name='devolucoes')
    justificativa = models.CharField(max_length=500)
    devolvida_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    devolvida_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-devolvida_em']


# ── Suspensão e liberação ──────────────────────────────────────────────────────
class Suspensao(models.Model):
    SUSPENSA, AGUARDANDO, LIBERADA, CANCELADA = 'SUSPENSA', 'AGUARDANDO', 'LIBERADA', 'CANCELADA'
    STATUS = [(SUSPENSA, 'Operação suspensa'), (AGUARDANDO, 'Aguardando liberação'),
              (LIBERADA, 'Liberada'), (CANCELADA, 'Cancelada')]
    ADESIVO_PENDENTE, ADESIVO_AFIXADO, ADESIVO_NAO = 'PENDENTE', 'AFIXADO', 'NAO_AFIXADO'
    ADESIVO = [(ADESIVO_PENDENTE, 'Não informado'), (ADESIVO_AFIXADO, 'Afixado'), (ADESIVO_NAO, 'Não foi possível afixar')]

    equipamento = models.ForeignKey(Equipamento, on_delete=models.PROTECT, related_name='suspensoes')
    vistoria = models.ForeignKey(Vistoria, on_delete=models.PROTECT, related_name='suspensoes')
    status = models.CharField(max_length=10, choices=STATUS, default=SUSPENSA)
    iniciada_em = models.DateTimeField(default=timezone.now)
    adesivo = models.CharField(max_length=12, choices=ADESIVO, default=ADESIVO_PENDENTE)
    adesivo_em = models.DateTimeField(null=True, blank=True)
    adesivo_justificativa = models.CharField(max_length=500, blank=True, default='')
    liberada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    liberada_em = models.DateTimeField(null=True, blank=True)
    liberacao_observacao = models.CharField(max_length=500, blank=True, default='')
    encerrada_em = models.DateTimeField(null=True, blank=True, help_text='Liberação ou cancelamento')

    class Meta:
        ordering = ['-iniciada_em']

    @property
    def aberta(self):
        return self.status in (self.SUSPENSA, self.AGUARDANDO)


class NCCritica(models.Model):
    """Cada NC crítica da suspensão: o PCM corrige, o SESMT/GEO valida. Todas validadas → libera."""
    PENDENTE, CORRIGIDA, VALIDADA, CANCELADA = 'PENDENTE', 'CORRIGIDA', 'VALIDADA', 'CANCELADA'
    STATUS = [(PENDENTE, 'Aguardando correção'), (CORRIGIDA, 'Correção registrada'),
              (VALIDADA, 'Correção validada'), (CANCELADA, 'NC cancelada')]
    suspensao = models.ForeignKey(Suspensao, on_delete=models.PROTECT, related_name='ncs')
    resposta = models.OneToOneField(Resposta, on_delete=models.PROTECT, related_name='nc_critica')
    status = models.CharField(max_length=10, choices=STATUS, default=PENDENTE)
    correcao = models.TextField(blank=True, default='')
    corrigida_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    corrigida_em = models.DateTimeField(null=True, blank=True)
    validada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    validada_em = models.DateTimeField(null=True, blank=True)
    rejeicao = models.CharField(max_length=500, blank=True, default='', help_text='Última rejeição')
    rejeitada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    rejeitada_em = models.DateTimeField(null=True, blank=True)
    rejeicoes = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['suspensao', 'resposta__ordem']


class EmailVistoria(models.Model):
    """Registro de cada e-mail (suspensão, liberação, cancelamento, rejeição): prova de envio e reenvio."""
    SUSPENSAO, LIBERACAO, CANCELAMENTO, REJEICAO = 'SUSPENSAO', 'LIBERACAO', 'CANCELAMENTO', 'REJEICAO'
    TIPOS = [(SUSPENSAO, 'Suspensão'), (LIBERACAO, 'Liberação'), (CANCELAMENTO, 'Cancelamento de NC crítica'),
             (REJEICAO, 'Correção rejeitada')]
    tipo = models.CharField(max_length=12, choices=TIPOS)
    suspensao = models.ForeignKey(Suspensao, on_delete=models.CASCADE, related_name='emails')
    resposta = models.ForeignKey(Resposta, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    assunto = models.CharField(max_length=200)
    destinatarios = models.TextField(default='')
    criado_em = models.DateTimeField(auto_now_add=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    erro = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-criado_em']


# ── Resultados ────────────────────────────────────────────────────────────────
class FechamentoMensal(models.Model):
    FECHADO, REABERTO = 'FECHADO', 'REABERTO'
    ano = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=8, default=FECHADO)
    fechado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    fechado_em = models.DateTimeField(default=timezone.now)
    reaberto_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reaberto_em = models.DateTimeField(null=True, blank=True)
    justificativa_reabertura = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        ordering = ['-ano', '-mes']
        unique_together = [('ano', 'mes')]


class ResultadoMensal(models.Model):
    """Congelado no fechamento. Reabrir não apaga: as linhas antigas ficam com ``vigente=False``."""
    S, I, C, NR, D = 'S', 'I', 'C', 'NR', 'D'
    fechamento = models.ForeignKey(FechamentoMensal, on_delete=models.PROTECT, related_name='resultados')
    vigente = models.BooleanField(default=True)
    ano = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    equipamento = models.ForeignKey(Equipamento, on_delete=models.PROTECT, related_name='resultados')
    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name='+')
    setor = models.ForeignKey(Setor, on_delete=models.PROTECT, related_name='+')
    gerente = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    tipo = models.ForeignKey(TipoEquipamento, on_delete=models.PROTECT, related_name='+')
    periodicidade = models.CharField(max_length=10, choices=PERIODICIDADES)
    resultado = models.CharField(max_length=2)
    herdado = models.BooleanField(default=False)
    suspenso = models.BooleanField(default=False)
    sem_validacao = models.BooleanField(default=False)
    vistoria = models.ForeignKey(Vistoria, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    item = models.ForeignKey(ProgramaItem, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    considerado = models.BooleanField(default=True)
    satisfatorio = models.BooleanField(default=False)

    class Meta:
        ordering = ['ano', 'mes', 'equipamento__tag']
        indexes = [models.Index(fields=['ano', 'mes', 'vigente'])]


class FechamentoTrimestral(models.Model):
    ano = models.PositiveSmallIntegerField()
    trimestre = models.PositiveSmallIntegerField()
    fechado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    fechado_em = models.DateTimeField(default=timezone.now)
    indicador = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    resumo = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-ano', '-trimestre']
        unique_together = [('ano', 'trimestre')]


class Auditoria(models.Model):
    """Trilha (13): criação, alteração, validação, abono, dispensa, cancelamento, liberação, fechamento…"""
    quando = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    acao = models.CharField(max_length=40)
    objeto = models.CharField(max_length=40, blank=True, default='')
    objeto_id = models.CharField(max_length=40, blank=True, default='')
    descricao = models.CharField(max_length=300, blank=True, default='')
    dados = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-quando']
        indexes = [models.Index(fields=['objeto', 'objeto_id'])]
