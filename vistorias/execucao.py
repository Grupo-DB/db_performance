"""Execução, validação e o fluxo de suspensão/liberação (seções 6, 8 e 9)."""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from . import avisos, regras
from .models import (CRITICA, NENHUMA, Equipamento, Evidencia, Impedimento, NCCritica, ProgramaItem, Resposta,
                     Suspensao, Vistoria)
from .servicos import auditar, item_aberto, suspensao_aberta, vinculo_em


# ── Início ─────────────────────────────────────────────────────────────────────
def ultima_medicao(eq: Equipamento, exceto: Vistoria | None = None):
    qs = eq.vistorias.exclude(medicao__isnull=True).exclude(status=Vistoria.ANDAMENTO)
    if exceto is not None:
        qs = qs.exclude(pk=exceto.pk)
    v = qs.order_by('-concluida_em').first()
    return (v.medicao, v.concluida_em) if v else (None, None)


@transaction.atomic
def iniciar(eq: Equipamento, avaliador, uuid=None, item: ProgramaItem | None = None,
            extraordinaria: bool = False, motivo: str = '') -> Vistoria:
    """
    Abre a vistoria com a versão VIGENTE da ficha e copia as questões ativas.
    Reenvio com o mesmo uuid (fila do aparelho) devolve a mesma vistoria.
    """
    if uuid:
        existente = Vistoria.objects.filter(uuid=uuid).first()
        if existente:
            if existente.avaliador_id != avaliador.pk:
                raise PermissionDenied('Essa vistoria é de outro avaliador.')
            return existente
    if not eq.ativo:
        raise ValidationError({'detail': 'Equipamento inativo.'})
    versao = eq.tipo.ficha.versao_atual()
    if versao is None:
        raise ValidationError({'detail': f'A ficha "{eq.tipo.ficha.nome}" ainda não tem questões.'})

    if not extraordinaria:
        if item is None:
            hoje = timezone.localdate()
            item = item_aberto(eq, hoje.year, hoje.month)
        if item is None or item.situacao != ProgramaItem.PROGRAMADA:
            raise ValidationError({'detail': 'Não há vistoria programada pendente para este equipamento. '
                                             'Use "Vistoria extraordinária".'})
        if item.equipamento_id != eq.pk:
            raise ValidationError({'detail': 'Item do programa não é deste equipamento.'})
        em_aberto = item.vistorias.first()
        if em_aberto is not None:
            if em_aberto.status != Vistoria.ANDAMENTO:
                raise ValidationError({'detail': 'Essa vistoria programada já foi realizada.'})
            if em_aberto.avaliador_id != avaliador.pk:
                raise ValidationError({'detail': f'Vistoria já iniciada por {em_aberto.avaliador.get_full_name() or em_aberto.avaliador.username}.'})
            return em_aberto
    elif not (motivo or '').strip():
        raise ValidationError({'motivo': 'Informe o motivo da vistoria extraordinária.'})

    agora = timezone.now()
    vinc = vinculo_em(eq, agora)
    anterior, _ = ultima_medicao(eq)
    extra = {'uuid': uuid} if uuid else {}
    v = Vistoria.objects.create(
        **extra, equipamento=eq, item=None if extraordinaria else item,
        tipo=Vistoria.EXTRAORDINARIA if extraordinaria else Vistoria.PROGRAMADA,
        motivo_extraordinaria=(motivo or '').strip()[:300], ficha_versao=versao,
        unidade_id=vinc.unidade_id if vinc else eq.unidade_id, setor_id=vinc.setor_id if vinc else eq.setor_id,
        gerente_id=vinc.gerente_id if vinc else eq.gerente_id, avaliador=avaliador, iniciada_em=agora,
        medicao_tipo=eq.tipo.medicao, medicao_anterior=anterior)
    Resposta.objects.bulk_create([
        Resposta(vistoria=v, questao=q, codigo=q.codigo, grupo=q.grupo, descricao=q.descricao,
                 criticidade=q.criticidade, permite_na=q.permite_na, permite_abono=q.permite_abono, ordem=q.ordem)
        for q in versao.questoes.filter(ativa=True)])
    auditar(avaliador, 'vistoria_iniciar', 'vistoria', v.uuid, f'{eq.tag} ({v.get_tipo_display()})')
    return v


