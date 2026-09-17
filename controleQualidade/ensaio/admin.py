from django.contrib import admin

from .models import PlanoPeneira


@admin.register(PlanoPeneira)
class PlanoPeneiraAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'tipo', 'quantidade_malhas', 'ativo', 'ordem')
    list_filter = ('tipo', 'ativo')
    search_fields = ('descricao',)

    @admin.display(description='Malhas')
    def quantidade_malhas(self, obj):
        return len(obj.peneiras or [])
