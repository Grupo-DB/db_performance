from rest_framework.routers import DefaultRouter
from .views import (RegiaoViewSet, RepresentanteViewSet, MetaViewSet, ComissaoViewSet,
                    ParametroComissaoViewSet, VinculoRepresentanteViewSet, MapeamentoMunicipioViewSet,
                    RegraComissaoViewSet, RegraComissaoGrupoViewSet, RegraComissaoFaixaViewSet,
                    calculos_comissoes, popular_mapeamento_agro, consulta_canceladas)
from .conferencia import conferencia_vendedor
from .teste_valor_total import teste_total_vendedor_valor_total, descobrir_colunas_pedido
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
    path('consulta_canceladas/', consulta_canceladas, name='consulta_canceladas'),
    path('municipio/popular_agro/', popular_mapeamento_agro, name='popular_mapeamento_agro'),
    path('conferencia_vendedor/', conferencia_vendedor, name='conferencia_vendedor'),
    path('teste_total_vendedor_valor_total/', teste_total_vendedor_valor_total, name='teste_total_vendedor_valor_total'),
    path('descobrir_colunas_pedido/', descobrir_colunas_pedido, name='descobrir_colunas_pedido'),
] + router.urls
