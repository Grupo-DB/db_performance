"""Endpoints da tela Suprimentos › Peças da Oficina (26/11/2026). Regras em pecas_oficina.py."""
import logging

from django.http import FileResponse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import pecas_oficina as po
from django.http import HttpResponse

from .models import CatalogoPecas, ConjuntoPecas, ItemSolicitacaoPecas, KitPecas, SolicitacaoPecas
from .views import _almox_acesso

logger = logging.getLogger(__name__)

# Muda a situação e responde as solicitações.
GRUPOS_TRATAR = {'Admin', 'Master', 'comprasGestor', 'comprasComprador'}
# Liga equipamento ↔ catálogo/série.
GRUPOS_LIGAR = {'Admin', 'Master', 'comprasGestor', 'comprasOficina'}
# Faz pedido (os outros com acesso à tela só consultam).
GRUPOS_PEDIR = {'Admin', 'Master', 'comprasGestor', 'comprasOficina'}
# Envia, renomeia e exclui catálogo de fabricante (PDF) pela tela.
GRUPOS_IMPORTAR = {'Admin', 'Master', 'comprasGestor', 'comprasOficina'}


def _tem(user, grupos) -> bool:
    return user.is_superuser or user.groups.filter(name__in=grupos).exists()


def _acesso(request):
    return _almox_acesso(request, tela='pecas')


def _serie(request):
    v = (request.GET.get('serie') or '').strip()
    return int(v) if v.isdigit() else None


def _erro(msg, codigo=status.HTTP_400_BAD_REQUEST):
    return Response({'erro': msg}, status=codigo)


@api_view(['GET'])
def pecas_inicio(request):
    if (erro := _acesso(request)):
        return erro
    u = request.user
    return Response({
        'catalogos': po.catalogos(),
        'pode_tratar': _tem(u, GRUPOS_TRATAR),
        'pode_ligar': _tem(u, GRUPOS_LIGAR),
        'pode_pedir': _tem(u, GRUPOS_PEDIR),
        'pode_importar': _tem(u, GRUPOS_IMPORTAR),
        'pode_vincular': _tem(u, GRUPOS_TRATAR),
        'ia_configurada': po.pecas_ia.configurada(),
        'pdf_max_mb': po.PDF_MAX_MB,
        'usuario_id': u.id,
    })


