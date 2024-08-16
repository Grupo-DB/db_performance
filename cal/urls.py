from django.urls import path
from .views import calculos_cal
urlpatterns = [
    path('calcular/', calculos_cal, name='cal'),
]