def _do_avaliador(v: Vistoria, usuario):
    if v.avaliador_id != usuario.pk:
        raise PermissionDenied('Só o avaliador que iniciou altera esta vistoria.')
    if v.status != Vistoria.ANDAMENTO:
        raise ValidationError({'detail': 'Vistoria já concluída: respostas e evidências não podem mais ser alteradas.'})


# ── Identificação ──────────────────────────────────────────────────────────────
@transaction.atomic
def salvar_identificacao(v: Vistoria, usuario, dados: dict) -> Vistoria:
    _do_avaliador(v, usuario)
    campos = []
    if 'medicao' in dados:
        bruto = dados.get('medicao')
        if bruto in (None, ''):
            v.medicao = None
        else:
            try:
                v.medicao = Decimal(str(bruto).replace(',', '.'))
            except InvalidOperation:
                raise ValidationError({'medicao': 'Valor inválido.'})
            if v.medicao < 0:
                raise ValidationError({'medicao': 'Valor inválido.'})
        v.medicao_menor_confirmada = bool(dados.get('medicao_menor_confirmada', v.medicao_menor_confirmada))
        campos += ['medicao', 'medicao_menor_confirmada']
    if 'marcacoes' in dados:
        v.marcacoes = validar_marcacoes(v, dados.get('marcacoes'))
        campos.append('marcacoes')
    for c in ('acompanhante_nome', 'acompanhante_cargo', 'observacoes'):
        if c in dados:
            setattr(v, c, str(dados.get(c) or '').strip()[:5000 if c == 'observacoes' else 120])
            campos.append(c)
    if campos:
        v.save(update_fields=campos + ['atualizada_em'])
    return v


def validar_marcacoes(v: Vistoria, bruto) -> list:
    if bruto in (None, ''):
        return []
    if not isinstance(bruto, list) or len(bruto) > 80:
        raise ValidationError({'marcacoes': 'Marcações inválidas.'})
    validas = set(v.equipamento.tipo.imagens.values_list('id', flat=True))
    saida = []
    for m in bruto:
        try:
            img, x, y = int(m['imagem']), float(m['x']), float(m['y'])
        except (KeyError, TypeError, ValueError):
            raise ValidationError({'marcacoes': 'Marcações inválidas.'})
        if img not in validas or not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValidationError({'marcacoes': 'Marcação fora do desenho.'})
        saida.append({'imagem': img, 'x': round(x, 4), 'y': round(y, 4), 'nota': str(m.get('nota') or '')[:120]})
    return saida


def medicao_menor(v: Vistoria) -> bool:
    return v.medicao is not None and v.medicao_anterior is not None and v.medicao < v.medicao_anterior


# ── Respostas ──────────────────────────────────────────────────────────────────
@transaction.atomic
def responder(v: Vistoria, usuario, codigo: str, valor: str, descricao: str = '', confirmar_critica: bool = False,
              request=None) -> tuple[Resposta, Suspensao | None]:
    """
    Salva uma resposta (autosave a cada toque). NC crítica só "vale" com ``confirmar_critica``:
    aí suspende o equipamento, cria/estende a suspensão e dispara o e-mail — e trava a resposta.
    """
    _do_avaliador(v, usuario)
    r = v.respostas.select_for_update().filter(codigo=codigo).first()
    if r is None:
        raise ValidationError({'codigo': 'Questão não encontrada nesta vistoria.'})
    if r.travada:
        raise ValidationError({'detail': 'NC crítica já confirmada: só o Gerente Executivo Operacional pode cancelá-la.'})
    valor = (valor or '').upper()
    if valor not in ('', Resposta.C, Resposta.NC, Resposta.NA):
        raise ValidationError({'valor': 'Resposta inválida.'})
    if valor == Resposta.NA and not r.permite_na:
        raise ValidationError({'valor': 'Esta questão não aceita "Não aplicável".'})
    r.valor = valor
    r.descricao_problema = (descricao or '').strip()[:2000] if valor == Resposta.NC else ''
    r.respondida_em = timezone.now() if valor else None
    suspensao = None
    if valor == Resposta.NC and r.criticidade == CRITICA and confirmar_critica:
        if not r.descricao_problema:
            raise ValidationError({'descricao': 'Descreva o problema antes de confirmar a NC crítica.'})
        r.critica_confirmada_em = timezone.now()
        r.save()
        suspensao = suspender(v, r, request=request)
    else:
        r.save()
    return r, suspensao


