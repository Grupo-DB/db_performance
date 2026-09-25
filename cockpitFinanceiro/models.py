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


class UsuarioCockpit(models.Model):
    """Acesso individual ao Cockpit (substituiu a senha única em 25/09/2026).

    Criado por `python manage.py cockpit_usuario criar ...` com senha provisória; no primeiro
    acesso a pessoa é obrigada a trocar. `versao` sobe a cada troca/reset e invalida as sessões
    abertas daquele usuário (o cookie carrega a versão)."""
    PERFIL_LEITURA = 'leitura'
    PERFIL_EDICAO = 'edicao'
    PERFIS = [(PERFIL_LEITURA, 'Só leitura'), (PERFIL_EDICAO, 'Edição (planilha e anexos)')]

    login = models.CharField(max_length=60, unique=True, help_text='minúsculas, sem espaço')
    nome = models.CharField(max_length=120)
    senha_hash = models.CharField(max_length=255)
    perfil = models.CharField(max_length=10, choices=PERFIS, default=PERFIL_LEITURA)
    # Pode subir uma versão nova da página (HTML baixado do artifact). O HTML roda com o
    # acesso de todo mundo que abre o painel — só para quem é de confiança.
    pode_publicar = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)
    trocar_senha = models.BooleanField(default=True)
    versao = models.PositiveIntegerField(default=1)
    ultimo_acesso = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Usuário do Cockpit Financeiro'
        verbose_name_plural = 'Usuários do Cockpit Financeiro'
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} ({self.login})'

    @property
    def pode_editar(self):
        return self.perfil == self.PERFIL_EDICAO


class ConfiguracaoCockpit(models.Model):
    """Da época da senha única (até 25/09/2026). Não é mais lida no login; fica para não
    quebrar a migration 0001 já aplicada."""
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


class VersaoPainel(models.Model):
    """Versões do HTML do painel, publicadas pela tela /financeiro/publicar.

    A página servida é a versão `ativa`; sem nenhuma, vale o arquivo pagina/cockpit.html.
    Guardado no banco (TextField = LONGTEXT no MySQL) para não depender de acesso ao disco
    do servidor e para poder voltar a qualquer versão anterior."""
    html = models.TextField()
    nome_arquivo = models.CharField(max_length=255, blank=True, default='')
    tamanho = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    observacao = models.CharField(max_length=255, blank=True, default='')
    enviado_por = models.CharField(max_length=120, blank=True, default='')
    enviado_em = models.DateTimeField(auto_now_add=True)
    ativa = models.BooleanField(default=False)
    ativada_em = models.DateTimeField(null=True, blank=True)
    ativada_por = models.CharField(max_length=120, blank=True, default='')

    class Meta:
        ordering = ['-enviado_em']
        verbose_name = 'Versão do painel'
        verbose_name_plural = 'Versões do painel'
