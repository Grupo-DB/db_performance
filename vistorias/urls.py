from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'unidades', views.UnidadeViewSet, basename='VistUnidade')
router.register(r'setores', views.SetorViewSet, basename='VistSetor')
router.register(r'tipos', views.TipoViewSet, basename='VistTipo')
router.register(r'fichas', views.FichaViewSet, basename='VistFicha')
router.register(r'equipamentos', views.EquipamentoViewSet, basename='VistEquipamento')
router.register(r'destinatarios', views.DestinatarioViewSet, basename='VistDestinatario')
router.register(r'programa/itens', views.ProgramaItemViewSet, basename='VistProgramaItem')
router.register(r'vistorias', views.VistoriaViewSet, basename='VistVistoria')
router.register(r'suspensoes', views.SuspensaoViewSet, basename='VistSuspensao')

urlpatterns = [
    path('opcoes/', views.OpcoesView.as_view()),
    path('usuarios/', views.UsuariosView.as_view()),
    path('programa/', views.ProgramaView.as_view()),
    path('programa/gerar/', views.ProgramaGerarView.as_view()),
    path('minhas/', views.MinhasView.as_view()),
    path('buscar-equipamento/', views.BuscarEquipamentoView.as_view()),
    path('evidencias/<uuid:uuid>/arquivo/', views.EvidenciaArquivoView.as_view()),
    path('imagens/<int:pk>/arquivo/', views.ImagemArquivoView.as_view()),
    path('painel/', views.PainelView.as_view()),
    path('resultados/', views.ResultadosView.as_view()),
    path('resultados/resumo/', views.ResultadosResumoView.as_view()),
    path('fechamentos/', views.FechamentoView.as_view()),
    path('auditoria/', views.AuditoriaView.as_view()),
    path('', include(router.urls)),
]