def suspender(v: Vistoria, r: Resposta, request=None) -> Suspensao:
    """9.2: suspende na hora. Se já há suspensão aberta, a NC entra nela (todas precisam de correção)."""
    eq = Equipamento.objects.select_for_update().get(pk=v.equipamento_id)
    s = suspensao_aberta(eq)
    nova = s is None
    if nova:
        s = Suspensao.objects.create(equipamento=eq, vistoria=v, iniciada_em=r.critica_confirmada_em)
    elif s.status == Suspensao.AGUARDANDO:
        s.status = Suspensao.SUSPENSA
        s.save(update_fields=['status'])
    NCCritica.objects.get_or_create(resposta=r, defaults={'suspensao': s})
    auditar(v.avaliador, 'suspensao', 'suspensao', s.pk, f'{eq.tag}: NC {r.codigo} — {r.descricao}',
            vistoria=str(v.uuid), resposta=r.codigo, nova=nova)
    avisos.agendar(avisos.preparar_suspensao(s, r))
    return s


@transaction.atomic
def registrar_adesivo(s: Suspensao, usuario, afixado: bool, justificativa: str = '') -> Suspensao:
    if s.vistoria.avaliador_id != usuario.pk and not usuario.is_superuser:
        raise PermissionDenied('Só o avaliador da vistoria informa o adesivo.')
    if not afixado and not (justificativa or '').strip():
        raise ValidationError({'justificativa': 'Informe por que não foi possível afixar o adesivo.'})
    s.adesivo = Suspensao.ADESIVO_AFIXADO if afixado else Suspensao.ADESIVO_NAO
    s.adesivo_em = timezone.now()
    s.adesivo_justificativa = '' if afixado else justificativa.strip()[:500]
    s.save(update_fields=['adesivo', 'adesivo_em', 'adesivo_justificativa'])
    auditar(usuario, 'adesivo', 'suspensao', s.pk, f'{s.equipamento.tag}: {s.get_adesivo_display()}')
    # o e-mail de suspensão sai na hora; se ainda não saiu (fila), sai com o adesivo informado
    avisos.atualizar_adesivo_pendente(s)
    return s


# ── Conclusão ──────────────────────────────────────────────────────────────────
def pendencias(v: Vistoria) -> list[dict]:
    """Tudo que impede concluir (critério de aceite 4: campo pendente indicado)."""
    p = []
    if v.medicao_tipo != NENHUMA and v.medicao is None:
        p.append({'campo': 'medicao', 'texto': f'Informe o {v.get_medicao_tipo_display().lower()}.'})
    if medicao_menor(v) and not v.medicao_menor_confirmada:
        p.append({'campo': 'medicao', 'texto': 'Confirme o valor menor que o da última vistoria.'})
    if not v.acompanhante_nome.strip():
        p.append({'campo': 'acompanhante_nome', 'texto': 'Informe o nome do funcionário acompanhante.'})
    if not v.acompanhante_cargo.strip():
        p.append({'campo': 'acompanhante_cargo', 'texto': 'Informe o cargo do acompanhante.'})
    fotos = {}
    for e in v.evidencias.filter(finalidade=Evidencia.NC).values('resposta_id'):
        fotos[e['resposta_id']] = fotos.get(e['resposta_id'], 0) + 1
    for r in v.respostas.all():
        if not r.valor:
            p.append({'campo': f'q:{r.codigo}', 'texto': f'{r.codigo} — {r.descricao}: sem resposta.'})
        elif r.valor == Resposta.NC and not r.cancelada:
            if not r.descricao_problema.strip():
                p.append({'campo': f'q:{r.codigo}', 'texto': f'{r.codigo} — {r.descricao}: descreva o problema.'})
            if not fotos.get(r.pk):
                p.append({'campo': f'q:{r.codigo}', 'texto': f'{r.codigo} — {r.descricao}: anexe foto ou vídeo.'})
            if r.criticidade == CRITICA and not r.critica_confirmada_em:
                p.append({'campo': f'q:{r.codigo}', 'texto': f'{r.codigo} — {r.descricao}: confirme a NC crítica.'})
    return p


