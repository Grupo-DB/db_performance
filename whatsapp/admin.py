from django.contrib import admin

from .models import (
    ConfiguracaoAtendimento, Contato, Disparo, DisparoDestinatario, Fila, Conversa,
    Mensagem, MensagemAnexo, NumeroNegocio, WhatsAppNotificacao,
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
        ('Saudação automática', {
            'fields': ('texto_saudacao',),
            'description': 'Resposta à <b>primeira</b> mensagem de um atendimento, em número '
                           'que não usa menu de setores (é o caso do RH). Sai uma vez por '
                           'atendimento, não a cada mensagem. Em branco, o cliente não recebe '
                           'nada até uma pessoa responder.',
        }),
        ('Menu de setores', {
            'fields': ('texto_menu',),
            'description': 'Os setores saem numerados abaixo desta linha, na ordem definida em Filas.',
        }),
        ('Confirmação de setor', {
            'fields': ('texto_roteamento',),
            'description': 'Escreva <code>{setor}</code> onde o nome do setor deve entrar.',
        }),
        ('Aviso de sem atendente online', {
            'fields': ('texto_sem_atendente',),
            'description': 'Enviado enquanto <b>Sem atendente online</b> estiver ligado no '
                           'número (em Números de negócio, ou pela chave na Central). Sai no '
                           'máximo uma vez a cada 6 horas por atendimento. Em branco, a '
                           'chave liga mas nada é enviado.',
        }),
        ('Assinatura das respostas', {
            'fields': ('assinatura',),
            'description': 'Rótulo do setor, que vai na frente de toda resposta do atendente '
                           'depois do primeiro nome de quem respondeu '
                           '(ex.: <i>Ana Paula · Grupo DB RH</i>). Em branco, sai só o nome '
                           'da pessoa.',
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
                    'menu_automatico', 'sem_atendente')
    list_editable = ('sem_atendente',)
    list_filter = ('ativo', 'is_padrao')
    search_fields = ('nome', 'telefone', 'phone_number_id')
    fieldsets = (
        (None, {'fields': ('nome', 'telefone', 'phone_number_id', 'ativo', 'is_padrao')}),
        ('Comportamento do robô', {
            'fields': ('menu_automatico', 'sem_atendente'),
            'description': 'Número que também é atendido no app do celular precisa do menu '
                           'DESLIGADO, senão o robô responde por cima da pessoa.<br>'
                           '<b>Sem atendente online</b> é chave de momento (almoço, fora do '
                           'horário, feriado) e também pode ser ligada na Central; o texto '
                           'do aviso está em Configuração do atendimento.',
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


class DisparoDestinatarioInline(admin.TabularInline):
    """Só leitura: a lista é montada no envio e o resultado é histórico."""
    model = DisparoDestinatario
    extra = 0
    can_delete = False
    fields = ('telefone', 'nome', 'status', 'erro', 'enviado_em')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Disparo)
class DisparoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'numero', 'template_nome', 'status', 'placar', 'criado_em')
    list_filter = ('status', 'numero')
    search_fields = ('nome', 'template_nome')
    readonly_fields = ('criado_por', 'criado_em', 'iniciado_em', 'concluido_em', 'detalhe_status')
    inlines = [DisparoDestinatarioInline]

    @admin.display(description='Enviados / Falhas / Pendentes')
    def placar(self, obj):
        return f'{obj.enviados} / {obj.falhas} / {obj.pendentes}'
