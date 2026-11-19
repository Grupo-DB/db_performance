from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('produtores', views.ProdutorViewSet, basename='agro-produtores')
router.register('contatos', views.ContatoViewSet, basename='agro-contatos')
router.register('cotacoes', views.CotacaoViewSet, basename='agro-cotacoes')
router.register('vendedores', views.VendedorViewSet, basename='agro-vendedores')

urlpatterns = [
    path('eu/', views.EuView.as_view()),
    path('inicio/', views.InicioView.as_view()),
    path('clientes/', views.ClientesView.as_view()),
    path('produtos/', views.ProdutosView.as_view()),
    path('vendas/', views.VendasView.as_view()),
    path('fila/', views.FilaView.as_view()),
    path('painel/', views.PainelView.as_view()),
    path('mercado/', views.MercadoView.as_view()),
    path('mercado/cenario/', views.CenarioMercadoView.as_view()),
    path('mercado/<int:ibge>/clientes/', views.MercadoClientesView.as_view()),
    path('malha/', views.MalhaView.as_view()),
    path('car/ponto/', views.CarPontoView.as_view()),
    path('car/<str:codigo>/', views.CarCodigoView.as_view()),
    path('prospeccao/', views.ProspeccaoView.as_view()),
    path('', include(router.urls)),
]