def calcular_resultado(v: Vistoria, final: bool) -> str:
    ncs = [(r.criticidade, not r.cancelada and not (final and r.abonada))
           for r in v.respostas.all() if r.valor == Resposta.NC]
    return regras.resultado(ncs)


@transaction.atomic
def concluir(v: Vistoria, usuario) -> Vistoria:
    _do_avaliador(v, usuario)
    p = pendencias(v)
    if p:
        raise ValidationError({'pendencias': p, 'detail': 'Há campos pendentes.'})
    v.status = Vistoria.CONCLUIDA
    v.concluida_em = timezone.now()
    v.resultado_inicial = calcular_resultado(v, final=False)
    v.resultado_final = ''
    v.save(update_fields=['status', 'concluida_em', 'resultado_inicial', 'resultado_final', 'atualizada_em'])
    auditar(usuario, 'vistoria_concluir', 'vistoria', v.uuid, f'{v.equipamento.tag}: resultado {v.resultado_inicial}')
    return v


# ── Validação (seção 8) ────────────────────────────────────────────────────────
def _pendente_de_validacao(v: Vistoria):
    if v.status != Vistoria.CONCLUIDA:
        raise ValidationError({'detail': 'Só vistoria concluída e aguardando validação.'})


@transaction.atomic
def abonar(v: Vistoria, usuario, codigo: str, abonar_: bool, justificativa: str = '') -> Resposta:
    _pendente_de_validacao(v)
    r = v.respostas.filter(codigo=codigo).first()
    if r is None or r.valor != Resposta.NC:
        raise ValidationError({'detail': 'Só não conformidades podem ser abonadas.'})
    if not r.permite_abono:
        raise ValidationError({'detail': 'Questão não cadastrada como passível de abono (só NC estética de funilaria e pintura).'})
    if abonar_ and not (justificativa or '').strip():
        raise ValidationError({'justificativa': 'O abono exige justificativa.'})
    r.abonada = abonar_
    r.abono_justificativa = justificativa.strip()[:500] if abonar_ else ''
    r.abonada_por = usuario if abonar_ else None
    r.abonada_em = timezone.now() if abonar_ else None
    r.save(update_fields=['abonada', 'abono_justificativa', 'abonada_por', 'abonada_em'])
    auditar(usuario, 'abono' if abonar_ else 'abono_desfeito', 'vistoria', v.uuid,
            f'{v.equipamento.tag} questão {codigo}: {justificativa}')
    return r


@transaction.atomic
def validar(v: Vistoria, usuario) -> Vistoria:
    _pendente_de_validacao(v)
    v.status = Vistoria.VALIDADA
    v.resultado_final = calcular_resultado(v, final=True)
    v.validada_por = usuario
    v.validada_em = timezone.now()
    v.save(update_fields=['status', 'resultado_final', 'validada_por', 'validada_em', 'atualizada_em'])
    auditar(usuario, 'vistoria_validar', 'vistoria', v.uuid,
            f'{v.equipamento.tag}: inicial {v.resultado_inicial} → final {v.resultado_final}')
    return v


