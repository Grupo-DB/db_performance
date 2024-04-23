from django.urls import path
from django.conf.urls.static import static
from django.conf import settings
from . import views
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
urlpatterns = [
    
    #path('management/', views.management, name='management'),
    path('create_user/', views.create_user, name='create_user'),
    path('registercompany/', views.registercompany, name='registercompany'),
    path('registerfilial/', views.registerfilial, name='registerfilial'),
    path('get_filial/', views.get_filial, name='get_filial'),
    path('registersetor/', views.registersetor, name='registersetor'),
    path('get_setor/', views.get_setor, name='get_setor'),
    path('registercargo/', views.registercargo, name='registercargo'),
    path('upload/', views.upload, name='upload'),
    path('get_cargo/', views.get_cargo, name='get_cargo'),
    path('registertipocontrato/', views.registertipocontrato, name='registertipocontrato'),
    path('get_tipocontrato/', views.get_tipocontrato, name='get_tipocontrato'),
    path('registertipoavaliacao/', views.registertipoavaliacao, name='registertipoavaliacao'),
    path('get_tipoavaliacao/', views.get_tipoavaliacao, name='get_tipoavaliacao'),
    path('registeravaliacao/', views.registeravaliacao, name='registeravaliacao'),
    path('get_avaliacao/', views.get_avaliacao, name='get_avaliacao'),
    path('registercolaborador/', views.registercolaborador, name='registercolaborador'),
    path('get_colaborador/', views.get_colaborador, name='get_colaborador'),
    path('registerformulario/', views.registerformulario, name='registerformulario'),
    path('get_formulario/', views.get_formulario, name='get_formulario'),
    path('registeravaliador/', views.registeravaliador, name='registeravaliador'),
    path('get_avaliador/', views.get_avaliador, name='get_avaliador'),
    path('registerpergunta/', views.registerpergunta, name='registerpergunta'),
    path('get_pergunta/', views.get_pergunta, name='get_pergunta'),
    path('get_company/', views.get_company, name='get_company'),
    path('registerarea/', views.registerarea, name='registerarea'),
    path('get_area/', views.get_area, name='get_area'),
    path('get_users/', views.get_users, name='get_users'),
    path('get_funcao/', views.get_funcao, name='get_funcao'),
    path('login/',views.login, name='login'),
    path('token/', TokenObtainPairView.as_view(),name='token_obtain_pair'),
    path('token/refresh/',TokenRefreshView.as_view(),name='token_refresh'),
    path('token/verify/',TokenVerifyView.as_view(),name='token_verify'),

] 
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)