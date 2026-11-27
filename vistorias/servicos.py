"""Cadastro, vínculo histórico, programa anual e trilha de auditoria."""
from datetime import date

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import regras
from .models import (Auditoria, Equipamento, Ficha, FichaVersao, Impedimento, ProgramaItem, Questao, Suspensao,
                     VinculoEquipamento, Vistoria)


def auditar(usuario, acao: str, objeto: str = '', objeto_id='', descricao: str = '', **dados):
    Auditoria.objects.create(
        usuario=usuario if getattr(usuario, 'pk', None) else None, acao=acao, objeto=objeto,
        objeto_id=str(objeto_id or ''), descricao=descricao[:300], dados=dados)


# ── Vínculo ────────────────────────────────────────────────────────────────────
CAMPOS_VINCULO = ('unidade_id', 'setor_id', 'gerente_id', 'tipo_id', 'periodicidade', 'ativo')


def registrar_vinculo(eq: Equipamento, usuario=None, quando=None) -> VinculoEquipamento | None:
    """Grava uma linha nova só se algo do vínculo mudou desde a última."""
    ultimo = eq.vinculos.order_by('-desde', '-id').first()
    if ultimo and all(getattr(ultimo, c) == getattr(eq, c) for c in CAMPOS_VINCULO):
        return None
    return VinculoEquipamento.objects.create(
        equipamento=eq, desde=quando or timezone.now(), unidade_id=eq.unidade_id, setor_id=eq.setor_id,
        gerente_id=eq.gerente_id, tipo_id=eq.tipo_id, periodicidade=eq.periodicidade, ativo=eq.ativo,
        alterado_por=usuario if getattr(usuario, 'pk', None) else None)


def vinculo_em(eq: Equipamento, quando, cache: dict | None = None):
    """Vínculo vigente no instante; sem histórico, o cadastro atual."""
    lista = cache.get(eq.pk) if cache is not None else None
    if lista is None:
        lista = list(eq.vinculos.order_by('desde', 'id'))
        if cache is not None:
            cache[eq.pk] = lista
    atual = None
    for v in lista:
        if v.desde <= quando:
            atual = v
        else:
            break
    return atual


# ── Fichas ─────────────────────────────────────────────────────────────────────
CAMPOS_QUESTAO = ('codigo', 'grupo', 'descricao', 'criticidade', 'permite_na', 'permite_abono', 'ordem', 'ativa')


@transaction.atomic
def nova_versao(ficha: Ficha, questoes: list[dict], usuario=None, observacao: str = '') -> FichaVersao:
    """
    Grava a ficha como uma versão nova. Questões não são excluídas: o código que sumir da lista
    volta inativo. Vistorias em andamento seguem na versão em que começaram (guardam a cópia).
    """
    codigos = [str(q.get('codigo', '')).strip() for q in questoes]
    if any(not c for c in codigos):
        raise ValidationError({'questoes': 'Toda questão precisa de código.'})
    if len(set(codigos)) != len(codigos):
        raise ValidationError({'questoes': 'Há códigos de questão repetidos.'})
    for q in questoes:
        if not str(q.get('descricao', '')).strip() or not str(q.get('grupo', '')).strip():
            raise ValidationError({'questoes': f'Questão {q.get("codigo")}: grupo e descrição são obrigatórios.'})
        if q.get('criticidade') not in ('LEVE', 'MEDIA', 'CRITICA'):
            raise ValidationError({'questoes': f'Questão {q.get("codigo")}: criticidade inválida.'})

    anterior = ficha.versao_atual()
    numero = (ficha.versoes.aggregate(m=Max('numero'))['m'] or 0) + 1
    versao = FichaVersao.objects.create(ficha=ficha, numero=numero, criada_por=usuario if getattr(usuario, 'pk', None) else None,
                                        observacao=observacao[:300])
    novos = []
    for i, q in enumerate(questoes):
        novos.append(Questao(
            versao=versao, codigo=str(q['codigo']).strip()[:12], grupo=str(q['grupo']).strip()[:80],
            descricao=str(q['descricao']).strip()[:300], criticidade=q['criticidade'],
            permite_na=bool(q.get('permite_na', True)), permite_abono=bool(q.get('permite_abono', False)),
            ordem=int(q.get('ordem') or (i + 1)), ativa=bool(q.get('ativa', True))))
    if anterior:
        presentes = set(codigos)
        for q in anterior.questoes.all():
            if q.codigo not in presentes:
                novos.append(Questao(versao=versao, **{c: getattr(q, c) for c in CAMPOS_QUESTAO if c != 'ativa'}, ativa=False))
    Questao.objects.bulk_create(novos)
    auditar(usuario, 'ficha_versao', 'ficha', ficha.pk, f'{ficha.nome} v{numero}', questoes=len(novos))
    return versao