@transaction.atomic
def devolver(v: Vistoria, usuario, justificativa: str) -> Vistoria:
    _pendente_de_validacao(v)
    if not (justificativa or '').strip():
        raise ValidationError({'justificativa': 'Informe o erro de preenchimento.'})
    v.devolucoes.create(justificativa=justificativa.strip()[:500], devolvida_por=usuario)
    v.status = Vistoria.ANDAMENTO
    v.concluida_em = None
    v.resultado_inicial = ''
    v.save(update_fields=['status', 'concluida_em', 'resultado_inicial', 'atualizada_em'])
    v.respostas.filter(abonada=True).update(abonada=False, abono_justificativa='', abonada_por=None, abonada_em=None)
    auditar(usuario, 'vistoria_devolver', 'vistoria', v.uuid, f'{v.equipamento.tag}: {justificativa}')
    return v


@transaction.atomic
def cancelar_critica(v: Vistoria, usuario, codigo: str, justificativa: str) -> Resposta:
    """Só o GEO desfaz uma NC crítica confirmada; manda e-mail de cancelamento aos mesmos destinatários."""
    if not (justificativa or '').strip():
        raise ValidationError({'justificativa': 'Informe a justificativa do cancelamento.'})
    r = v.respostas.select_for_update().filter(codigo=codigo).first()
    if r is None or not r.travada:
        raise ValidationError({'detail': 'Essa questão não tem NC crítica confirmada.'})
    r.cancelada = True
    r.cancelamento_justificativa = justificativa.strip()[:500]
    r.cancelada_por = usuario
    r.cancelada_em = timezone.now()
    r.save(update_fields=['cancelada', 'cancelamento_justificativa', 'cancelada_por', 'cancelada_em'])
    nc = getattr(r, 'nc_critica', None)
    s = nc.suspensao if nc else None
    if nc:
        nc.status = NCCritica.CANCELADA
        nc.save(update_fields=['status'])
        restantes = s.ncs.exclude(status=NCCritica.CANCELADA)
        if not restantes.exists():
            s.status = Suspensao.CANCELADA
            s.encerrada_em = timezone.now()
            s.save(update_fields=['status', 'encerrada_em'])
        else:
            _reavaliar(s)
    # vistoria já concluída: o resultado inicial recalcula (a NC cancelada não conta)
    if v.status != Vistoria.ANDAMENTO:
        v.resultado_inicial = calcular_resultado(v, final=False)
        if v.status == Vistoria.VALIDADA:
            v.resultado_final = calcular_resultado(v, final=True)
        v.save(update_fields=['resultado_inicial', 'resultado_final'])
    auditar(usuario, 'nc_critica_cancelar', 'vistoria', v.uuid, f'{v.equipamento.tag} questão {codigo}: {justificativa}')
    if s is not None:
        avisos.agendar(avisos.preparar_cancelamento(s, r))
    return r


# ── Correção e liberação (9.3) ─────────────────────────────────────────────────
def _reavaliar(s: Suspensao):
    """Todas as NCs com correção registrada (ou validada) → aguardando liberação; senão, suspensa."""
    ativas = s.ncs.exclude(status=NCCritica.CANCELADA)
    novo = Suspensao.AGUARDANDO if ativas.exists() and not ativas.filter(status=NCCritica.PENDENTE).exists() \
        else Suspensao.SUSPENSA
    if s.status != novo and s.aberta:
        s.status = novo
        s.save(update_fields=['status'])


@transaction.atomic
def registrar_correcao(nc: NCCritica, usuario, texto: str) -> NCCritica:
    if not nc.suspensao.aberta:
        raise ValidationError({'detail': 'Suspensão já encerrada.'})
    if nc.status not in (NCCritica.PENDENTE, NCCritica.CORRIGIDA):
        raise ValidationError({'detail': 'Essa NC não aceita correção agora.'})
    if not (texto or '').strip():
        raise ValidationError({'correcao': 'Descreva a correção realizada.'})
    if not nc.evidencias.exists():
        raise ValidationError({'evidencias': 'Anexe a comprovação da correção (foto ou vídeo).'})
    nc.status = NCCritica.CORRIGIDA
    nc.correcao = texto.strip()[:3000]
    nc.corrigida_por = usuario
    nc.corrigida_em = timezone.now()
    nc.save(update_fields=['status', 'correcao', 'corrigida_por', 'corrigida_em'])
    _reavaliar(nc.suspensao)
    auditar(usuario, 'correcao', 'suspensao', nc.suspensao_id, f'{nc.suspensao.equipamento.tag} questão {nc.resposta.codigo}')
    return nc


