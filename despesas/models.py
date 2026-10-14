from django.conf import settings
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation


class DocumentoAnexo(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name='despesas_documentoanexo_set')
    object_id = models.PositiveIntegerField()
    documento = GenericForeignKey('content_type', 'object_id')
    arquivo = models.FileField(upload_to='despesas/')
    nome_original = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = 'Anexo'
        verbose_name_plural = 'Anexos'
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
        ]


class Despesa(models.Model):
    """
    Despesa lançada por um colaborador, com comprovantes.

    Fluxo (14/10/2026): PENDENTE → APROVADA ou RECUSADA → LANCADA (no financeiro).
    Reembolso é independente do status: vale para despesa ``reembolsavel``
    (paga com dinheiro do próprio colaborador) já aprovada ou lançada.
    ``lancada`` continua existindo por compatibilidade e acompanha o status.
    """

    PENDENTE = 'PENDENTE'
    APROVADA = 'APROVADA'
    RECUSADA = 'RECUSADA'
    LANCADA = 'LANCADA'
    STATUS = [
        (PENDENTE, 'Pendente'),
        (APROVADA, 'Aprovada'),
        (RECUSADA, 'Recusada'),
        (LANCADA, 'Lançada'),
    ]

    id = models.AutoField(primary_key=True)
    colaborador = models.CharField(max_length=455, null=False, blank=False)
    # Dono da despesa. As antigas não têm (eram ligadas só pelo nome).
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='despesas')
    tipo = models.CharField(max_length=455, null=False, blank=False)
    # O que foi a despesa; obrigatória quando o tipo é "outros".
    descricao = models.TextField(blank=True, default='', db_default='')
    data = models.DateField(null=False, blank=False)
    valor = models.FloatField(null=False, blank=False)
    anexo = models.ImageField(upload_to='despesas/', null=True, blank=True)
    anexos = GenericRelation('DocumentoAnexo', related_query_name='despesa')
    created_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=20, choices=STATUS, default=PENDENTE, db_default=PENDENTE)
    lancada = models.BooleanField(default=False)
    reembolsavel = models.BooleanField(default=False)

    aprovado_por = models.CharField(max_length=255, blank=True, default='', db_default='')
    aprovado_em = models.DateTimeField(null=True, blank=True)
    motivo_recusa = models.TextField(blank=True, default='', db_default='')
    lancada_por = models.CharField(max_length=255, blank=True, default='', db_default='')
    lancada_em = models.DateTimeField(null=True, blank=True)

    reembolsada = models.BooleanField(default=False, db_default=False)
    reembolsada_em = models.DateField(null=True, blank=True)
    reembolsada_por = models.CharField(max_length=255, blank=True, default='', db_default='')

    class Meta:
        verbose_name = 'Despesa'
        verbose_name_plural = 'Despesas'
        ordering = ['-data', '-id']

    def save(self, *args, **kwargs):
        self.lancada = self.status == self.LANCADA
        super().save(*args, **kwargs)
