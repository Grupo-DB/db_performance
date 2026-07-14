from django.contrib import admin

from .models import Aplicacao, Banco, Credor, Empresa, Resgate


@admin.register(Credor)
class CredorAdmin(admin.ModelAdmin):
    list_display = ['nome', 'cpf', 'cidade', 'estado', 'ativo']
    search_fields = ['nome', 'cpf']


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'cnpj', 'local', 'ativo']
    search_fields = ['nome', 'cnpj']


@admin.register(Banco)
class BancoAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'nome']


@admin.register(Aplicacao)
class AplicacaoAdmin(admin.ModelAdmin):
    list_display = ['numero_contrato', 'credor', 'empresa', 'valor_aplicacao', 'taxa', 'status', 'data_aplicacao']
    list_filter = ['status', 'empresa', 'banco', 'ano_referencia']
    search_fields = ['numero_contrato', 'credor__nome', 'empresa__nome']


@admin.register(Resgate)
class ResgateAdmin(admin.ModelAdmin):
    list_display = ['aplicacao', 'tipo', 'valor_resgatado', 'data_resgate']
    list_filter = ['tipo']
