from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
# Create your models here.
class DocumentoAnexo(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name='despesas_documentoanexo_set')
    object_id = models.PositiveIntegerField()
    documento = GenericForeignKey('content_type', 'object_id')
    arquivo = models.FileField(upload_to='anexos/')
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
    id = models.AutoField(primary_key=True)
    colaborador = models.CharField(max_length=455, null=False, blank=False)
    tipo = models.CharField(max_length=455, null=False, blank=False)
    data = models.DateField(null=False, blank=False)
    valor = models.FloatField(null=False, blank=False)
    anexo = models.ImageField(upload_to='anexos/', null=True, blank=True)
    anexos = GenericRelation('DocumentoAnexo', related_query_name='despesa')
    created_at = models.DateTimeField(auto_now_add=True)
    lancada = models.BooleanField(default=False)
    reembolsavel = models.BooleanField(default=False)
    class Meta:
        verbose_name = 'Despesa'
        verbose_name_plural = 'Despesas'

