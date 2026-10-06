"""Indicadores das avaliações de desempenho (a dash da Home do módulo).

O escopo sai de quem pede, não de parâmetro:

- Admin, Master e RHGestor (ou superusuário) veem o geral e podem abrir um
  avaliador qualquer com ``?avaliador_id=``;
- os demais só veem os próprios números, como avaliador. Sem cadastro de
  avaliador a resposta é 403.

Filtros que valem nos dois escopos: ``?tipo=`` (nome do formulário gravado em
``Avaliacao.tipo``) e ``?avaliado_id=`` (um colaborador só — as médias dele
vêm com a da empresa ao lado, e vínculo/pendência ficam restritos a ele).

Pendência e "quem o avaliador avalia" vêm de ``management/vinculos.py`` — o
vínculo por setor entra junto com o individual, igual ao sino e às cobranças.
"""
import json
import re
from collections import defaultdict

from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from avaliacoes.management.models import Avaliacao, Avaliado, Avaliador
from avaliacoes.management.vinculos import avaliados_do_avaliador, avaliados_pendentes, q_ativo

GRUPOS_GERAL = ('Admin', 'Master', 'RHGestor')

# Nome antigo do tipo (gravado em Avaliacao.tipo até 2024) -> nome do formulário atual.
TIPO_NOME_ATUAL = {'avaliação do gestor': 'Avaliação de Gestores'}


def _tipo_atual(nome):
    nome = (nome or '').strip()
    return TIPO_NOME_ATUAL.get(nome.lower(), nome)


def _q_tipo(tipo):
    """Avaliações do tipo, incluindo as gravadas com o nome antigo dele."""
    q = Q(tipo__iexact=tipo)
    for antigo, atual in TIPO_NOME_ATUAL.items():
        if atual.lower() == tipo.lower():
            q |= Q(tipo__iexact=antigo)
    return q


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


def _por_avaliado(avaliacoes):
    """
    Junta as avaliações do mesmo colaborador: {avaliado_id: {pergunta: média}}.

    Com o "Basta um" um colaborador pode receber mais de uma avaliação no
    período (a segunda é opcional). Sem isso ele pesaria em dobro nas médias;
    aqui cada pergunta de cada avaliado vira uma nota só, e as médias saem daí.
    """
    notas = defaultdict(lambda: defaultdict(list))
    for a in avaliacoes:
        for pergunta, nota in a['_notas'].items():
            notas[a['avaliado_id']][pergunta].append(nota)
    return {av: {p: sum(v) / len(v) for p, v in por_p.items()} for av, por_p in notas.items()}


def _resumo_notas(avaliacoes):
    """
    Média geral, distribuição 1..5 + N/A e média por pergunta de uma lista de avaliações.

    Médias por avaliado (cada colaborador pesa 1, não importa quantos o avaliaram);
    a distribuição continua contando respostas, porque é o retrato das notas dadas.
    `respostas` de cada pergunta é o número de avaliados que a tiveram respondida.
    """
    todas, por_pergunta = [], defaultdict(list)
    distribuicao = {'5': 0, '4': 0, '3': 0, '2': 0, '1': 0, 'na': 0}
    for a in avaliacoes:
        for nota in a['_notas'].values():
            chave = str(int(round(nota)))
            if chave in distribuicao:
                distribuicao[chave] += 1
        distribuicao['na'] += a['_na']
    for por_p in _por_avaliado(avaliacoes).values():
        for pergunta, nota in por_p.items():
            todas.append(nota)
            por_pergunta[pergunta].append(nota)
    perguntas = sorted(
        ({'pergunta': p, 'media': _media(v), 'respostas': len(v)} for p, v in por_pergunta.items()),
        key=lambda x: -x['media'],
    )
    return _media(todas), distribuicao, perguntas


def _do_tipo(avaliados, tipo):
    """Com tipo escolhido, só os avaliados ligados ao formulário daquele tipo.

    `Avaliacao.tipo` grava o NOME do formulário usado (Nova Avaliação), e o avaliado
    tem os formulários dele em `Avaliado.formulario` — é por aí que se sabe quem
    deveria receber uma "Avaliação de Gestores" e quem recebe a "Geral".
    """
    if not tipo:
        return avaliados
    return avaliados.filter(formulario__nome__iexact=tipo).distinct()


