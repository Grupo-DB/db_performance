"""Módulo BI (24/11/2026): relatórios do Power BI reproduzidos no Manager. Hoje: Comercial."""
import logging
from datetime import date

from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

# Módulo próprio (24/11/2026), fora dos pedidos de venda: só estes grupos.
GRUPOS_BI_COMERCIAL = ('Admin', 'Master', 'comercialBI')


class TemAcessoBiComercial(BasePermission):
    message = 'Sem acesso ao BI Comercial.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_superuser or u.groups.filter(name__in=GRUPOS_BI_COMERCIAL).exists()))


def _bi_filtros(params, chaves) -> dict:
    """?cliente=A&cliente=B… (repetido: nome de cliente pode ter vírgula)."""
    return {k: [v for v in params.getlist(k) if v] for k in chaves if params.getlist(k)}


class BiComercialView(APIView):
    """Páginas 0, 1, 2, 4 e 5 do BI: ?desde=&ate= (AAAA-MM-DD, padrão: o ano até hoje) e os filtros
    filial, regiao, segmento, grupo, representante, cliente, natureza, produto (repetíveis)."""
    permission_classes = [TemAcessoBiComercial]

    def get(self, request):
        from . import comercial as bi
        p = request.query_params
        try:
            desde = date.fromisoformat(p['desde']) if p.get('desde') else None
            ate = date.fromisoformat(p['ate']) if p.get('ate') else None
            return Response(bi.painel(desde, ate, _bi_filtros(p, bi.FILTROS)))
        except ValueError as exc:
            return Response({'detail': str(exc) or 'Data inválida (AAAA-MM-DD).'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception('BI comercial')
            return Response({'detail': f'Falha na consulta ao SGA: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)


class BiComercialSaldoView(APIView):
    """Página 8 do BI (saldo de pedidos abertos): filtros filial, grupo, produto, cliente e
    ?desde=&ate= na data de criação do pedido."""
    permission_classes = [TemAcessoBiComercial]

    def get(self, request):
        from . import comercial as bi
        p = request.query_params
        try:
            desde = date.fromisoformat(p['desde']) if p.get('desde') else None
            ate = date.fromisoformat(p['ate']) if p.get('ate') else None
            return Response(bi.saldo(_bi_filtros(p, bi.FILTROS_SALDO), desde, ate))
        except ValueError:
            return Response({'detail': 'Data inválida (AAAA-MM-DD).'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception('BI comercial — saldo de pedidos')
            return Response({'detail': f'Falha na consulta ao SGA: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)


class BiComercialMesView(APIView):
    """Mês a mês (25/11/2026): ?mes=AAAA-MM → cada dia do mês; ?dia=AAAA-MM-DD → as notas do dia.
    Mesmos filtros do painel (repetíveis)."""
    permission_classes = [TemAcessoBiComercial]

    def get(self, request):
        from . import comercial as bi
        p = request.query_params
        filtros = _bi_filtros(p, bi.FILTROS)
        try:
            if p.get('dia'):
                return Response(bi.dia_detalhe(date.fromisoformat(p['dia']), filtros))
            return Response(bi.mes_diario(p.get('mes') or date.today().strftime('%Y-%m'), filtros))
        except ValueError as exc:
            return Response({'detail': str(exc) or 'Data inválida.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception('BI comercial — mês a mês')
            return Response({'detail': f'Falha na consulta ao SGA: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