@api_view(['GET'])
def pecas_equipamentos(request):
    if (erro := _acesso(request)):
        return erro
    try:
        return Response(po.lista_equipamentos())
    except Exception:
        logger.exception('peças da oficina: equipamentos do SGA')
        return _erro('Não foi possível ler os equipamentos do SGA agora.', status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(['PUT'])
def pecas_equipamento(request, codigo):
    if (erro := _acesso(request)):
        return erro
    if not _tem(request.user, GRUPOS_LIGAR):
        return _erro('Só o chefe da oficina ou o gestor ligam o equipamento ao catálogo.', status.HTTP_403_FORBIDDEN)
    try:
        return Response(po.ligar_equipamento(codigo, request.data.get('catalogo'), request.data.get('serie'),
                                             request.user))
    except ValueError as exc:
        return _erro(str(exc))


def _pode_importar(request):
    if (erro := _acesso(request)):
        return erro
    if not _tem(request.user, GRUPOS_IMPORTAR):
        return _erro('Só o chefe da oficina ou o gestor enviam catálogo.', status.HTTP_403_FORBIDDEN)
    return None


@api_view(['GET', 'POST'])
def pecas_catalogos(request):
    """GET: catálogos com a situação (a tela consulta enquanto importa). POST multipart: pdf, nome, fabricante, edicao."""
    if request.method == 'GET':
        if (erro := _acesso(request)):
            return erro
        return Response(po.catalogos())
    if (erro := _pode_importar(request)):
        return erro
    try:
        cat = po.enviar_catalogo(request.FILES.get('pdf'), request.data, request.user)
    except ValueError as exc:
        return _erro(str(exc))
    return Response(po.catalogo_dict(cat), status=status.HTTP_202_ACCEPTED)


@api_view(['PATCH', 'DELETE'])
def pecas_catalogo(request, pk):
    if (erro := _pode_importar(request)):
        return erro
    cat = CatalogoPecas.objects.filter(pk=pk).first()
    if cat is None:
        return _erro('Catálogo não encontrado.', status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        po.excluir_catalogo(cat)
        return Response(status=status.HTTP_204_NO_CONTENT)
    try:
        return Response(po.catalogo_dict(po.editar_catalogo(cat, request.data)))
    except ValueError as exc:
        return _erro(str(exc))


@api_view(['POST'])
def pecas_catalogo_pdf(request, pk):
    """Nova edição: reenvia o PDF de um catálogo existente (equipamentos ligados continuam ligados)."""
    if (erro := _pode_importar(request)):
        return erro
    cat = CatalogoPecas.objects.filter(pk=pk).first()
    if cat is None:
        return _erro('Catálogo não encontrado.', status.HTTP_404_NOT_FOUND)
    try:
        cat = po.enviar_catalogo(request.FILES.get('pdf'), request.data, request.user, catalogo=cat)
    except ValueError as exc:
        return _erro(str(exc))
    return Response(po.catalogo_dict(cat), status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
def pecas_conjuntos(request, catalogo):
    if (erro := _acesso(request)):
        return erro
    cat = CatalogoPecas.objects.filter(pk=catalogo).first()
    if cat is None:
        return _erro('Catálogo não encontrado.', status.HTTP_404_NOT_FOUND)
    serie = _serie(request)
    faixas = po.faixas_catalogo(cat)
    # Série fora de todas as faixas do catálogo: filtrar esconderia tudo; mostra o catálogo inteiro e avisa.
    fora = serie is not None and bool(faixas) and not any(a <= serie <= b for a, b in faixas)
    return Response({'catalogo': {'id': cat.id, 'nome': cat.nome, 'fabricante': cat.fabricante, 'edicao': cat.edicao},
                     'faixas': faixas, 'serie_fora': fora,
                     'conjuntos': po.indice(cat, None if fora else serie)})


@api_view(['GET'])
def pecas_busca(request, catalogo):
    if (erro := _acesso(request)):
        return erro
    cat = CatalogoPecas.objects.filter(pk=catalogo).first()
    if cat is None:
        return _erro('Catálogo não encontrado.', status.HTTP_404_NOT_FOUND)
    serie = _serie(request)
    return Response(po.buscar(cat, request.GET.get('q') or '', serie if po.serie_no_catalogo(cat, serie) else None))


@api_view(['GET', 'PATCH', 'DELETE'])
def pecas_conjunto(request, pk):
    if (erro := _acesso(request)):
        return erro
    cj = ConjuntoPecas.objects.filter(pk=pk).first()
    if cj is None:
        return _erro('Conjunto não encontrado.', status.HTTP_404_NOT_FOUND)
    if request.method in ('PATCH', 'DELETE'):
        if (erro := _pode_importar(request)):
            return erro
        if request.method == 'DELETE':
            po.excluir_conjunto(cj)
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            cj = po.editar_conjunto(cj, request.data)
        except ValueError as exc:
            return _erro(str(exc))
    serie = _serie(request)
    return Response(po.conjunto(cj, serie if po.serie_no_catalogo(cj.catalogo, serie) else None))


@api_view(['GET'])
def pecas_desenho(request, pk):
    if (erro := _acesso(request)):
        return erro
    cj = ConjuntoPecas.objects.filter(pk=pk).first()
    caminho = po.caminho_desenho(cj) if cj else None
    if caminho is None:
        return _erro('Desenho não encontrado.', status.HTTP_404_NOT_FOUND)
    resp = FileResponse(open(caminho, 'rb'), content_type='image/jpeg')
    resp['Cache-Control'] = 'private, max-age=86400'
    return resp


@api_view(['GET', 'POST'])
def pecas_solicitacoes(request):
    if (erro := _acesso(request)):
        return erro
    if request.method == 'POST':
        if not _tem(request.user, GRUPOS_PEDIR):
            return _erro('Só o chefe da oficina (ou o gestor) faz solicitação de peças.', status.HTTP_403_FORBIDDEN)
        try:
            sol = po.criar_solicitacao(request.data, request.user)
        except ValueError as exc:
            return _erro(str(exc))
        return Response(po.solicitacao_dict(sol), status=status.HTTP_201_CREATED)
    minhas = request.GET.get('minhas') in ('1', 'true')
    return Response(po.listar_solicitacoes(request.GET.get('status') or None,
                                           so_do_usuario=request.user if minhas else None))


@api_view(['GET', 'PATCH'])
def pecas_solicitacao(request, pk):
    if (erro := _acesso(request)):
        return erro
    sol = SolicitacaoPecas.objects.select_related('solicitante', 'tratado_por').filter(pk=pk).first()
    if sol is None:
        return _erro('Solicitação não encontrada.', status.HTTP_404_NOT_FOUND)
    if request.method == 'PATCH':
        try:
            sol = po.atualizar_solicitacao(sol, request.data, request.user, _tem(request.user, GRUPOS_TRATAR))
        except PermissionError as exc:
            return _erro(str(exc), status.HTTP_403_FORBIDDEN)
        except ValueError as exc:
            return _erro(str(exc))
    return Response(po.solicitacao_dict(sol, sga=True))



# ── 26/11/2026: de-para, sugestão da IA, kits, histórico, avisos, revisão e identificação ─────────────────

def _so_tratar(request, msg='Só o comprador (ou o gestor) vincula peça a item do SGA.'):
    if (erro := _acesso(request)):
        return erro
    if not _tem(request.user, GRUPOS_TRATAR):
        return _erro(msg, status.HTTP_403_FORBIDDEN)
    return None


@api_view(['GET'])
def pecas_itens_sga(request):
    if (erro := _acesso(request)):
        return erro
    try:
        return Response(po.buscar_itens_sga(request.GET.get('q') or ''))
    except Exception:
        logger.exception('peças: busca de itens do SGA')
        return _erro('Não foi possível consultar o SGA agora.', status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(['POST'])
def pecas_sugerir_sga(request):
    if (erro := _so_tratar(request)):
        return erro
    d = request.data
    if not (d.get('descricao') or '').strip():
        return _erro('Informe a descrição da peça.')
    try:
        return Response(po.sugerir_sga({k: str(d.get(k) or '')[:300] for k in ('codigo', 'descricao', 'conjunto', 'equipamento')}))
    except Exception:
        logger.exception('peças: sugestão de item do SGA')
        return _erro('Não foi possível consultar o SGA agora.', status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(['POST'])
def pecas_depara(request):
    if (erro := _so_tratar(request)):
        return erro
    d = request.data
    try:
        if d.get('remover'):
            return Response({'removidos': po.desvincular_sga(d.get('codigo') or '', d.get('item_sga'))})
        obj = po.vincular_sga(d.get('codigo') or '', d.get('item_sga'), request.user, d.get('origem') or 'manual')
    except (ValueError, TypeError) as exc:
        return _erro(str(exc))
    return Response({'id': obj.id, 'codigo': obj.codigo, 'item_sga': obj.item_sga, 'nome_sga': obj.nome_sga,
                     'origem': obj.origem}, status=status.HTTP_201_CREATED)


@api_view(['PATCH'])
def pecas_solicitacao_item(request, pk, item_id):
    if (erro := _so_tratar(request, 'Só o comprador escolhe o item do SGA da solicitação.')):
        return erro
    item = ItemSolicitacaoPecas.objects.select_related('solicitacao').filter(pk=item_id, solicitacao_id=pk).first()
    if item is None:
        return _erro('Item não encontrado.', status.HTTP_404_NOT_FOUND)
    try:
        po.definir_item_sga(item, request.data.get('item_sga'), request.user)
    except (ValueError, TypeError) as exc:
        return _erro(str(exc))
    return Response(po.solicitacao_dict(item.solicitacao, sga=True))


@api_view(['GET', 'POST'])
def pecas_kits(request):
    if (erro := _acesso(request)):
        return erro
    if request.method == 'GET':
        cat = request.GET.get('catalogo')
        return Response(po.listar_kits(int(cat) if cat and cat.isdigit() else None))
    if not _tem(request.user, GRUPOS_PEDIR):
        return _erro('Só o chefe da oficina (ou o gestor) monta kits.', status.HTTP_403_FORBIDDEN)
    try:
        kit = po.salvar_kit(request.data, request.user)
    except ValueError as exc:
        return _erro(str(exc))
    return Response(po.kit_dict(kit), status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'DELETE'])
def pecas_kit(request, pk):
    if (erro := _acesso(request)):
        return erro
    kit = KitPecas.objects.filter(pk=pk).first()
    if kit is None:
        return _erro('Kit não encontrado.', status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(po.kit_dict(kit, sga=True))
    if not _tem(request.user, GRUPOS_PEDIR):
        return _erro('Só o chefe da oficina (ou o gestor) altera kits.', status.HTTP_403_FORBIDDEN)
    if request.method == 'DELETE':
        kit.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    try:
        kit = po.salvar_kit(request.data, request.user, kit=kit)
    except ValueError as exc:
        return _erro(str(exc))
    return Response(po.kit_dict(kit, sga=True))


@api_view(['GET'])
def pecas_historico(request, codigo):
    if (erro := _acesso(request)):
        return erro
    return Response(po.historico_equipamento(codigo))


@api_view(['GET'])
def pecas_notificacoes(request):
    # Só o próprio usuário: não depende do grupo da tela (o aviso já foi para quem devia).
    return Response(po.notificacoes_do_usuario(request.user))


@api_view(['POST'])
def pecas_notificacoes_lidas(request):
    ids = request.data.get('notificacao_ids')
    return Response({'marcadas': po.marcar_notificacoes_lidas(request.user, ids)})


@api_view(['GET', 'PUT'])
def pecas_preferencias(request):
    if (erro := _acesso(request)):
        return erro
    if request.method == 'GET':
        return Response(po.preferencia_dict(request.user))
    try:
        return Response(po.salvar_preferencia(request.user, request.data))
    except ValueError as exc:
        return _erro(str(exc))


@api_view(['GET'])
def pecas_catalogo_revisao(request, pk):
    if (erro := _pode_importar(request)):
        return erro
    cat = CatalogoPecas.objects.filter(pk=pk).first()
    if cat is None:
        return _erro('Catálogo não encontrado.', status.HTTP_404_NOT_FOUND)
    return Response(po.revisao_catalogo(cat))


@api_view(['POST'])
def pecas_catalogo_publicar(request, pk):
    if (erro := _pode_importar(request)):
        return erro
    cat = CatalogoPecas.objects.filter(pk=pk).first()
    if cat is None:
        return _erro('Catálogo não encontrado.', status.HTTP_404_NOT_FOUND)
    try:
        return Response(po.catalogo_dict(po.publicar_catalogo(cat)))
    except ValueError as exc:
        return _erro(str(exc))


@api_view(['GET'])
def pecas_catalogo_pagina(request, pk, pagina):
    if (erro := _acesso(request)):
        return erro
    cat = CatalogoPecas.objects.filter(pk=pk).first()
    if cat is None:
        return _erro('Catálogo não encontrado.', status.HTTP_404_NOT_FOUND)
    try:
        jpg = po.pagina_pdf(cat, pagina)
    except ValueError as exc:
        return _erro(str(exc), status.HTTP_404_NOT_FOUND)
    except Exception:
        logger.exception('peças: página %s do catálogo %s', pagina, pk)
        return _erro('Não foi possível gerar a página.', status.HTTP_503_SERVICE_UNAVAILABLE)
    resp = HttpResponse(jpg, content_type='image/jpeg')
    resp['Cache-Control'] = 'private, max-age=86400'
    return resp


@api_view(['PUT'])
def pecas_conjunto_pecas(request, pk):
    if (erro := _pode_importar(request)):
        return erro
    cj = ConjuntoPecas.objects.filter(pk=pk).first()
    if cj is None:
        return _erro('Conjunto não encontrado.', status.HTTP_404_NOT_FOUND)
    try:
        po.salvar_pecas_conjunto(cj, request.data.get('pecas'))
    except ValueError as exc:
        return _erro(str(exc))
    return Response(po.conjunto(cj))


@api_view(['POST'])
def pecas_identificar(request, catalogo):
    if (erro := _acesso(request)):
        return erro
    cat = CatalogoPecas.objects.filter(pk=catalogo).first()
    if cat is None:
        return _erro('Catálogo não encontrado.', status.HTTP_404_NOT_FOUND)
    serie = request.data.get('serie')
    serie = int(serie) if str(serie or '').isdigit() else None
    try:
        return Response(po.identificar(cat, request.FILES.get('foto'), request.data.get('texto') or '',
                                       serie if po.serie_no_catalogo(cat, serie) else None,
                                       str(request.data.get('equipamento') or '')[:200]))
    except ValueError as exc:
        return _erro(str(exc))
