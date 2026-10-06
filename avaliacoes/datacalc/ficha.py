"""Ficha do colaborador: cadastro, avaliações completas e histórico (destino do QR code da dash).

Quem abre:

- Admin, Master e RHGestor (ou superusuário): tudo, inclusive salário e dados pessoais;
- o avaliador que tem o colaborador nos vínculos (individual ou por setor):
  cadastro profissional, avaliações e histórico, SEM salário e sem os dados
  pessoais sensíveis (LGPD: raça, gênero, estado civil, nascimento).

O próprio colaborador não abre: veria as justificativas antes do feedback.

Qualquer outro usuário recebe 403 — o link do QR não abre nada sem login.
"""
import json
from collections import defaultdict

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from avaliacoes.management.models import Avaliacao, Avaliado, Avaliador, Colaborador, HistoricoAlteracao
from avaliacoes.management.vinculos import avaliados_do_avaliador

from .dashboard import GRUPOS_GERAL, _chave_periodo, _media, _notas

CONCEITO = {5: 'Ótimo', 4: 'Bom', 3: 'Regular', 2: 'Ruim', 1: 'Péssimo'}
CAMPOS_SENSIVEIS = ('salario',)


def _nome(obj):
    return obj.nome if obj else ''


def _data(v):
    return v.isoformat() if v else None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ficha_colaborador(request, pk):
    c = (
        Colaborador.objects
        .select_related('empresa', 'filial', 'area', 'setor', 'ambiente', 'cargo')
        .filter(pk=pk).first()
    )
    if not c:
        return Response({'detail': 'Colaborador não encontrado.'}, status=404)

    user = request.user
    completo = user.is_superuser or user.groups.filter(name__in=GRUPOS_GERAL).exists()
    if not completo:
        avaliador = Avaliador.objects.filter(user=user).first()
        vinculado = bool(avaliador) and avaliados_do_avaliador(avaliador).filter(pk=c.pk).exists()
        if not vinculado:
            return Response({'detail': 'Você não tem acesso à ficha deste colaborador.'}, status=403)

    cadastro = {
        'id': c.pk,
        'nome': c.nome,
        'email': c.email,
        'image': request.build_absolute_uri(c.image.url) if c.image else None,
        'empresa': _nome(c.empresa),
        'filial': _nome(c.filial),
        'area': _nome(c.area),
        'setor': _nome(c.setor),
        'ambiente': _nome(c.ambiente),
        'cargo': _nome(c.cargo),
        'tipocontrato': c.tipocontrato,
        'categoria': c.categoria,
        'instrucao': c.instrucao,
        'laboratorio': c.laboratorio,
        'situacao': c.situacao,
        'data_admissao': _data(c.data_admissao),
        'data_troca_setor': _data(c.data_troca_setor),
        'data_troca_cargo': _data(c.data_troca_cargo),
        'data_demissao': _data(c.data_demissao),
        'is_avaliado': Avaliado.objects.filter(pk=c.pk, papel_ativo=True).exists(),
        'is_avaliador': Avaliador.objects.filter(pk=c.pk, papel_ativo=True).exists(),
    }
    if completo:
        cadastro.update({
            'salario': c.salario,
            'genero': c.genero,
            'estado_civil': c.estado_civil,
            'raca': c.raca,
            'data_nascimento': _data(c.data_nascimento),
            'dominio_id': c.dominio_id,
            'minerion_id': c.minerion_id,
            'sgg_id': c.sgg_id,
        })

    # ---- Avaliações completas, da mais recente para a mais antiga ----
    avaliacoes = []
    for a in Avaliacao.objects.filter(avaliado_id=c.pk).select_related('avaliador'):
        notas, _ = _notas(a.perguntasRespostas)
        pr = a.perguntasRespostas
        if isinstance(pr, str):
            try:
                pr = json.loads(pr)
            except ValueError:
                pr = {}
        pr = pr if isinstance(pr, dict) else {}
        respostas = []
        for chave, dados in pr.items():
            dados = dados if isinstance(dados, dict) else {}
            pergunta = chave.removeprefix('pergunta-')
            nota = notas.get(pergunta)
            respostas.append({
                'pergunta': pergunta,
                'nota': nota,
                'conceito': CONCEITO.get(int(nota)) if nota is not None else 'Não se aplica',
                'justificativa': dados.get('justificativa') or '',
            })
        avaliacoes.append({
            'id': a.pk,
            'tipo': a.tipo,
            'periodo': a.periodo,
            'avaliador': a.avaliador.nome if a.avaliador_id else '',
            'data': _data(a.create_at),
            'feedback': a.feedback,
            'feedback_em': _data(a.finished_at),
            'observacoes': a.observacoes or '',
            'media': _media(list(notas.values())),
            'respostas': respostas,
            '_ordem': (_chave_periodo(a.periodo), a.create_at),
        })
    avaliacoes.sort(key=lambda x: x['_ordem'], reverse=True)

    # Evolução por período e média de cada pergunta em todas as avaliações.
    por_periodo, por_pergunta = defaultdict(list), defaultdict(list)
    for a in avaliacoes:
        for r in a['respostas']:
            if r['nota'] is not None:
                por_periodo[a['periodo']].append(r['nota'])
                por_pergunta[r['pergunta']].append(r['nota'])
        del a['_ordem']
    evolucao = [
        {'periodo': p, 'media': _media(v)}
        for p, v in sorted(por_periodo.items(), key=lambda kv: _chave_periodo(kv[0]))
    ]
    perguntas = sorted(
        ({'pergunta': p, 'media': _media(v), 'respostas': len(v)} for p, v in por_pergunta.items()),
        key=lambda x: -x['media'],
    )
    todas = [n for v in por_periodo.values() for n in v]

    # ---- Histórico de alterações do cadastro ----
    historico = HistoricoAlteracao.objects.filter(colaborador_id=c.pk).select_related('usuario').order_by('-data_alteracao')
    if not completo:
        historico = historico.exclude(campo_alterado__in=CAMPOS_SENSIVEIS)
    historico = [
        {
            'campo': h.campo_alterado,
            'de': h.valor_antigo,
            'para': h.valor_novo,
            'usuario': h.usuario.get_full_name() or h.usuario.username if h.usuario else '',
            'data': _data(h.data_alteracao),
        }
        for h in historico
    ]

    return Response({
        'completo': completo,
        'colaborador': cadastro,
        'resumo': {
            'avaliacoes': len(avaliacoes),
            'media': _media(todas),
            'ultima': avaliacoes[0]['media'] if avaliacoes else None,
            'feedbacks': sum(1 for a in avaliacoes if a['feedback']),
        },
        'evolucao': evolucao,
        'por_pergunta': perguntas,
        'avaliacoes': avaliacoes,
        'historico': historico,
    })
