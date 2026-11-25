"""
Renovação / nova versão de licença (23/11/2026, pedido do Pedro com a LO 05809/2026 da Mina Mato
Grande, que revoga a LO 00893/2024).

A licença nova é lançada como uma Norma nova ligada à anterior (`Norma.substitui`). A IA lê o PDF
novo como sempre; aqui as condicionantes sugeridas são CRUZADAS com as da licença anterior:

- igual     → o mesmo texto (a pessoa só confere);
- alterada  → a mesma condicionante com o texto mudado (a tela mostra o antes/depois);
- nova      → só existe na licença nova;
- removida  → só existia na anterior.

O par é achado pelo TEXTO, não pelo número: na LO 05809 entrou o capítulo "1. Quanto à Revogação"
e toda a numeração andou uma casa (a 1.1 virou 2.1). O número só desempata.

Ao aplicar, cada condicionante herdada leva da anterior: aplicabilidade e justificativa, responsável,
periodicidade, terceiros, capítulo, antecedência do aviso e a ÚLTIMA RESPOSTA (opção A combinada
com o Pedro: copiada como verificação marcada "herdada", com as fotos/anexos), além dos vínculos da
Matriz legal. A licença anterior vira REVOGADA e fica guardada com todo o histórico.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

IGUAL_MIN = 0.985       # texto praticamente igual (só espaço/pontuação)
PAR_MIN = 0.55          # abaixo disso não é a mesma condicionante
PAR_MIN_MESMO_NUMERO = 0.35   # com o número esperado batendo, aceita texto mais reescrito
BONUS_MESMO_NUMERO = 0.03
CANDIDATOS = 8          # por item novo, os mais parecidos pelo vocabulário vão para a conta fina
SEGURO = 0.9            # pares com essa similaridade ensinam a renumeração dos capítulos


def normalizar(texto: str) -> str:
    t = unicodedata.normalize('NFD', texto or '').encode('ascii', 'ignore').decode().lower()
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def numero(ref: str) -> str:
    """'Condicionante 4.1.3' / 'Item 4.1.3-' / '4.1.3' → '4.1.3'; subitem '14.2-3' → '14.2.3'."""
    m = re.search(r'\d+(?:[.-]\d+)*', ref or '')
    return m.group(0).replace('-', '.') if m else ''


def _palavras(t: str) -> set[str]:
    return {p for p in t.split() if len(p) > 2}


def similaridade(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _capitulos(pares: dict, novos: list[dict], antigos: list[dict]) -> dict[str, str]:
    """
    Renumeração aprendida dos pares seguros: capítulo antigo → capítulo novo pela maioria
    (na LO 05809 entrou o capítulo 1 "Revogação": o 1 antigo virou 2, o 3 virou 4…).
    """
    votos: dict[str, dict[str, int]] = {}
    for i, (j, s) in pares.items():
        if s < SEGURO:
            continue
        a, n = numero(antigos[j].get('referencia', '')), numero(novos[i].get('referencia', ''))
        if a and n:
            ca, cn = a.split('.')[0], n.split('.')[0]
            votos.setdefault(ca, {}).setdefault(cn, 0)
            votos[ca][cn] += 1
    return {ca: max(v, key=v.get) for ca, v in votos.items()}


def numero_esperado(ref_antiga: str, capitulos: dict[str, str]) -> str:
    """Número que a condicionante antiga deve ter na licença nova (o mesmo, com o capítulo renumerado)."""
    n = numero(ref_antiga)
    if not n:
        return ''
    partes = n.split('.')
    partes[0] = capitulos.get(partes[0], partes[0])
    return '.'.join(partes)


def cruzar(novos: list[dict], antigos: list[dict]) -> dict:
    """
    novos: [{'referencia', 'texto'}] (índice = posição na lista); antigos: [{'id', 'referencia', 'texto'}].
    Devolve {'pares': [{'novo': i, 'antigo': id|None, 'situacao', 'similaridade'}], 'removidos': [ids],
    'capitulos': {antigo: novo}}. Pareamento 1-para-1 guloso pela maior similaridade, em duas passadas:
    a 1ª aprende a renumeração dos capítulos, a 2ª usa o número esperado como desempate.
    """
    primeira = _parear(novos, antigos, {})
    capitulos = _capitulos(primeira, novos, antigos)
    par = _parear(novos, antigos, capitulos)

    pares = []
    for i in range(len(novos)):
        if i in par:
            j, s = par[i]
            pares.append({'novo': i, 'antigo': antigos[j]['id'], 'similaridade': round(s, 3),
                          'situacao': 'igual' if s >= IGUAL_MIN else 'alterada'})
        else:
            pares.append({'novo': i, 'antigo': None, 'similaridade': 0.0, 'situacao': 'nova'})
    usados = {j for j, _ in par.values()}
    removidos = [a['id'] for j, a in enumerate(antigos) if j not in usados]
    return {'pares': pares, 'removidos': removidos,
            'capitulos': {a: n for a, n in capitulos.items() if a != n}}


def _parear(novos: list[dict], antigos: list[dict], capitulos: dict[str, str]) -> dict[int, tuple[int, float]]:
    nn = [normalizar(n.get('texto', '')) for n in novos]
    na = [normalizar(a.get('texto', '')) for a in antigos]
    pn = [_palavras(t) for t in nn]
    pa = [_palavras(t) for t in na]
    esperado = [numero_esperado(a.get('referencia', ''), capitulos) for a in antigos]
    por_numero: dict[str, list[int]] = {}
    for j, e in enumerate(esperado):
        if e:
            por_numero.setdefault(e, []).append(j)

    candidatos = []
    for i, t in enumerate(nn):
        if not t:
            continue
        # pré-filtro barato: vocabulário em comum (Jaccard) → os CANDIDATOS melhores
        jac = []
        for j, p in enumerate(pa):
            if not na[j]:
                continue
            uniao = len(pn[i] | p) or 1
            jac.append((len(pn[i] & p) / uniao, j))
        jac.sort(reverse=True)
        num_i = numero(novos[i].get('referencia', ''))
        # os de vocabulário parecido + o(s) que deviam ter este número (texto muito reescrito)
        js = list(dict.fromkeys([j for _, j in jac[:CANDIDATOS]] + por_numero.get(num_i, [])))
        for j in js:
            if not na[j]:
                continue
            s = similaridade(t, na[j])
            mesmo = bool(num_i) and num_i == esperado[j]
            minimo = PAR_MIN_MESMO_NUMERO if mesmo else PAR_MIN
            if s >= minimo:
                candidatos.append((min(1.0, s + (BONUS_MESMO_NUMERO if mesmo else 0)), s, i, j))

    candidatos.sort(reverse=True)
    usado_n, usado_a, par = set(), set(), {}
    for _, s, i, j in candidatos:
        if i in usado_n or j in usado_a:
            continue
        usado_n.add(i)
        usado_a.add(j)
        par[i] = (j, s)
    return par


# ── Banco: comparação para a tela, aplicação e nova versão ──────────────────

# Campos da norma anterior que a nova versão leva (o resto — número, datas, PDF — é da nova).
CAMPOS_NORMA = ('tipo', 'orgao', 'esfera', 'tema', 'unidade_id', 'dias_aviso', 'link')
# Chaves da capa do relatório anual que apontam para requisitos da licença anterior (ids não valem na nova).
CAPA_SEM_IDS = ('fora', 'sem_resposta')


class SemExtracao(Exception):
    """A leitura da IA da licença nova ainda não terminou (ou falhou)."""


def texto_requisito(r) -> str:
    """O texto que se compara: o trecho literal da condicionante; sem ele, a descrição."""
    return r.trecho_fonte or r.descricao or ''


def _resumo_anterior(r, ultima) -> dict:
    from .serializers import nome_usuario
    return {
        'id': r.id,
        'referencia': r.referencia,
        'secao': r.secao,
        'descricao': r.descricao,
        'trecho': r.trecho_fonte,
        'aplicabilidade': r.aplicabilidade,
        'justificativa': r.justificativa,
        'responsavel': r.responsavel_id,
        'responsavel_nome': nome_usuario(r.responsavel) if r.responsavel_id else None,
        'periodicidade_meses': r.periodicidade_meses,
        'terceiros_nomes': [str(t) for t in r.terceiros.all()],
        'situacao': r.situacao,
        'ultima': None if ultima is None else {
            'id': ultima.id,
            'data': ultima.data.isoformat(),
            'resultado': ultima.resultado,
            'evidencia': ultima.evidencia,
            'observacao': ultima.observacao,
            'anexos': len(ultima.anexos.all()),
        },
    }


def _ultimas(requisitos) -> dict:
    """Última verificação de cada requisito (a mesma regra do recalcular_situacao)."""
    from .models import Verificacao
    ultimas = {}
    for v in (Verificacao.objects.filter(requisito__in=requisitos).prefetch_related('anexos')
              .order_by('requisito_id', '-data', '-id')):
        ultimas.setdefault(v.requisito_id, v)
    return ultimas


def comparar(norma) -> dict:
    """Cruza a última leitura da IA da licença nova com as condicionantes da anterior."""
    anterior = norma.substitui
    if anterior is None:
        raise ValueError('Esta licença não está ligada a uma versão anterior.')
    extracao = norma.extracoes.first()
    if extracao is None or extracao.status != 'CONCLUIDA':
        raise SemExtracao(extracao.status if extracao else 'SEM_LEITURA')

    antigos = list(anterior.requisitos.filter(ativo=True).select_related('responsavel__colaborador')
                   .prefetch_related('terceiros').order_by('id'))
    novos = list(extracao.itens or [])
    resultado = cruzar([{'referencia': n.get('referencia', ''), 'texto': n.get('trecho') or n.get('descricao', '')} for n in novos],
                       [{'id': r.id, 'referencia': r.referencia, 'texto': texto_requisito(r)} for r in antigos])
    ultimas = _ultimas(antigos)
    por_id = {r.id: r for r in antigos}
    # condicionantes já criadas na licença nova (aplicação anterior / revisão comum): não duplicar
    ja = {(normalizar(r.referencia), normalizar(texto_requisito(r))) for r in norma.requisitos.all()}

    itens = []
    for p in resultado['pares']:
        n = novos[p['novo']]
        r = por_id.get(p['antigo'])
        itens.append({
            'indice': p['novo'],
            'item': n,
            'situacao': p['situacao'],
            'similaridade': p['similaridade'],
            'ja_criado': (normalizar(n.get('referencia', '')), normalizar(n.get('trecho') or n.get('descricao', ''))) in ja,
            'anterior': _resumo_anterior(r, ultimas.get(r.id)) if r else None,
        })
    contagem = {s: sum(1 for i in itens if i['situacao'] == s) for s in ('igual', 'alterada', 'nova')}
    contagem['removida'] = len(resultado['removidos'])
    return {
        'norma': {'id': norma.id, 'identificacao': norma.identificacao, 'validade': norma.validade},
        'anterior': {'id': anterior.id, 'identificacao': anterior.identificacao, 'validade': anterior.validade,
                     'situacao': anterior.situacao, 'requisitos': len(antigos)},
        'extracao': extracao.id,
        'capitulos': resultado['capitulos'],
        'contagem': contagem,
        'itens': itens,
        'removidos': [_resumo_anterior(por_id[i], ultimas.get(i)) for i in resultado['removidos']],
        # candidatos para trocar o par na tela: todas as condicionantes da anterior
        'anteriores': [{'id': r.id, 'referencia': r.referencia, 'texto': texto_requisito(r)[:200]} for r in antigos],
    }


def _herdar_resposta(novo, ultima, usuario) -> None:
    """Opção A: a última resposta da anterior vira a 1ª da nova, com a mesma data e os mesmos anexos."""
    from .models import EvidenciaAnexo, Verificacao
    obs = ultima.observacao
    nota = 'Resposta herdada da licença anterior na renovação.'
    v = Verificacao.objects.create(
        requisito=novo, data=ultima.data, resultado=ultima.resultado, evidencia=ultima.evidencia,
        observacao=f'{obs}\n\n{nota}' if obs else nota, verificado_por=ultima.verificado_por or usuario,
        herdada_de=ultima)
    # mesmo arquivo no disco (o anexo só some quando a última evidência que o usa for apagada)
    EvidenciaAnexo.objects.bulk_create([
        EvidenciaAnexo(verificacao=v, nome=a.nome, arquivo=a.arquivo.name, legenda=a.legenda, tamanho=a.tamanho)
        for a in ultima.anexos.all()])


def aplicar(norma, itens: list[dict], usuario, revogar_anterior: bool = True) -> dict:
    """
    Cria as condicionantes aprovadas na licença nova. Cada item:
    {'indice', 'herdar_de': id|null, 'herdar_resposta': bool, 'dados': {referencia, secao, descricao, tema,
    periodicidade_meses, prazo_legal, trecho, pagina, observacao}}.
    Herdar (opção A): aplicabilidade+justificativa, responsável, periodicidade, terceiros, capítulo e aviso
    da anterior; a última resposta como verificação herdada; os vínculos da Matriz legal.
    """
    from django.db import transaction
    from django.utils import timezone
    from .models import MatrizVinculo, MatrizVinculoNorma, Requisito
    from .serializers import RequisitoSerializer

    anterior = norma.substitui
    if anterior is None:
        raise ValueError('Esta licença não está ligada a uma versão anterior.')
    antigos = {r.id: r for r in anterior.requisitos.prefetch_related('terceiros', 'matriz_vinculos')}
    ultimas = _ultimas(list(antigos.values()))
    usados: set[int] = set()
    criados, herdados, com_resposta = [], 0, 0

    with transaction.atomic():
        for it in itens:
            d = it.get('dados') or {}
            if not (d.get('descricao') or '').strip():
                continue
            velho = antigos.get(it.get('herdar_de')) if it.get('herdar_de') else None
            if it.get('herdar_de') and velho is None:
                raise ValueError(f"A condicionante {it.get('herdar_de')} não é da licença anterior.")
            if velho is not None:
                if velho.id in usados:
                    raise ValueError(f'A condicionante {velho.referencia or velho.id} da anterior foi escolhida duas vezes.')
                usados.add(velho.id)
            dados = {
                'norma': norma.id,
                'referencia': d.get('referencia', ''),
                'secao': d.get('secao') or (velho.secao if velho else ''),
                'descricao': d['descricao'].strip(),
                'tema': d.get('tema') or (velho.tema if velho else norma.tema),
                'periodicidade_meses': velho.periodicidade_meses if velho else d.get('periodicidade_meses', 12),
                'prazo_legal': d.get('prazo_legal') or None,
                'origem': 'IA',
                'trecho_fonte': d.get('trecho', ''),
                'pagina_fonte': d.get('pagina') or None,
                'aplicabilidade': velho.aplicabilidade if velho else 'EM_ANALISE',
                'justificativa': velho.justificativa if velho else (d.get('observacao') or ''),
                'responsavel': velho.responsavel_id if velho else None,
                'terceiros': [t.id for t in velho.terceiros.all()] if velho else [],
                'dias_aviso': velho.dias_aviso if velho else None,
            }
            s = RequisitoSerializer(data=dados)
            s.is_valid(raise_exception=True)
            novo = s.save(criado_por=usuario, herdado_de=velho)
            if velho is not None:
                herdados += 1
                ultima = ultimas.get(velho.id)
                if it.get('herdar_resposta') and ultima is not None:
                    _herdar_resposta(novo, ultima, usuario)
                    com_resposta += 1
                MatrizVinculo.objects.bulk_create(
                    [MatrizVinculo(item_id=v.item_id, requisito=novo, automatico=v.automatico, excluido=v.excluido, motivo=v.motivo)
                     for v in velho.matriz_vinculos.all()], ignore_conflicts=True)
            novo.recalcular_situacao()
            criados.append(novo.id)

        # A licença nova toma o lugar da anterior na Matriz legal.
        MatrizVinculoNorma.objects.bulk_create(
            [MatrizVinculoNorma(item_id=v.item_id, norma=norma, automatico=v.automatico, excluido=v.excluido, motivo=v.motivo)
             for v in anterior.matriz_vinculos.all()], ignore_conflicts=True)
        if revogar_anterior and anterior.situacao != 'REVOGADA':
            nota = f'Substituída por {norma.identificacao} em {timezone.localdate():%d/%m/%Y} (renovação no Manager).'
            anterior.situacao = 'REVOGADA'
            anterior.observacao = f'{anterior.observacao}\n{nota}'.strip()
            anterior.save(update_fields=['situacao', 'observacao', 'atualizado_em'])

    # Comparativo guardado (25/11/2026): retrato de como ficou a renovação + PDF.
    from . import comparativo
    comp = comparativo.gerar(norma, usuario)
    return {'criados': len(criados), 'herdados': herdados, 'com_resposta': com_resposta,
            'anterior_revogada': anterior.situacao == 'REVOGADA', 'ids': criados, 'comparativo': comp.id}


def nova_versao(anterior, dados: dict, arquivo, usuario):
    """Cria a licença nova ligada à anterior (número/datas/PDF da nova; órgão, tema, unidade, capa do relatório da anterior)."""
    from .models import Norma
    capa = dict(anterior.relatorio_anual or {}) or None
    if capa:
        for k in CAPA_SEM_IDS:
            capa.pop(k, None)
    nova = Norma(
        **{c: getattr(anterior, c) for c in CAMPOS_NORMA},
        numero=dados.get('numero', ''),
        ano=dados.get('ano') or None,
        ementa=dados.get('ementa') or anterior.ementa,
        data_publicacao=dados.get('data_publicacao') or None,
        validade=dados.get('validade') or None,
        situacao='VIGENTE',
        observacao=f'Nova versão de {anterior.identificacao}.',
        relatorio_anual=capa,
        substitui=anterior,
        criado_por=usuario,
    )
    if anterior.relatorio_logo:
        nova.relatorio_logo = anterior.relatorio_logo.name
    nova.arquivo = arquivo
    nova.save()
    return nova