# ── Programa ───────────────────────────────────────────────────────────────────
ATIVOS_NO_PROGRAMA = (ProgramaItem.PROGRAMADA, ProgramaItem.DISPENSADA)


def _mes_inicial(ano: int, hoje: date) -> int:
    if ano < hoje.year:
        return 13
    if ano > hoje.year:
        return 1
    return hoje.month


@transaction.atomic
def gerar_programa(ano: int, usuario=None, equipamentos=None, hoje: date | None = None) -> int:
    """
    Cria o que falta do programa do ano conforme a periodicidade (ciclos desde janeiro).
    No ano corrente só cria do mês atual em diante — não inventa atraso no passado.
    Idempotente: quem já tem item no mês fica como está.
    """
    hoje = hoje or timezone.localdate()
    desde = _mes_inicial(ano, hoje)
    qs = equipamentos if equipamentos is not None else Equipamento.objects.filter(ativo=True)
    existentes = set(ProgramaItem.objects.filter(ano=ano).exclude(situacao=ProgramaItem.CANCELADA)
                     .values_list('equipamento_id', 'mes'))
    novos = []
    for eq in qs:
        if not eq.ativo:
            continue
        for m in regras.meses_previstos(eq.periodicidade, desde):
            if (eq.pk, m) not in existentes:
                novos.append(ProgramaItem(equipamento=eq, ano=ano, mes=m))
    ProgramaItem.objects.bulk_create(novos)
    if novos and usuario is not None:
        auditar(usuario, 'programa_gerar', 'programa', ano, f'Programa {ano}: {len(novos)} vistorias criadas', criados=len(novos))
    return len(novos)


@transaction.atomic
def sincronizar_programa(eq: Equipamento, usuario=None, hoje: date | None = None) -> None:
    """
    Depois de mudar periodicidade ou situação: a partir do mês atual, cancela o que não
    pertence mais ao ciclo (só itens sem vistoria e não manuais) e cria o que falta.
    """
    hoje = hoje or timezone.localdate()
    futuros = (ProgramaItem.objects.filter(equipamento=eq, situacao=ProgramaItem.PROGRAMADA, manual=False)
               .filter(ano__gte=hoje.year))
    validos = set(regras.MESES_DO_CICLO.get(eq.periodicidade, [])) if eq.ativo else set()
    for it in futuros:
        if (it.ano, it.mes) < (hoje.year, hoje.month):
            continue
        if it.mes not in validos and not it.vistorias.exists():
            it.situacao = ProgramaItem.CANCELADA
            it.justificativa = 'Cancelada pelo sistema: mudança de periodicidade ou equipamento inativado.'
            it.decidido_em = timezone.now()
            it.save(update_fields=['situacao', 'justificativa', 'decidido_em'])
    if eq.ativo:
        anos = set(ProgramaItem.objects.filter(ano__gte=hoje.year).values_list('ano', flat=True)) | {hoje.year}
        for ano in sorted(anos):
            gerar_programa(ano, None, [eq], hoje)


def item_aberto(eq: Equipamento, ano: int, mes: int) -> ProgramaItem | None:
    return (ProgramaItem.objects.filter(equipamento=eq, ano=ano, mes=mes, situacao__in=ATIVOS_NO_PROGRAMA)
            .order_by('-id').first())


def suspensao_aberta(eq: Equipamento) -> Suspensao | None:
    return eq.suspensoes.filter(status__in=(Suspensao.SUSPENSA, Suspensao.AGUARDANDO)).order_by('-iniciada_em').first()


@transaction.atomic
def dispensar(item: ProgramaItem, usuario, justificativa: str, confirmado: bool = False) -> ProgramaItem:
    justificativa = (justificativa or '').strip()
    if not justificativa:
        raise ValidationError({'justificativa': 'Informe a justificativa da dispensa.'})
    if item.situacao != ProgramaItem.PROGRAMADA:
        raise ValidationError({'detail': 'Só uma vistoria programada pode ser dispensada.'})
    if item.vistorias.exclude(status=Vistoria.ANDAMENTO).exists():
        raise ValidationError({'detail': 'Essa vistoria já foi realizada.'})
    if suspensao_aberta(item.equipamento):
        raise ValidationError({'detail': 'Equipamento com operação suspensa não pode ter vistoria dispensada.'})
    if item.equipamento.periodicidade != 'MENSAL' and not confirmado:
        raise ValidationError({'confirmar': 'A dispensa deve ser aplicada preferencialmente às vistorias mensais. '
                                            'Confirme para dispensar esta vistoria '
                                            f'{item.equipamento.get_periodicidade_display().lower()}.'})
    item.situacao = ProgramaItem.DISPENSADA
    item.justificativa = justificativa[:500]
    item.decidido_por = usuario
    item.decidido_em = timezone.now()
    item.save(update_fields=['situacao', 'justificativa', 'decidido_por', 'decidido_em'])
    item.impedimentos.filter(decisao=Impedimento.PENDENTE).update(
        decisao=Impedimento.DISPENSADA, decidido_por=usuario, decidido_em=timezone.now())
    auditar(usuario, 'dispensa', 'programa_item', item.pk,
            f'{item.equipamento.tag} {regras.NOMES_MES[item.mes]}/{item.ano}: {justificativa}')
    return item


