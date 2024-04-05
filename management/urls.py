from django.urls import path
from . import views
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,TokenVerifyView
urlpatterns = [
    
    #path('management/', views.management, name='management'),
    path('create_user/', views.create_user, name='create_user'),
    path('get_users/', views.get_users, name='get_users'),
    path('login/',views.login, name='login'),
    path('token/', TokenObtainPairView.as_view(),name='token_obtain_pair'),
    path('token/refresh/',TokenRefreshView.as_view(),name='token_refresh'),
    path('token/verify/',TokenVerifyView.as_view(),name='token_verify'),

]