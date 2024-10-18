
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    #path('auth/', include('autenticacoes.urls')),
    path('management/', include('avaliacoes.management.urls')),
    path('datacalc/', include('avaliacoes.datacalc.urls')),
    path('cal/', include('bisGerenciais.cal.urls')),
    path('home/', include('bisGerenciais.dashboardOperacoes.home.urls')),
    path('britagem/', include('bisGerenciais.dashboardOperacoes.britagem.urls')),
    path('rebritagem/', include('bisGerenciais.dashboardOperacoes.rebritagem.urls')),
    path('calcario/', include('bisGerenciais.dashboardOperacoes.calcario.urls')),
    path('fertilizante/',include('bisGerenciais.dashboardOperacoes.fertilizante.urls')),

]
urlpatterns+=static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

