"""Endpoints da tela Suprimentos › Peças da Oficina (26/11/2026). Regras em pecas_oficina.py."""
import logging

from django.http import FileResponse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import pecas_oficina as po
from .models import CatalogoPecas, ConjuntoPecas, SolicitacaoPecas
from .views import _almox_acesso

logger = logging.getLogger(__name__)

# Muda a situação e responde as solicitações.
GRUPOS_TRATAR = {'Admin', 'Master', 'comprasGestor', 'comprasComprador'}
# Liga equipamento ↔ catálogo/série.
GRUPOS_LIGAR = {'Admin', 'Master', 'comprasGestor', 'comprasOficina'}
# Faz pedido (os outros com acesso à tela só consultam).
GRUPOS_PEDIR = {'Admin', 'Master', 'comprasGestor', 'comprasOficina'}


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


@api_view(['GET'])
def pecas_conjunto(request, pk):
    if (erro := _acesso(request)):
        return erro
    cj = ConjuntoPecas.objects.filter(pk=pk).first()
    if cj is None:
        return _erro('Conjunto não encontrado.', status.HTTP_404_NOT_FOUND)
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
