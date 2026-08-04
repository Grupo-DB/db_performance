
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


from whatsapp.legal_views import PoliticaPrivacidadeView, TermosUsoView

urlpatterns = [
    path('admin/', admin.site.urls),
    # Páginas legais públicas exigidas pela Meta no cadastro do app do WhatsApp.
    # Ficam na raiz (não dentro de whatsapp/) porque valem para a empresa, não só para
    # esse canal, e porque a URL aparece para o usuário final no diálogo do WhatsApp.
    path('privacidade/', PoliticaPrivacidadeView.as_view(), name='legal-privacidade'),
    path('termos/', TermosUsoView.as_view(), name='legal-termos'),
    #path('auth/', include('autenticacoes.urls')),
    path('management/', include('avaliacoes.management.urls')),
    path('datacalc/', include('avaliacoes.datacalc.urls')),
    path('cal/', include('bisGerenciais.dashboardOperacoes.cal.urls')),
    path('home/', include('bisGerenciais.dashboardOperacoes.home.urls')),
    path('britagem/', include('bisGerenciais.dashboardOperacoes.britagem.urls')),
    path('rebritagem/', include('bisGerenciais.dashboardOperacoes.rebritagem.urls')),
    path('calcario/', include('bisGerenciais.dashboardOperacoes.calcario.urls')),
    path('fertilizante/',include('bisGerenciais.dashboardOperacoes.fertilizante.urls')),
    path('argamassa/',include('bisGerenciais.dashboardOperacoes.argamassa.urls')),
    path('orcamento/',include('baseOrcamentaria.orcamento.urls')),
    path('realizado/',include('baseOrcamentaria.realizado.urls')),
    path('dre/', include('baseOrcamentaria.dre.urls')),
    path('grupoitens/', include('baseOrcamentaria.grupoitens.urls')),
    path('custoproducao/', include('baseOrcamentaria.custoproducao.urls')),
    path('curva/', include('baseOrcamentaria.curva.urls')),
    path('ppr/', include('baseOrcamentaria.ppr.urls')),
    path('ensaio/', include('controleQualidade.ensaio.urls')),
    path('calculosEnsaio/', include('controleQualidade.calculosEnsaio.urls')),
    path('plano/', include('controleQualidade.plano.urls')),
    path('ordem/', include('controleQualidade.ordem.urls')),
    path('amostra/', include('controleQualidade.amostra.urls')),
    path('analise/', include('controleQualidade.analise.urls')),
    path('visitaTecnica/', include('controleQualidade.visitaTecnica.urls')),
    path('registroHoraExtra/', include('horasExtras.registros.urls')),
    path('kanban/', include('kanban.urls')),
    path('gestaoDocumentos/', include('gestaoDocumentos.urls')),
    path('apuracaoCustos/', include('apuracaoCustos.urls')),
    path('reservas/', include('reservas.urls')),
    path('despesas/', include('despesas.urls')),
    path('comissoes/', include('comissoes.urls')),
    path('catalogos/', include('catalogos.urls')),
    path('whatsapp/', include('whatsapp.urls')),
    path('emprestimos/', include('emprestimos.urls')),
    path('recrutamento/', include('recrutamento.urls')),
]
urlpatterns+=static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

