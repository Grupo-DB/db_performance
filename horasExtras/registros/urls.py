from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()

router.register(r'registroHoraExtra', views.RegistroHoraExtraViewSet, basename='RegistroHoraExtra')

urlpatterns = [
    path('', include(router.urls)),
]