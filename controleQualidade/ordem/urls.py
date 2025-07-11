from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework import routers
from rest_framework.routers import DefaultRouter

from .views import OrdemViewSet, OrdemHistoryViewSet, ExpressaViewSet

router = DefaultRouter()

router.register(r'ordem', OrdemViewSet, basename='Ordem')
router.register(r'expressa', ExpressaViewSet, basename='OrdemExpressa')

ordem_history_list = OrdemHistoryViewSet.as_view({'get': 'list'})

urlpatterns = [
    path('', include(router.urls)),
    path('ordem/<int:ordem_pk>/historico/', ordem_history_list, name='ordem-historico'),
]


