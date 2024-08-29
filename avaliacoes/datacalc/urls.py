from django.urls import path
from .views import filtrar_colaboradores,filtrar_avaliacoes,periodo,filtrar_avaliacoes_logado,filtrar_avaliados,filtrar_avaliacoes_periodo,filtrar_avaliacoes_avaliador_periodo,get_unique_periodos,filtrar_historico,get_unique_tipos
urlpatterns = [
    path('periodo/', periodo, name='periodo'),
    path('filtrar-avaliacoes/', filtrar_avaliacoes, name='filter_avaliacoes'),
    path('filtrar-colaboradores/', filtrar_colaboradores, name='filter_colaboradores'),
    path('filtrar-avaliacoes-logado/', filtrar_avaliacoes_logado, name='filter_avaliacoes_logado'),
    path('filtrar-avaliados/', filtrar_avaliados, name='filter_avaliados'),
    path('filtrar-avaliacoes-periodo/', filtrar_avaliacoes_periodo, name='filter_avaliacoes_periodo'),
    path('filtrar-avaliacoes-avaliador-periodo/', filtrar_avaliacoes_avaliador_periodo, name='filter_avaliacoes_avaliador_periodo'),
    path('get-periodos/', get_unique_periodos, name='get_unique_periodos'),
    path('get-tipos/', get_unique_tipos, name='get_unique_tipos'),
    path('filtrar-historico/', filtrar_historico, name='filtrar_historico'),
]
