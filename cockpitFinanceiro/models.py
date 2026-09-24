"""
Cockpit Financeiro — dashboard feito como artifact do Claude e hospedado aqui para ser
aberto por quem não tem assinatura (acesso por senha única compartilhada).

O HTML original conversa com o runtime do Claude (`claude.use('db' | 'assets' | 'user' |
'downloads')`). `static_src/claude-shim.js` imita essa interface e grava nestes modelos, para
o HTML do artifact poder ser trocado por uma versão nova sem reescrever nada.
"""
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
import os

# Fora do MEDIA_ROOT de propósito: /media/ é servido direto pelo nginx, sem login, e aqui
# os anexos são extratos e relatórios financeiros.
armazenamento_privado = FileSystemStorage(
    location=os.path.join(settings.BASE_DIR, 'privado', 'cockpit_financeiro'),
)


class ConfiguracaoCockpit(models.Model):
    """Linha única. Trocar a senha incrementa `versao_senha` e derruba quem estava logado."""
    senha_hash = models.CharField(max_length=255, blank=True, default='')
    versao_senha = models.PositiveIntegerField(default=1)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração do Cockpit Financeiro'

    @classmethod
    def atual(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class DocumentoCockpit(models.Model):
    """Equivalente a um documento do `db` do artifact: coleção + id + JSON."""
    colecao = models.CharField(max_length=64)
    doc_id = models.CharField(max_length=64)
    dados = models.JSONField(default=dict)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.CharField(max_length=120, blank=True, default='')

    class Meta:
        unique_together = ('colecao', 'doc_id')
        indexes = [models.Index(fields=['colecao'])]


class AnexoCockpit(models.Model):
    """Equivalente a um asset do artifact (PDF/imagem enviado numa aba)."""
    arquivo = models.FileField(storage=armazenamento_privado, upload_to='%Y/%m/')
    nome = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    tamanho = models.PositiveIntegerField(default=0)
    enviado_por = models.CharField(max_length=120, blank=True, default='')
    enviado_em = models.DateTimeField(auto_now_add=True)
