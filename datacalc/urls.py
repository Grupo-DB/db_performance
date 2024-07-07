from django.urls import path
from .views import filtrar_colaboradores,filtrar_avaliacoes,periodo,filtrar_avaliacoes_logado
urlpatterns = [
    path('periodo/', periodo, name='periodo'),
    path('filtrar-avaliacoes/', filtrar_avaliacoes, name='filter_avaliacoes'),
    path('filtrar-colaboradores/', filtrar_colaboradores, name='filter_colaboradores'),
    path('filtrar-avaliacoes-logado/', filtrar_avaliacoes_logado, name='filter_avaliacoes_logado'),
]
