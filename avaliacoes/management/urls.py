from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from . import views
from . views import AvaliadoViewSet,ColaboradorViewSet,AvaliadorViewSet,EmpresaViewSet,FilialViewSet,AreaViewSet, GestorViewSet,SetorViewSet,AmbienteViewSet,CargoViewSet,TipoContratoViewSet,PerguntaViewSet,FormularioViewSet,AvaliacaoViewSet,TipoAvaliacaoViewSet,send_email_view2,NotificationViewSet
from .views import update_password_first_login,CustomTokenObtainPairView,forgot_password,reset_password,HistoricoAlteracaoViewSet
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
from rest_framework.routers import DefaultRouter
router = DefaultRouter()
router.register(r'colaboradores', ColaboradorViewSet, basename='Colaborador')
router.register(r'avaliadores', AvaliadorViewSet, basename='Avaliador')
router.register(r'avaliados', AvaliadoViewSet, basename='Avaliado')
router.register(r'gestores', GestorViewSet, basename='Gestor')
router.register(r'empresas', EmpresaViewSet, basename='Empresa')
router.register(r'filiais', FilialViewSet, basename='Filial')
router.register(r'areas', AreaViewSet, basename='Areas')
router.register(r'setores', SetorViewSet, basename='Setores')
router.register(r'ambientes', AmbienteViewSet, basename='Ambientes')
router.register(r'cargos', CargoViewSet, basename='Cargos')
router.register(r'tipocontratos', TipoContratoViewSet, basename='TipoContratos')
router.register(r'tipoavaliacoes', TipoAvaliacaoViewSet, basename='TipoAvaliacoes')
router.register(r'perguntas', PerguntaViewSet, basename='Perguntas')
router.register(r'formularios', FormularioViewSet, basename='Formularios')
router.register(r'avaliacoes', AvaliacaoViewSet, basename='Avaliacoes')
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'historico-alteracoes', HistoricoAlteracaoViewSet)

#router.register(r'email', EmailViewSet, basename='Email')
urlpatterns = [
    
    #path('update_feedback/<int:avaliacao_id>/', UpdateFeedbackView.as_view(), name='update_feedback'),
    path('create_user/', views.create_user, name='create_user'),
    path('email/', send_email_view2, name='email'),
    path('update-password-first-login/', update_password_first_login, name='update_password_first_login'),
    path('forgot-password/', forgot_password, name='forgot_password'),
    path('reset-password/<uidb64>/<token>/', reset_password, name='reset_password'),
    #path('registerfilial/', views.registerfilial, name='registerfilial'),
    #path('get_filial/', views.get_filial, name='get_filial'),
    #path('registersetor/', views.registersetor, name='registersetor'),
    #path('get_setor/', views.get_setor, name='get_setor'),
    #path('registercargo/', views.registercargo, name='registercargo'),
    #path('upload/', views.upload, name='upload'),
    #path('get_cargo/', views.get_cargo, name='get_cargo'),
    #path('registertipocontrato/', views.registertipocontrato, name='registertipocontrato'),
    #path('get_tipocontrato/', views.get_tipocontrato, name='get_tipocontrato'),
    #path('registertipoavaliacao/', views.registertipoavaliacao, name='registertipoavaliacao'),
    #path('get_tipoavaliacao/', views.get_tipoavaliacao, name='get_tipoavaliacao'),
    #path('registeravaliacao/', views.registeravaliacao, name='registeravaliacao'),
    #path('get_avaliacao/', views.get_avaliacao, name='get_avaliacao'),
    #path('registercolaborador/', views.registercolaborador, name='registercolaborador'),
    #path('get_colaborador/', views.get_colaborador, name='get_colaborador'),
    #path('registerformulario/', views.registerformulario, name='registerformulario'),
    #path('get_formulario/', views.get_formulario, name='get_formulario'),
    #path('registeravaliador/', views.registeravaliador, name='registeravaliador'),
    #path('get_avaliador/', views.get_avaliador, name='get_avaliador'),
    #path('registerpergunta/', views.registerpergunta, name='registerpergunta'),
    #path('get_pergunta/', views.get_pergunta, name='get_pergunta'),
    #path('get_company/', views.get_company, name='get_company'),
    #path('registerarea/', views.registerarea, name='registerarea'),
    #path('responder/', views.responder, name='responder'),
   # path('colaborador_ativo/', views.colaborador_ativo, name='colaborador_ativo'),
    #path('avaliadores/<int:user_id>/informacoes_avaliador/', views.informacoes_avaliador, name='informacoes_avaliador'),
    #path('avaliador_do_usuario/', views.avaliador_do_usuario, name='avaliador_do_usuario'),
    #path('get_area/', views.get_area, name='get_area'),
    path('get_users/', views.get_users, name='get_users'),
    path('get_funcao/', views.get_funcao, name='get_funcao'),
    #path('login/',views.login, name='login'),
    path('token/', CustomTokenObtainPairView.as_view(),name='token_obtain_pair'),
    path('token/refresh/',TokenRefreshView.as_view(),name='token_refresh'),
    path('token/verify/',TokenVerifyView.as_view(),name='token_verify'),
    path('formulario/<int:formulario_id>/adicionar-pergunta/', views.add_pergunta_formulario, name='add_pergunta_formulario'),
    #path('avaliadores/<int:avaliador_id>/add_avaliado/', views.add_avaliado_avaliador, name='add_avaliado_avaliador'),
    path('formulario/<int:formulario_id>/perguntas/', views.get_perguntas_formularios, name='get_perguntas_formulario'),
    #path('avaliadores/<int:avaliador_id>/avaliados/', views.get_avaliados_avaliador, name='get_avaliados_avaliador'),
    path('', include(router.urls)),

] 
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)