from django.urls import path

from .views import BiComercialMesView, BiComercialSaldoView, BiComercialView

# /api/bi/… (módulo BI, separado dos pedidos de venda)
urlpatterns = [
    path('comercial/', BiComercialView.as_view(), name='bi-comercial'),
    path('comercial/mes/', BiComercialMesView.as_view(), name='bi-comercial-mes'),
    path('comercial/saldo-pedidos/', BiComercialSaldoView.as_view(), name='bi-comercial-saldo'),
]
