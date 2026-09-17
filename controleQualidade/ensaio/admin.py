from django.contrib import admin

from .models import PlanoPeneira, Finalidade, Fornecedor


@admin.register(PlanoPeneira)
class PlanoPeneiraAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'tipo', 'quantidade_malhas', 'ativo', 'ordem')
    list_filter = ('tipo', 'ativo')
    search_fields = ('descricao',)

    @admin.display(description='Malhas')
    def quantidade_malhas(self, obj):
        return len(obj.peneiras or [])


@admin.register(Finalidade)
class FinalidadeAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ativo', 'ordem')
    list_filter = ('ativo',)
    search_fields = ('nome',)


@admin.register(Fornecedor)
class FornecedorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ativo', 'ordem')
    list_filter = ('ativo',)
    search_fields = ('nome',)
