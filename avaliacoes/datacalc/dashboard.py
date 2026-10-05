"""Indicadores das avaliações de desempenho (a dash da Home do módulo).

O escopo sai de quem pede, não de parâmetro:

- Admin, Master e RHGestor (ou superusuário) veem o geral e podem abrir um
  avaliador qualquer com ``?avaliador_id=``;
- os demais só veem os próprios números, como avaliador. Sem cadastro de
  avaliador a resposta é 403.

Pendência e "quem o avaliador avalia" vêm de ``management/vinculos.py`` — o
vínculo por setor entra junto com o individual, igual ao sino e às cobranças.
"""
import json
import re
from collections import defaultdict

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from avaliacoes.management.models import Avaliacao, Avaliador
from avaliacoes.management.vinculos import avaliados_do_avaliador, avaliados_pendentes

GRUPOS_GERAL = ('Admin', 'Master', 'RHGestor')

ORDINAIS = {'primeiro': 1, 'segundo': 2, 'terceiro': 3, 'quarto': 4}
NOMES_TRIMESTRE = {1: 'Primeiro', 2: 'Segundo', 3: 'Terceiro', 4: 'Quarto'}


def _chave_periodo(texto):
    """("Terceiro Trimestre de 2025") -> (2025, 3). Os antigos sem ano ficam antes de todos."""
    t = (texto or '').strip().lower()
    tri = next((n for nome, n in ORDINAIS.items() if t.startswith(nome)), 0)
    ano = re.search(r'(\d{4})', t)
    return (int(ano.group(1)) if ano else 0, tri)


def periodo_corrente():
    """O período que está sendo avaliado agora: o trimestre anterior (mesma regra da tela Nova Avaliação)."""
    hoje = timezone.localdate()
    tri = (hoje.month - 1) // 3 + 1
    ano = hoje.year
    if tri == 1:
        tri, ano = 4, ano - 1
    else:
        tri -= 1
    return f'{NOMES_TRIMESTRE[tri]} Trimestre de {ano}'


def _notas(perguntas_respostas):
    """{pergunta: nota} só das respostas numéricas (1 a 5); "não se aplica" e vazio ficam de fora."""
    pr = perguntas_respostas
    if isinstance(pr, str):
        try:
            pr = json.loads(pr)
        except ValueError:
            return {}, 0
    notas, na = {}, 0
    for chave, dados in (pr or {}).items():
        resposta = dados.get('resposta') if isinstance(dados, dict) else None
        if resposta in (None, '', 'nao_se_aplica'):
            na += 1
            continue
        try:
            notas[chave.removeprefix('pergunta-')] = float(resposta)
        except (TypeError, ValueError):
            na += 1
    return notas, na


def _media(valores):
    return round(sum(valores) / len(valores), 2) if valores else None


def _pct(parte, total):
    return round(100 * parte / total, 1) if total else None


