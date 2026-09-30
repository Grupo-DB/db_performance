"""Gravação das metas de um mês em lote (grade da tela de Metas / planilha importada).

Substitui o comando de management por mês (popular_metas_MM_AAAA): a tela monta a grade
representante × grupo, o usuário preenche (ou importa um Excel) e manda tudo aqui.
"""
import datetime as dt
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Meta, Representante

# Quem pode gravar metas (mesmos grupos de gestão das comissões).
GRUPOS_GESTAO = {'Admin', 'Master', 'vendasGestao'}
GRUPOS_VALIDOS = {'CB/CAL CREM', 'PRIMOR', 'PRIMEX', 'FINALIZA', 'AGRONEGOCIO', 'CONSTRUCAO CIVIL'}


class _DryRun(Exception):
    pass


def _pode_gravar(request) -> bool:
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name__in=GRUPOS_GESTAO).exists()


@csrf_exempt
@api_view(['POST'])
def metas_lote(request):
    """Grava as metas de um mês.

    Body: {
      data_meta: 'AAAA-MM-DD' (qualquer dia; vale o mês, gravado no dia 1),
      segmento: 'CONSTRUCAO CIVIL' | 'AGRONEGOCIO',
      itens: [{ representante: id | null (null = meta global), grupo, valor }],
      dry_run: bool (só simula)
    }
    Cada item é a célula (representante, grupo, mês): valor > 0 cria/atualiza; vazio ou 0
    apaga a meta que existir. Células que não vêm no lote não são tocadas.
    """
    if not _pode_gravar(request):
        return Response({'erro': 'Sem permissão para gravar metas.'}, status=403)

    d = request.data
    try:
        data_meta = dt.datetime.strptime(str(d.get('data_meta'))[:10], '%Y-%m-%d').date().replace(day=1)
    except (TypeError, ValueError):
        return Response({'erro': 'data_meta inválida (AAAA-MM-DD).'}, status=400)
    segmento = (d.get('segmento') or 'CONSTRUCAO CIVIL').strip().upper()
    itens = d.get('itens') or []
    if not isinstance(itens, list) or not itens:
        return Response({'erro': 'Nenhum item enviado.'}, status=400)

    reps = {r.id: r for r in Representante.objects.all()}
    erros = []
    normalizados = []
    for i, it in enumerate(itens, 1):
        grupo = str(it.get('grupo') or '').strip().upper()
        if grupo not in GRUPOS_VALIDOS:
            erros.append(f'Item {i}: grupo "{grupo}" inválido.')
            continue
        rep_id = it.get('representante')
        rep = None
        if rep_id not in (None, '', 0):
            rep = reps.get(int(rep_id))
            if rep is None:
                erros.append(f'Item {i}: representante {rep_id} não existe.')
                continue
        bruto = it.get('valor')
        try:
            valor = None if bruto in (None, '') else Decimal(str(bruto)).quantize(Decimal('0.01'))
        except InvalidOperation:
            erros.append(f'Item {i}: valor "{bruto}" inválido.')
            continue
        if valor is not None and valor < 0:
            erros.append(f'Item {i}: valor negativo.')
            continue
        normalizados.append((rep, grupo, valor))
    if erros:
        return Response({'erro': 'Lote recusado; nada foi gravado.', 'detalhes': erros}, status=400)

    resumo = {'criadas': 0, 'atualizadas': 0, 'removidas': 0, 'inalteradas': 0}
    try:
        with transaction.atomic():
            for rep, grupo, valor in normalizados:
                existentes = list(Meta.objects.filter(representante=rep, grupo=grupo, data_meta=data_meta).order_by('id'))
                # Duplicatas antigas da mesma célula: fica a primeira, o resto sai.
                for extra in existentes[1:]:
                    extra.delete()
                atual = existentes[0] if existentes else None
                if not valor:
                    if atual:
                        atual.delete()
                        resumo['removidas'] += 1
                    continue
                if atual is None:
                    Meta.objects.create(representante=rep, grupo=grupo, data_meta=data_meta,
                                        valor=valor, segmento=segmento,
                                        regiao=rep.regiao if rep else None)
                    resumo['criadas'] += 1
                elif atual.valor != valor or (atual.segmento or '') != segmento:
                    atual.valor = valor
                    atual.segmento = segmento
                    atual.save(update_fields=['valor', 'segmento'])
                    resumo['atualizadas'] += 1
                else:
                    resumo['inalteradas'] += 1
            if d.get('dry_run'):
                raise _DryRun()
    except _DryRun:
        return Response({**resumo, 'dry_run': True, 'data_meta': data_meta.isoformat()})

    return Response({**resumo, 'data_meta': data_meta.isoformat()})
