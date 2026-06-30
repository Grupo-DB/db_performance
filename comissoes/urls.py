from rest_framework.routers import DefaultRouter
from .views import (RegiaoViewSet, RepresentanteViewSet, MetaViewSet, ComissaoViewSet,
                    ParametroComissaoViewSet, VinculoRepresentanteViewSet, MapeamentoMunicipioViewSet,
                    RegraComissaoViewSet, RegraComissaoGrupoViewSet, RegraComissaoFaixaViewSet,
                    calculos_comissoes, popular_mapeamento_agro)
from django.urls import path

router = DefaultRouter()
router.register(r'regiao', RegiaoViewSet, basename='regiao')
router.register(r'representante', RepresentanteViewSet, basename='representante')
router.register(r'meta', MetaViewSet, basename='meta')
router.register(r'comissao', ComissaoViewSet, basename='comissao')
router.register(r'parametros', ParametroComissaoViewSet, basename='parametros')
router.register(r'vinculo', VinculoRepresentanteViewSet, basename='vinculo')
router.register(r'municipio', MapeamentoMunicipioViewSet, basename='municipio')
router.register(r'regra', RegraComissaoViewSet, basename='regra')
router.register(r'regra-grupo', RegraComissaoGrupoViewSet, basename='regra-grupo')
router.register(r'regra-faixa', RegraComissaoFaixaViewSet, basename='regra-faixa')

urlpatterns = [
    path('calculos_comissoes/', calculos_comissoes, name='calculos_comissoes'),
    path('municipio/popular_agro/', popular_mapeamento_agro, name='popular_mapeamento_agro'),
] + router.urls
