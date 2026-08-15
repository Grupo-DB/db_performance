from django.contrib import admin

from .models import (
    ConfiguracaoAtendimento, Fila, Conversa, Mensagem, MensagemAnexo, WhatsAppNotificacao,
)


@admin.register(ConfiguracaoAtendimento)
class ConfiguracaoAtendimentoAdmin(admin.ModelAdmin):
    """
    Tela única dos textos automáticos — sem lista, sem "adicionar", sem "excluir".

    O `changelist` redireciona direto para o formulário do registro 1: uma lista
    com uma linha só não ajuda ninguém, e a entrada do menu passa a abrir o que a
    pessoa veio editar.
    """
    readonly_fields = ('atualizado_em', 'atualizado_por')
    fieldsets = (
        ('Menu de setores', {
            'fields': ('texto_menu',),
            'description': 'Os setores saem numerados abaixo desta linha, na ordem definida em Filas.',
        }),
        ('Confirmação de setor', {
            'fields': ('texto_roteamento',),
            'description': 'Escreva <code>{setor}</code> onde o nome do setor deve entrar.',
        }),
        ('Assinatura das respostas', {
            'fields': ('assinatura',),
            'description': 'Vai na frente de toda resposta do atendente. É a mesma para todos '
                           'os atendentes — o cliente fala com a empresa, não com uma pessoa. '
                           'Em branco não assina.',
        }),
        ('Última alteração', {'fields': ('atualizado_em', 'atualizado_por')}),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.shortcuts import redirect
        from django.urls import reverse

        config = ConfiguracaoAtendimento.carregar()
        return redirect(reverse('admin:whatsapp_configuracaoatendimento_change', args=[config.pk]))

    def save_model(self, request, obj, form, change):
        obj.atualizado_por = request.user
        super().save_model(request, obj, form, change)


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