@transaction.atomic
def rejeitar_correcao(nc: NCCritica, usuario, justificativa: str) -> NCCritica:
    if nc.status != NCCritica.CORRIGIDA:
        raise ValidationError({'detail': 'Só correção registrada pode ser rejeitada.'})
    if not (justificativa or '').strip():
        raise ValidationError({'justificativa': 'Informe o motivo da rejeição.'})
    nc.status = NCCritica.PENDENTE
    nc.rejeicao = justificativa.strip()[:500]
    nc.rejeicoes += 1
    nc.rejeitada_por = usuario
    nc.rejeitada_em = timezone.now()
    nc.save(update_fields=['status', 'rejeicao', 'rejeicoes', 'rejeitada_por', 'rejeitada_em'])
    s = nc.suspensao
    s.status = Suspensao.SUSPENSA
    s.save(update_fields=['status'])
    auditar(usuario, 'correcao_rejeitar', 'suspensao', s.pk, f'{s.equipamento.tag} questão {nc.resposta.codigo}: {justificativa}')
    avisos.agendar(avisos.preparar_rejeicao(s, nc, usuario))
    return nc


@transaction.atomic
def liberar(s: Suspensao, usuario, observacao: str = '') -> Suspensao:
    """Valida todas as correções e libera. Bloqueia se alguma NC crítica não foi corrigida (aceite 6)."""
    if not s.aberta:
        raise ValidationError({'detail': 'Suspensão já encerrada.'})
    ativas = list(s.ncs.exclude(status=NCCritica.CANCELADA).select_related('resposta'))
    faltam = [nc for nc in ativas if nc.status == NCCritica.PENDENTE]
    if faltam:
        raise ValidationError({'detail': 'Liberação bloqueada: há NC crítica sem correção registrada pelo PCM ('
                                         + ', '.join(nc.resposta.codigo for nc in faltam) + ').'})
    agora = timezone.now()
    for nc in ativas:
        if nc.status == NCCritica.CORRIGIDA:
            nc.status = NCCritica.VALIDADA
            nc.validada_por = usuario
            nc.validada_em = agora
            nc.save(update_fields=['status', 'validada_por', 'validada_em'])
    s.status = Suspensao.LIBERADA
    s.liberada_por = usuario
    s.liberada_em = agora
    s.encerrada_em = agora
    s.liberacao_observacao = (observacao or '').strip()[:500]
    s.save(update_fields=['status', 'liberada_por', 'liberada_em', 'encerrada_em', 'liberacao_observacao'])
    auditar(usuario, 'liberacao', 'suspensao', s.pk, f'{s.equipamento.tag} liberado')
    avisos.agendar(avisos.preparar_liberacao(s))
    return s


# ── Impedimento (5.2) ──────────────────────────────────────────────────────────
@transaction.atomic
def registrar_impedimento(item: ProgramaItem, usuario, motivo: str) -> Impedimento:
    if not (motivo or '').strip():
        raise ValidationError({'motivo': 'Informe a justificativa do impedimento.'})
    if item.situacao != ProgramaItem.PROGRAMADA:
        raise ValidationError({'detail': 'Essa vistoria não está programada.'})
    if item.vistorias.exclude(status=Vistoria.ANDAMENTO).exists():
        raise ValidationError({'detail': 'Essa vistoria já foi realizada.'})
    imp = Impedimento.objects.create(item=item, motivo=motivo.strip()[:500], registrado_por=usuario)
    auditar(usuario, 'impedimento', 'programa_item', item.pk, f'{item.equipamento.tag}: {motivo}')
    return imp