def _regua_empresa(perguntas, periodo, tipo):
    """Põe em cada pergunta a média da empresa no período (`media_geral`), para comparar."""
    todas_periodo = Avaliacao.objects.filter(q_ativo('avaliado__'), q_ativo('avaliador__'), periodo=periodo)
    if tipo:
        todas_periodo = todas_periodo.filter(_q_tipo(tipo))
    geral_por_pergunta = defaultdict(list)
    todas_linhas = [
        {'avaliado_id': av_id, '_notas': _notas(pr)[0]}
        for av_id, pr in todas_periodo.values_list('avaliado_id', 'perguntasRespostas')
    ]
    for por_p in _por_avaliado(todas_linhas).values():
        for pergunta, nota in por_p.items():
            geral_por_pergunta[pergunta].append(nota)
    for item in perguntas:
        item['media_geral'] = _media(geral_por_pergunta.get(item['pergunta'], []))


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

    tipo = _tipo_atual(request.query_params.get('tipo'))
    avaliado_id = request.query_params.get('avaliado_id')
    avaliado = None
    if avaliado_id:
        avaliado = Avaliado.objects.filter(pk=avaliado_id).values('id', 'nome').first()
        if not avaliado:
            return Response({'detail': 'Avaliado não encontrado.'}, status=404)

    # Só colaboradores ativos (Situação + sem demissão passada), dos dois lados.
    base = Avaliacao.objects.filter(q_ativo('avaliado__'), q_ativo('avaliador__'))
    if avaliador:
        base = base.filter(avaliador=avaliador)
    # Opções do seletor de tipo: tudo o que já foi gravado, antes de filtrar por tipo/avaliado.
    tipos = {}
    for t in base.exclude(tipo__isnull=True).exclude(tipo='').values_list('tipo', flat=True).distinct():
        tipos.setdefault(_tipo_atual(t).lower(), _tipo_atual(t))
    if tipo:
        base = base.filter(_q_tipo(tipo))
    if avaliado:
        base = base.filter(avaliado_id=avaliado['id'])

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
        {a['periodo'] for a in base.values('periodo') if a['periodo']} | {corrente},
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
        'avaliado': avaliado,
        'tipo': tipo or None,
        'tipos': sorted(tipos.values(), key=str.lower),
        'periodo': periodo,
        'periodo_corrente': corrente,
        'periodos': periodos,
        'distribuicao': distribuicao,
        'por_pergunta': perguntas,
        'evolucao': evolucao,
    }

    if avaliador or avaliado:
        _regua_empresa(perguntas, periodo, tipo)

    if avaliador:
        # Seletor de avaliado: só os que este avaliador avalia (lista cheia mesmo com um aberto).
        resposta['avaliados_opcoes'] = list(avaliados_do_avaliador(avaliador).order_by('nome').values('id', 'nome'))
        do_avaliador = _do_tipo(avaliados_do_avaliador(avaliador), tipo)
        pend_qs = _do_tipo(avaliados_pendentes(avaliador, periodo), tipo)
        if avaliado:
            do_avaliador = do_avaliador.filter(pk=avaliado['id'])
            pend_qs = pend_qs.filter(pk=avaliado['id'])
        avaliados = list(do_avaliador.select_related('cargo', 'ambiente').order_by('nome'))
        pendentes = set(pend_qs.values_list('pk', flat=True))
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
    avaliados_esperados_ids = set()
    for av in Avaliador.objects.filter(q_ativo(), papel_ativo=True).order_by('nome'):
        do_av = _do_tipo(avaliados_do_avaliador(av), tipo)
        pend_qs = _do_tipo(avaliados_pendentes(av, periodo), tipo)
        if avaliado:
            # Com um avaliado aberto, só conta o vínculo com ele.
            do_av, pend_qs = do_av.filter(pk=avaliado['id']), pend_qs.filter(pk=avaliado['id'])
        ids_av = set(do_av.values_list('pk', flat=True))
        avaliados_esperados_ids |= ids_av
        esperados = len(ids_av)
        feitas = feitas_por_avaliador.get(av.pk, [])
        if not esperados and not feitas:
            continue
        pend = list(pend_qs.values_list('pk', 'ambiente__nome'))
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
        # Card "Pendentes" da visão geral: colaborador vinculado que não recebeu NENHUMA
        # avaliação no período (de nenhum avaliador). `pendentes` soma vínculos e conta
        # a mesma pessoa uma vez por avaliador que ainda falta.
        'avaliados_sem_avaliacao': len(avaliados_esperados_ids - {a['avaliado_id'] for a in do_periodo}),
        'avaliados_esperados': len(avaliados_esperados_ids),
        'conclusao_pct': _pct(total_esperados - total_pendentes, total_esperados),
        'media': media,
        'feedback_dados': feedback_dados,
        'feedback_pendentes': len(do_periodo) - feedback_dados,
    }
    # Média que cada avaliador deu em cada pergunta: o filtro da dash escolhe a pergunta.
    notas_av_pergunta = defaultdict(lambda: defaultdict(list))
    for a in do_periodo:
        for pergunta, nota in a['_notas'].items():
            notas_av_pergunta[a['avaliador_id']][pergunta].append(nota)
    nomes = {a['id']: a['nome'] for a in por_avaliador}
    resposta['por_avaliador_pergunta'] = [
        {
            'id': av_id,
            'nome': nomes.get(av_id) or Avaliador.objects.filter(pk=av_id).values_list('nome', flat=True).first() or '',
            'medias': {p: {'media': _media(v), 'respostas': len(v)} for p, v in por_p.items()},
            'media': _media([n for v in por_p.values() for n in v]),
        }
        for av_id, por_p in notas_av_pergunta.items()
    ]
    resposta['por_avaliador'] = por_avaliador
    resposta['por_setor'] = por_setor
    resposta['avaliadores'] = [{'id': a['id'], 'nome': a['nome']} for a in por_avaliador]
    resposta['avaliados_opcoes'] = list(Avaliado.objects.filter(q_ativo(), papel_ativo=True).order_by('nome').values('id', 'nome'))
    return Response(resposta)
