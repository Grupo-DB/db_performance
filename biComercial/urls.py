from django.urls import path

from .views import BiComercialSaldoView, BiComercialView

# /api/bi/… (módulo BI, separado dos pedidos de venda)
urlpatterns = [
    path('comercial/', BiComercialView.as_view(), name='bi-comercial'),
    path('comercial/saldo-pedidos/', BiComercialSaldoView.as_view(), name='bi-comercial-saldo'),
]
