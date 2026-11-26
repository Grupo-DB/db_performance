from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    FabricanteViewSet, EquipamentoViewSet, VeiculoViewSet, SecaoViewSet, ItemViewSet,
    PedidoViewSet, PedidoNotificacaoViewSet, AnexoPedidoViewSet, ItemPedidoNaoCatalogadoViewSet,
    CatalogoPDFViewSet, ItemErpCatalogoViewSet, EquipamentoCatalogoViewSet,
    consultar_produtos, consultar_imagem_produto, almoxarifado_resumo,
    almoxarifado_itens, almoxarifado_foto, almoxarifado_catalogo,
    almoxarifado_catalogo_opcoes, almoxarifado_catalogo_item, almoxarifado_minimos, almoxarifado_prazo,
    almoxarifado_insumos, almoxarifado_insumos_serie, almoxarifado_indicadores, almoxarifado_insumos_monitorados, almoxarifado_insumos_monitorado,
    almoxarifado_insumos_setores, almoxarifado_insumos_setor, almoxarifado_insumos_usuarios,
    serve_catalogo_pdf_inline,
)

router = DefaultRouter()
router.register(r'fabricantes',          FabricanteViewSet,          basename='fabricante')
router.register(r'equipamentos',         EquipamentoViewSet,         basename='equipamento')
router.register(r'veiculos',             VeiculoViewSet,             basename='veiculo')
router.register(r'secoes',               SecaoViewSet,               basename='secao')
router.register(r'itens',               ItemViewSet,                basename='item')
router.register(r'pedidos',              PedidoViewSet,              basename='pedido')
router.register(r'notificacoes',         PedidoNotificacaoViewSet,   basename='notificacao')
router.register(r'catalogos-pdf',        CatalogoPDFViewSet,         basename='catalogo-pdf')
router.register(r'erp-catalogo',         ItemErpCatalogoViewSet,     basename='erp-catalogo')
router.register(r'equipamento-catalogo', EquipamentoCatalogoViewSet, basename='equipamento-catalogo')

anexo_router = DefaultRouter()
anexo_router.register(r'anexos', AnexoPedidoViewSet, basename='pedido-anexo')
anexo_router.register(r'itens-nao-catalogados', ItemPedidoNaoCatalogadoViewSet, basename='pedido-item-nao-catalogado')

urlpatterns = [
    path('', include(router.urls)),
    path('pedidos/<int:pedido_pk>/', include(anexo_router.urls)),
    path('erp/produtos/',       consultar_produtos,       name='erp-produtos'),
    path('erp/produto-imagem/', consultar_imagem_produto, name='erp-produto-imagem'),
    path('erp/almoxarifado/',   almoxarifado_resumo,      name='erp-almoxarifado'),
    path('erp/almoxarifado/itens/',   almoxarifado_itens,   name='erp-almoxarifado-itens'),
    path('erp/almoxarifado/foto/<int:cod>/', almoxarifado_foto, name='erp-almoxarifado-foto'),
    path('erp/almoxarifado/catalogo/', almoxarifado_catalogo, name='erp-almoxarifado-catalogo'),
    path('erp/almoxarifado/catalogo/opcoes/', almoxarifado_catalogo_opcoes, name='erp-almoxarifado-catalogo-opcoes'),
    path('erp/almoxarifado/catalogo/<int:cod>/', almoxarifado_catalogo_item, name='erp-almoxarifado-catalogo-item'),
    path('erp/almoxarifado/minimos/', almoxarifado_minimos, name='erp-almoxarifado-minimos'),
    path('erp/almoxarifado/prazos/',  almoxarifado_prazo,   name='erp-almoxarifado-prazos'),
    path('erp/almoxarifado/indicadores/', almoxarifado_indicadores, name='erp-almoxarifado-indicadores'),
    path('erp/almoxarifado/insumos/', almoxarifado_insumos, name='erp-almoxarifado-insumos'),
    path('erp/almoxarifado/insumos/serie/<int:codigo>/', almoxarifado_insumos_serie, name='erp-almoxarifado-insumos-serie'),
    path('erp/almoxarifado/insumos/monitorados/', almoxarifado_insumos_monitorados, name='erp-almoxarifado-insumos-monitorados'),
    path('erp/almoxarifado/insumos/monitorados/<int:pk>/', almoxarifado_insumos_monitorado, name='erp-almoxarifado-insumos-monitorado'),
    path('erp/almoxarifado/insumos/setores/', almoxarifado_insumos_setores, name='erp-almoxarifado-insumos-setores'),
    path('erp/almoxarifado/insumos/setores/<int:pk>/', almoxarifado_insumos_setor, name='erp-almoxarifado-insumos-setor'),
    path('erp/almoxarifado/insumos/usuarios/', almoxarifado_insumos_usuarios, name='erp-almoxarifado-insumos-usuarios'),
    path('catalogos-pdf/<int:pk>/inline/', serve_catalogo_pdf_inline, name='catalogo-pdf-inline'),
]
