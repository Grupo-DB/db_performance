from django.urls import path

from . import views

urlpatterns = [
    path('', views.painel, name='cockpit-painel'),
    path('entrar', views.entrar, name='cockpit-entrar'),
    path('sair', views.sair, name='cockpit-sair'),
    path('trocar-senha', views.trocar_senha, name='cockpit-trocar-senha'),
    path('publicar', views.publicar, name='cockpit-publicar'),
    path('api/eu', views.api_eu),
    path('api/db/<str:colecao>/<str:doc_id>', views.api_doc),
    path('api/colecao/<str:colecao>', views.api_colecao),
    path('api/anexos', views.api_anexos),
    path('api/anexos/<int:anexo_id>', views.api_anexo),
]
