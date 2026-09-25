from django.contrib import admin

from .models import AnexoCockpit, DocumentoCockpit, UsuarioCockpit


@admin.register(DocumentoCockpit)
class DocumentoCockpitAdmin(admin.ModelAdmin):
    list_display = ('colecao', 'doc_id', 'atualizado_por', 'atualizado_em')
    list_filter = ('colecao',)
    exclude = ('dados',)


@admin.register(AnexoCockpit)
class AnexoCockpitAdmin(admin.ModelAdmin):
    list_display = ('nome', 'content_type', 'tamanho', 'enviado_por', 'enviado_em')


@admin.register(UsuarioCockpit)
class UsuarioCockpitAdmin(admin.ModelAdmin):
    """Senha não se edita aqui: use `python manage.py cockpit_usuario resetar <login>`."""
    list_display = ('nome', 'login', 'perfil', 'ativo', 'trocar_senha', 'ultimo_acesso')
    list_filter = ('perfil', 'ativo')
    search_fields = ('nome', 'login')
    exclude = ('senha_hash',)
    readonly_fields = ('versao', 'ultimo_acesso', 'criado_em')

    def save_model(self, request, obj, form, change):
        # Bloquear/mudar perfil derruba as sessões abertas do usuário.
        if change:
            obj.versao += 1
        super().save_model(request, obj, form, change)
