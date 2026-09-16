"""URLconf só dos testes: monta o app na raiz, sem o resto do projeto."""
from django.urls import include, path

urlpatterns = [path('pesquisas/', include('pesquisas.urls'))]
