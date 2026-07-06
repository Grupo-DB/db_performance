from django.db import models
from django.contrib.auth.models import User


class Fila(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    descricao = models.CharField(max_length=255, blank=True)
    ativa = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0, help_text='Posição no menu numérico enviado ao cliente')
    palavras_chave = models.CharField(
        max_length=255, blank=True,
        help_text='Termos separados por vírgula usados no roteamento automático (ex: compra,comprar,fornecedor)'
    )
    is_padrao = models.BooleanField(default=False, help_text='Fila de fallback quando não é possível identificar o setor')
    membros = models.ManyToManyField(User, related_name='filas_whatsapp', blank=True)
    criado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='filas_whatsapp_criadas')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fila'
        verbose_name_plural = 'Filas'
        ordering = ['ordem', 'nome']

    def __str__(self):
        return self.nome


class Conversa(models.Model):
    STATUS_CHOICES = [
        ('ABERTA', 'Aberta'),
        ('ENCERRADA', 'Encerrada'),
    ]
    ESTADO_MENU_CHOICES = [
        ('AGUARDANDO_SETOR', 'Aguardando escolha de setor'),
        ('EM_ATENDIMENTO', 'Em atendimento'),
    ]

    contato_telefone = models.CharField(max_length=30, db_index=True)
    contato_nome = models.CharField(max_length=150, blank=True)
    numero_negocio_id = models.CharField(max_length=50, blank=True, help_text='phone_number_id do Meta que recebeu a mensagem')
    fila = models.ForeignKey(Fila, on_delete=models.SET_NULL, null=True, blank=True, related_name='conversas')
    responsavel = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conversas_whatsapp_responsavel'
    )  # opcional — qualquer membro da fila pode assumir/liberar
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ABERTA')
    estado_menu = models.CharField(max_length=20, choices=ESTADO_MENU_CHOICES, default='AGUARDANDO_SETOR')
    tentativas_menu = models.PositiveSmallIntegerField(default=0)
    ultima_mensagem_em = models.DateTimeField(null=True, blank=True, db_index=True)
    ultima_mensagem_cliente_em = models.DateTimeField(null=True, blank=True, help_text='Base do cálculo da janela de 24h do WhatsApp')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Conversa'
        verbose_name_plural = 'Conversas'
        ordering = ['-ultima_mensagem_em']
        indexes = [
            models.Index(fields=['fila', 'status']),
            models.Index(fields=['responsavel', 'status']),
        ]

    def __str__(self):
        return f"{self.contato_nome or self.contato_telefone} ({self.get_status_display()})"

    @property
    def dentro_da_janela_24h(self):
        if not self.ultima_mensagem_cliente_em:
            return False
        from django.utils import timezone
        return (timezone.now() - self.ultima_mensagem_cliente_em).total_seconds() < 24 * 3600


class Mensagem(models.Model):
    DIRECAO_CHOICES = [
        ('ENTRADA', 'Entrada'),
        ('SAIDA', 'Saída'),
    ]
    TIPO_CHOICES = [
        ('TEXTO', 'Texto'),
        ('IMAGEM', 'Imagem'),
        ('DOCUMENTO', 'Documento'),
        ('AUDIO', 'Áudio'),
        ('VIDEO', 'Vídeo'),
    ]
    STATUS_ENTREGA_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('ENVIADA', 'Enviada'),
        ('ENTREGUE', 'Entregue'),
        ('LIDA', 'Lida'),
        ('FALHOU', 'Falhou'),
    ]

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='mensagens')
    direcao = models.CharField(max_length=10, choices=DIRECAO_CHOICES)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='TEXTO')
    texto = models.TextField(blank=True)
    autor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='mensagens_whatsapp_enviadas')
    wa_message_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    status_entrega = models.CharField(max_length=10, choices=STATUS_ENTREGA_CHOICES, default='PENDENTE')
    erro_detalhe = models.TextField(blank=True)
    payload_bruto = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Mensagem'
        verbose_name_plural = 'Mensagens'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversa', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.direcao}] {self.conversa} - {self.created_at:%d/%m/%Y %H:%M}"


class MensagemAnexo(models.Model):
    mensagem = models.ForeignKey(Mensagem, on_delete=models.CASCADE, related_name='anexos')
    arquivo = models.FileField(upload_to='whatsapp/anexos/%Y/%m/')
    nome_original = models.CharField(max_length=255, blank=True)
    tamanho = models.PositiveIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    wa_media_id = models.CharField(max_length=100, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.arquivo and not self.nome_original:
            self.nome_original = self.arquivo.name
        if self.arquivo and not self.tamanho:
            self.tamanho = self.arquivo.size
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome_original or f"Anexo {self.pk}"


class WhatsAppNotificacao(models.Model):
    TIPO_CHOICES = [
        ('NOVA_MENSAGEM', 'Nova Mensagem'),
        ('CONVERSA_ATRIBUIDA', 'Conversa Atribuída'),
        ('CONVERSA_TRANSFERIDA', 'Conversa Transferida'),
    ]

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='notificacoes')
    usuario_notificado = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notificacoes_whatsapp')
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    mensagem = models.CharField(max_length=255)
    lido = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Notificação de WhatsApp'
        verbose_name_plural = 'Notificações de WhatsApp'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['usuario_notificado', '-created_at']),
            models.Index(fields=['usuario_notificado', 'lido']),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.conversa}"
