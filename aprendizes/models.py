"""Acompanhamento do período de experiência (planilha "AVALIAÇÃO PERÍODO DE EXPERIÊNCIA").

A planilha tinha uma aba por mês com NOME | TIPO | VENCIMENTO | SITUAÇÃO | OBSERVAÇÃO:
cada linha é uma ETAPA de uma pessoa (1º vencimento, prorrogação, efetivação). Aqui a
pessoa vira um ``Acompanhamento`` e as linhas viram ``Etapa`` — a tela mensal é só um
filtro por vencimento, e o histórico da pessoa fica junto.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from avaliacoes.management.models import Colaborador

# Contrato de experiência 30 + 60 dias: a prorrogação cai 60 dias depois do 1º
# vencimento (66 de 80 pares da planilha). Contados com o dia da admissão.
DIAS_PRIMEIRO_VENCIMENTO = 30
DIAS_PRORROGACAO = 90


class Acompanhamento(models.Model):
    EM_ANDAMENTO = 'EM_ANDAMENTO'
    EFETIVADO = 'EFETIVADO'
    DESLIGADO = 'DESLIGADO'
    AFASTADO = 'AFASTADO'
    SITUACOES = [
        (EM_ANDAMENTO, 'Em experiência'),
        (EFETIVADO, 'Efetivado (passou da experiência)'),
        (DESLIGADO, 'Desligado'),
        (AFASTADO, 'Afastado'),
    ]

    colaborador = models.ForeignKey(
        Colaborador, null=True, blank=True, on_delete=models.SET_NULL, related_name='acompanhamentos_experiencia',
    )
    # Cópia do cadastro no momento: a planilha tinha gente que não está (ou não está
    # mais) no cadastro de colaboradores, e o histórico não pode depender dele.
    nome = models.CharField(max_length=150)
    setor = models.CharField(max_length=150, blank=True, default='')
    cargo = models.CharField(max_length=150, blank=True, default='')
    data_admissao = models.DateField(null=True, blank=True)
    situacao = models.CharField(max_length=15, choices=SITUACOES, default=EM_ANDAMENTO)
    observacao = models.TextField(blank=True, default='')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_admissao', 'nome']

    def __str__(self):
        return self.nome

    def atualizar_situacao(self):
        """Situação da pessoa sai das etapas; afastado é a única marcada à mão."""
        if self.situacao == self.AFASTADO:
            return
        etapas = list(self.etapas.all())
        if any(e.situacao in (Etapa.DESLIGADO, Etapa.DISPENSADO) for e in etapas):
            nova = self.DESLIGADO
        elif any(e.tipo in (Etapa.PRORROGACAO, Etapa.EFETIVACAO) and e.situacao == Etapa.CONCLUIDO for e in etapas):
            # Passou da prorrogação: o contrato vira por prazo indeterminado. A etapa de
            # efetivação (que a planilha passou a usar em 2026) é um acompanhamento a mais.
            nova = self.EFETIVADO
        else:
            nova = self.EM_ANDAMENTO
        if nova != self.situacao:
            self.situacao = nova
            self.save(update_fields=['situacao', 'atualizado_em'])


class Etapa(models.Model):
    PRIMEIRO_VENCIMENTO = 'PRIMEIRO'
    PRORROGACAO = 'PRORROGACAO'
    EFETIVACAO = 'EFETIVACAO'
    ENCERRAMENTO = 'ENCERRAMENTO'
    TIPOS = [
        (PRIMEIRO_VENCIMENTO, '1º vencimento'),
        (PRORROGACAO, 'Prorrogação'),
        (EFETIVACAO, 'Efetivação'),
        (ENCERRAMENTO, 'Encerramento'),
    ]
    ORDEM_TIPO = {PRIMEIRO_VENCIMENTO: 1, PRORROGACAO: 2, EFETIVACAO: 3, ENCERRAMENTO: 4}

    PENDENTE = 'PENDENTE'
    CONCLUIDO = 'CONCLUIDO'
    DISPENSADO = 'DISPENSADO'    # a empresa não seguiu com a pessoa
    DESLIGADO = 'DESLIGADO'      # demitido, pediu demissão
    AFASTADO = 'AFASTADO'
    SITUACOES = [
        (PENDENTE, 'Pendente'),
        (CONCLUIDO, 'Concluído'),
        (DISPENSADO, 'Dispensado'),
        (DESLIGADO, 'Desligado / pediu demissão'),
        (AFASTADO, 'Em afastamento'),
    ]

    acompanhamento = models.ForeignKey(Acompanhamento, on_delete=models.CASCADE, related_name='etapas')
    tipo = models.CharField(max_length=15, choices=TIPOS)
    vencimento = models.DateField()
    situacao = models.CharField(max_length=12, choices=SITUACOES, default=PENDENTE)
    # O que a planilha controlava na coluna de observação ("Feedback ok - Falta brinde",
    # "CAMISETA OK", "Plano de saúde: INFORMADO") vira checklist.
    avaliacao_feita = models.BooleanField(default=False)
    feedback_dado = models.BooleanField(default=False)
    brinde_entregue = models.BooleanField(default=False)
    camiseta_entregue = models.BooleanField(default=False)
    plano_saude_informado = models.BooleanField(default=False)
    pendencia = models.CharField(max_length=200, blank=True, default='')
    observacao = models.TextField(blank=True, default='')
    concluido_em = models.DateTimeField(null=True, blank=True)
    concluido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )

    class Meta:
        ordering = ['vencimento', 'id']
        unique_together = ('acompanhamento', 'tipo')

    def __str__(self):
        return f'{self.acompanhamento} — {self.get_tipo_display()}'


class AvaliacaoJovemAprendiz(models.Model):
    """
    Avaliação do Programa Jovem Aprendiz: a do instrutor (INSTRUTOR) ou a autoavaliação (AUTO).
    Notas 1–4 por competência em ``notas`` ({chave: nota}); as chaves são as de ``jovem_aprendiz.CHAVES``.
    """
    INSTRUTOR, AUTO = 'INSTRUTOR', 'AUTO'
    TIPOS = [(INSTRUTOR, 'Avaliação do instrutor'), (AUTO, 'Autoavaliação')]
    EVOLUCOES = [('SIGNIFICATIVA', 'Sim, significativa'), ('MODERADA', 'Sim, moderada'),
                 ('POUCA', 'Pouca evolução'), ('NAO_PERCEBIDA', 'Ainda não foi possível perceber')]

    tipo = models.CharField(max_length=10, choices=TIPOS)
    colaborador = models.ForeignKey(Colaborador, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='avaliacoes_jovem_aprendiz')
    # Cópia no momento (o jovem pode não estar, ou deixar de estar, no cadastro).
    nome = models.CharField(max_length=150)
    setor = models.CharField(max_length=150, blank=True, default='')
    data = models.DateField()
    notas = models.JSONField(default=dict)
    respostas = models.JSONField(default=dict, blank=True)
    evolucao = models.CharField(max_length=15, choices=EVOLUCOES, blank=True, default='')
    competencia_prioritaria = models.CharField(max_length=30, blank=True, default='')
    avaliador = models.CharField(max_length=150, blank=True, default='', help_text='Quem avaliou (instrutor) ou o próprio jovem.')
    observacao = models.TextField(blank=True, default='')
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data', '-id']
        verbose_name = 'Avaliação do Jovem Aprendiz'
        verbose_name_plural = 'Avaliações do Jovem Aprendiz'

    def __str__(self):
        return f'{self.get_tipo_display()} — {self.nome} ({self.data:%d/%m/%Y})'


def _token_convite() -> str:
    return secrets.token_urlsafe(18)


def _expira_convite():
    return timezone.now() + timedelta(days=30)


class ConviteAutoavaliacao(models.Model):
    """
    Link para o próprio jovem responder a autoavaliação pelo celular, sem login.
    Uma resposta por link; vence em 30 dias; o RH pode cancelar.
    """
    token = models.CharField(max_length=40, unique=True, default=_token_convite, db_index=True)
    colaborador = models.ForeignKey(Colaborador, null=True, blank=True, on_delete=models.SET_NULL, related_name='convites_autoavaliacao')
    nome = models.CharField(max_length=150)
    setor = models.CharField(max_length=150, blank=True, default='')
    telefone = models.CharField(max_length=20, blank=True, default='')
    expira_em = models.DateTimeField(default=_expira_convite)
    cancelado = models.BooleanField(default=False)
    respondido_em = models.DateTimeField(null=True, blank=True)
    avaliacao = models.OneToOneField(AvaliacaoJovemAprendiz, null=True, blank=True, on_delete=models.SET_NULL, related_name='convite')
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

    @property
    def situacao(self) -> str:
        if self.respondido_em:
            return 'RESPONDIDO'
        if self.cancelado:
            return 'CANCELADO'
        if self.expira_em and self.expira_em < timezone.now():
            return 'VENCIDO'
        return 'ABERTO'
