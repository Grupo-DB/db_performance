from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'tanques', views.TanqueViewSet, basename='CombustivelTanque')
router.register(r'medicoes', views.MedicaoViewSet, basename='CombustivelMedicao')
router.register(r'carregamentos', views.CarregamentoViewSet, basename='CombustivelCarregamento')
router.register(r'abastecimentos', views.AbastecimentoViewSet, basename='CombustivelAbastecimento')
router.register(r'lotes', views.LoteViewSet, basename='CombustivelLote')
router.register(r'chaves', views.ChaveViewSet, basename='CombustivelChave')

urlpatterns = [
    path('painel/', views.PainelView.as_view()),
    path('cadastros/', views.CadastrosView.as_view()),
    path('equipamentos/<int:equipamento>/ultima-leitura/', views.UltimaLeituraView.as_view()),
    path('documentacao/', views.DocumentacaoView.as_view()),
    path('auditoria/', views.AuditoriaView.as_view()),
    # Para o SGA (ou outro sistema) buscar — autenticação por chave, não por usuário.
    path('integracao/abastecimentos/', views.IntegracaoAbastecimentosView.as_view()),
    path('integracao/confirmar/', views.IntegracaoConfirmarView.as_view()),
    path('', include(router.urls)),
]
