from django.contrib import admin

from .models import Fila, Conversa, Mensagem, MensagemAnexo, WhatsAppNotificacao


@admin.register(Fila)
class FilaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ativa', 'ordem', 'is_padrao', 'criado_em')
    list_filter = ('ativa', 'is_padrao')
    search_fields = ('nome', 'palavras_chave')
    ordering = ('ordem', 'nome')


@admin.register(Conversa)
class ConversaAdmin(admin.ModelAdmin):
    list_display = ('contato_nome', 'contato_telefone', 'fila', 'responsavel', 'status', 'estado_menu', 'ultima_mensagem_em')
    list_filter = ('status', 'estado_menu', 'fila')
    search_fields = ('contato_nome', 'contato_telefone')
    ordering = ('-ultima_mensagem_em',)


@admin.register(Mensagem)
class MensagemAdmin(admin.ModelAdmin):
    list_display = ('conversa', 'direcao', 'tipo', 'status_entrega', 'created_at')
    list_filter = ('direcao', 'tipo', 'status_entrega')
    search_fields = ('texto', 'wa_message_id', 'conversa__contato_telefone')
    ordering = ('-created_at',)
    readonly_fields = ('payload_bruto',)


@admin.register(MensagemAnexo)
class MensagemAnexoAdmin(admin.ModelAdmin):
    list_display = ('nome_original', 'mensagem', 'mime_type', 'tamanho', 'criado_em')


@admin.register(WhatsAppNotificacao)
class WhatsAppNotificacaoAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'conversa', 'usuario_notificado', 'lido', 'created_at')
    list_filter = ('tipo', 'lido')
    ordering = ('-created_at',)