@transaction.atomic
def reprogramar(item: ProgramaItem, usuario, ano: int, mes: int, justificativa: str) -> ProgramaItem:
    justificativa = (justificativa or '').strip()
    if not justificativa:
        raise ValidationError({'justificativa': 'Informe a justificativa da reprogramação.'})
    if item.situacao != ProgramaItem.PROGRAMADA or item.vistorias.exclude(status=Vistoria.ANDAMENTO).exists():
        raise ValidationError({'detail': 'Só uma vistoria programada e ainda não realizada pode ser reprogramada.'})
    if not (1 <= mes <= 12) or (ano, mes) == (item.ano, item.mes):
        raise ValidationError({'mes': 'Escolha outro mês.'})
    if item_aberto(item.equipamento, ano, mes):
        raise ValidationError({'mes': 'Já existe vistoria programada para esse mês.'})
    novo = ProgramaItem.objects.create(equipamento=item.equipamento, ano=ano, mes=mes, origem=item, manual=True,
                                       justificativa=f'Reprogramada de {regras.NOMES_MES[item.mes]}/{item.ano}')
    item.situacao = ProgramaItem.REPROGRAMADA
    item.justificativa = justificativa[:500]
    item.decidido_por = usuario
    item.decidido_em = timezone.now()
    item.save(update_fields=['situacao', 'justificativa', 'decidido_por', 'decidido_em'])
    # vistoria em andamento acompanha o item novo
    item.vistorias.filter(status=Vistoria.ANDAMENTO).update(item=novo)
    item.impedimentos.filter(decisao=Impedimento.PENDENTE).update(
        decisao=Impedimento.REPROGRAMADA, decidido_por=usuario, decidido_em=timezone.now())
    auditar(usuario, 'reprogramacao', 'programa_item', item.pk,
            f'{item.equipamento.tag} {regras.NOMES_MES[item.mes]}/{item.ano} → {regras.NOMES_MES[mes]}/{ano}: {justificativa}')
    return novo


def situacao_item(item: ProgramaItem, vistorias: list, impedimentos: list, hoje: date | None = None) -> dict:
    """
    Célula do mapa (5.4): R realizada e validada · V aguardando validação · E em andamento ·
    P programada · A atrasada · I impedimento registrado · D dispensada · X reprogramada.
    """
    hoje = hoje or timezone.localdate()
    if item.situacao == ProgramaItem.DISPENSADA:
        return {'codigo': 'D'}
    if item.situacao == ProgramaItem.REPROGRAMADA:
        return {'codigo': 'X'}
    concl = [v for v in vistorias if v.status in (Vistoria.CONCLUIDA, Vistoria.VALIDADA)]
    vencida = regras.mes_encerrado(item.ano, item.mes, hoje)
    if concl:
        v = max(concl, key=lambda x: x.concluida_em)
        fora = (v.concluida_em and (timezone.localtime(v.concluida_em).year, timezone.localtime(v.concluida_em).month)
                != (item.ano, item.mes))
        return {'codigo': 'R' if v.status == Vistoria.VALIDADA else 'V', 'vistoria': str(v.uuid),
                'resultado': v.resultado_vigente, 'fora_do_prazo': bool(fora)}
    pend = [i for i in impedimentos if i.decisao == Impedimento.PENDENTE]
    andamento = [v for v in vistorias if v.status == Vistoria.ANDAMENTO]
    if pend:
        return {'codigo': 'I', 'impedimento': pend[0].pk, 'atrasada': vencida}
    if vencida:
        return {'codigo': 'A', 'vistoria': str(andamento[0].uuid) if andamento else None}
    if andamento:
        return {'codigo': 'E', 'vistoria': str(andamento[0].uuid)}
    return {'codigo': 'P'}
