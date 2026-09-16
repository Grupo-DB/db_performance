from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import PesquisaPublicaView, PesquisaViewSet

router = DefaultRouter()
router.register(r'pesquisa', PesquisaViewSet, basename='pesquisa')

urlpatterns = router.urls + [
    # Aberto, sem autenticação: é o endereço que vai para o colaborador.
    path('publica/<str:token>/', PesquisaPublicaView.as_view(), name='pesquisa-publica'),
]