def _resumo_notas(avaliacoes):
    """Média geral, distribuição 1..5 + N/A e média por pergunta de uma lista de avaliações."""
    todas, por_pergunta = [], defaultdict(list)
    distribuicao = {'5': 0, '4': 0, '3': 0, '2': 0, '1': 0, 'na': 0}
    for a in avaliacoes:
        for pergunta, nota in a['_notas'].items():
            todas.append(nota)
            por_pergunta[pergunta].append(nota)
            chave = str(int(round(nota)))
            if chave in distribuicao:
                distribuicao[chave] += 1
        distribuicao['na'] += a['_na']
    perguntas = sorted(
        ({'pergunta': p, 'media': _media(v), 'respostas': len(v)} for p, v in por_pergunta.items()),
        key=lambda x: -x['media'],
    )
    return _media(todas), distribuicao, perguntas


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_avaliacoes(request):
    user = request.user
    pode_ver_geral = user.is_superuser or user.groups.filter(name__in=GRUPOS_GERAL).exists()

    avaliador = None
    avaliador_id = request.query_params.get('avaliador_id')
    if pode_ver_geral and avaliador_id:
        avaliador = Avaliador.objects.filter(pk=avaliador_id).first()
        if not avaliador:
            return Response({'detail': 'Avaliador não encontrado.'}, status=404)
    elif not pode_ver_geral:
        avaliador = Avaliador.objects.filter(user=user).first()
        if not avaliador:
            return Response({'detail': 'Você não está cadastrado como avaliador.'}, status=403)

    tipo = (request.query_params.get('tipo') or '').strip()

    base = Avaliacao.objects.all()
    if avaliador:
        base = base.filter(avaliador=avaliador)
    if tipo:
        base = base.filter(tipo__iexact=tipo)

    linhas = list(base.values(
        'id', 'periodo', 'feedback', 'avaliador_id', 'avaliado_id',
        'avaliado__nome', 'avaliado__ambiente__nome', 'perguntasRespostas',
    ))
    for a in linhas:
        a['_notas'], a['_na'] = _notas(a.pop('perguntasRespostas'))
        valores = list(a['_notas'].values())
        a['_media'] = _media(valores)

    corrente = periodo_corrente()
    periodos = sorted(
        {a['periodo'] for a in Avaliacao.objects.values('periodo') if a['periodo']} | {corrente},
        key=_chave_periodo, reverse=True,
    )
    periodo = request.query_params.get('periodo') or corrente

    # Evolução: média de cada período (todos, em ordem cronológica) no mesmo escopo.
    por_periodo = defaultdict(list)
    for a in linhas:
        if a['periodo']:
            por_periodo[a['periodo']].append(a)
    evolucao = []
    for p in sorted(por_periodo, key=_chave_periodo):
        media, _, _ = _resumo_notas(por_periodo[p])
        evolucao.append({'periodo': p, 'media': media, 'avaliacoes': len(por_periodo[p])})

    do_periodo = por_periodo.get(periodo, [])
    media, distribuicao, perguntas = _resumo_notas(do_periodo)
    feedback_dados = sum(1 for a in do_periodo if a['feedback'])

    resposta = {
        'escopo': 'individual' if avaliador else 'geral',
        'pode_ver_geral': pode_ver_geral,
        'avaliador': {'id': avaliador.pk, 'nome': avaliador.nome} if avaliador else None,
        'periodo': periodo,
        'periodo_corrente': corrente,
        'periodos': periodos,
        'distribuicao': distribuicao,
        'por_pergunta': perguntas,
        'evolucao': evolucao,
    }

    if avaliador:
        avaliados = list(avaliados_do_avaliador(avaliador).select_related('cargo', 'ambiente').order_by('nome'))
        pendentes = set(avaliados_pendentes(avaliador, periodo).values_list('pk', flat=True))
        minhas = {a['avaliado_id']: a for a in do_periodo}
        lista = []
        for c in avaliados:
            feita = minhas.get(c.pk)
            if feita:
                status = 'avaliado'
            elif c.pk in pendentes:
                status = 'pendente'
            else:
                status = 'por_colega'  # setor em modo "qualquer": outro avaliador já fez
            lista.append({
                'id': c.pk,
                'nome': c.nome,
                'cargo': c.cargo.nome if c.cargo_id else '',
                'setor': c.ambiente.nome if c.ambiente_id else '',
                'status': status,
                'media': feita['_media'] if feita else None,
                'feedback': bool(feita and feita['feedback']),
            })
        esperados = len(avaliados)
        resposta['kpis'] = {
            'avaliacoes': len(do_periodo),
            'esperados': esperados,
            'pendentes': len(pendentes),
            'conclusao_pct': _pct(esperados - len(pendentes), esperados),
            'media': media,
            'feedback_dados': feedback_dados,
            'feedback_pendentes': len(do_periodo) - feedback_dados,
        }
        resposta['avaliados'] = lista
        return Response(resposta)

    # ---- Geral: cada avaliador, os setores e o total ----
    feitas_por_avaliador = defaultdict(list)
    for a in do_periodo:
        feitas_por_avaliador[a['avaliador_id']].append(a)

    por_avaliador, pendentes_setor, avaliados_pendentes_ids = [], defaultdict(set), set()
    total_esperados = total_pendentes = 0
    for av in Avaliador.objects.order_by('nome'):
        esperados = avaliados_do_avaliador(av).count()
        feitas = feitas_por_avaliador.get(av.pk, [])
        if not esperados and not feitas:
            continue
        pend = list(avaliados_pendentes(av, periodo).values_list('pk', 'ambiente__nome'))
        for pk, setor in pend:
            pendentes_setor[setor or 'Sem setor'].add(pk)
            avaliados_pendentes_ids.add(pk)
        total_esperados += esperados
        total_pendentes += len(pend)
        por_avaliador.append({
            'id': av.pk,
            'nome': av.nome,
            'esperados': esperados,
            'feitas': len(feitas),
            'pendentes': len(pend),
            'conclusao_pct': _pct(esperados - len(pend), esperados),
            'media': _media([a['_media'] for a in feitas if a['_media'] is not None]),
        })

    por_setor_aval = defaultdict(list)
    for a in do_periodo:
        por_setor_aval[a['avaliado__ambiente__nome'] or 'Sem setor'].append(a)
    por_setor = sorted(
        (
            {
                'setor': s,
                'avaliacoes': len(por_setor_aval.get(s, [])),
                'media': _resumo_notas(por_setor_aval.get(s, []))[0],
                'pendentes': len(pendentes_setor.get(s, ())),
            }
            for s in set(por_setor_aval) | set(pendentes_setor)
        ),
        key=lambda x: (-(x['media'] or 0), x['setor']),
    )

    resposta['kpis'] = {
        'avaliacoes': len(do_periodo),
        'avaliados': len({a['avaliado_id'] for a in do_periodo}),
        'avaliadores_ativos': len(feitas_por_avaliador),
        'esperados': total_esperados,
        'pendentes': total_pendentes,
        'avaliados_pendentes': len(avaliados_pendentes_ids),
        'conclusao_pct': _pct(total_esperados - total_pendentes, total_esperados),
        'media': media,
        'feedback_dados': feedback_dados,
        'feedback_pendentes': len(do_periodo) - feedback_dados,
    }
    resposta['por_avaliador'] = por_avaliador
    resposta['por_setor'] = por_setor
    resposta['avaliadores'] = [{'id': a['id'], 'nome': a['nome']} for a in por_avaliador]
    return Response(resposta)
