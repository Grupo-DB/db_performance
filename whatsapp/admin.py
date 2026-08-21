from django.contrib import admin

from .models import (
    ConfiguracaoAtendimento, Contato, Fila, Conversa, Mensagem, MensagemAnexo,
    NumeroNegocio, WhatsAppNotificacao,
)


@admin.register(ConfiguracaoAtendimento)
class ConfiguracaoAtendimentoAdmin(admin.ModelAdmin):
    """
    Textos automáticos: um conjunto por número, mais o geral.

    Era tela única (um registro só) e o changelist redirecionava para ele. Com o
    segundo número deixou de ser: cada setor precisa do seu menu e da sua
    assinatura, então voltou a ser lista, e "adicionar" voltou a existir. A linha
    de número em branco é a geral, usada por quem não tem a sua.
    """
    list_display = ('rotulo', 'assinatura', 'atualizado_em')
    readonly_fields = ('atualizado_em', 'atualizado_por')

    @admin.display(description='Aplica-se a')
    def rotulo(self, obj):
        return obj.numero.nome if obj.numero_id else 'Geral (todos os números)'
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
        ('Número', {
            'fields': ('numero',),
            'description': 'Em branco = configuração geral. Preencha para dar textos '
                           'próprios a um número (é o que separa um setor do outro).',
        }),
        ('Última alteração', {'fields': ('atualizado_em', 'atualizado_por')}),
    )

    def save_model(self, request, obj, form, change):
        obj.atualizado_por = request.user
        super().save_model(request, obj, form, change)


@admin.register(NumeroNegocio)
class NumeroNegocioAdmin(admin.ModelAdmin):
    list_display = ('nome', 'telefone', 'phone_number_id', 'ativo', 'is_padrao',
                    'menu_automatico')
    list_filter = ('ativo', 'is_padrao')
    search_fields = ('nome', 'telefone', 'phone_number_id')
    fieldsets = (
        (None, {'fields': ('nome', 'telefone', 'phone_number_id', 'ativo', 'is_padrao')}),
        ('Comportamento do robô', {
            'fields': ('menu_automatico',),
            'description': 'Número que também é atendido no app do celular precisa disto '
                           'DESLIGADO, senão o robô responde por cima da pessoa.',
        }),
        ('Só se o número estiver em OUTRA WABA', {
            'fields': ('waba_id', 'access_token'),
            'classes': ('collapse',),
            'description': 'Deixe em branco quando o número está na mesma conta do .env — '
                           'é o caso normal. O token guarda um retrato dos ativos de quando '
                           'foi gerado, então WABA nova exige token novo.',
        }),
    )


@admin.register(Contato)
class ContatoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'telefone', 'empresa', 'ativo', 'criado_por', 'criado_em')
    list_filter = ('ativo', 'empresa')
    search_fields = ('nome', 'telefone', 'empresa')


@admin.register(Fila)
class FilaAdmin(admin.ModelAdmin):
    # `numero` na lista porque é ele que decide em qual menu a fila aparece:
    # fila do RH pendurada no número do TI entra no menu errado, e isso não se vê
    # abrindo a lista se a coluna não estiver aqui. Em branco = fila dos dois.
    list_display = ('nome', 'numero', 'ativa', 'ordem', 'is_padrao', 'criado_em')
    list_filter = ('ativa', 'is_padrao', 'numero')
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
