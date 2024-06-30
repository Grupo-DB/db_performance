from django.urls import path
from .views import filtrar_colaboradores,filtrar_avaliacoes
urlpatterns = [
    #path('total-colaboradores/', calc_colaboradores, name='total-colaboradores'),
    # path('filtrar_colaboradores/', filtrar_colaboradores, name='filtrar_colaboradores'),
    path('filtrar-avaliacoes/', filtrar_avaliacoes, name='filter_avaliacoes'),
    path('filtrar-colaboradores/', filtrar_colaboradores, name='filter_colaboradores'),
]