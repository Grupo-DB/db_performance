from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import VisitaTecnicaImagemViewSet, VisitaTecnicaViewSet

router = DefaultRouter()
router.register(r'visitaTecnica', VisitaTecnicaViewSet, basename='VisitaTecnica')
router.register(r'visitaTecnicaImagem', VisitaTecnicaImagemViewSet, basename='VisitaTecnicaImagem')

urlpatterns = [
    path('', include(router.urls)),
]
