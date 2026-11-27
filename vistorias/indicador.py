"""
Apuração do Indicador (seção 11) a partir do banco.

Mês aberto = prévia, calculada na hora. Mês fechado = ``ResultadoMensal`` congelado.
O recorte (unidade, setor, gerente, tipo) é aplicado com o VÍNCULO DO MÊS, não o cadastro de
hoje: trocar o gerente não leva os resultados passados junto (aceite 8).
"""
from collections import defaultdict
from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import regras
from .models import (Equipamento, FechamentoMensal, FechamentoTrimestral, ProgramaItem, ResultadoMensal, Suspensao,
                     Vistoria)
from .servicos import auditar

CONTA_NO_PROGRAMA = (ProgramaItem.PROGRAMADA, ProgramaItem.DISPENSADA)


class Contexto:
    """Carrega de uma vez o que o ano precisa (sem N+1)."""

    def __init__(self, ano: int, equipamentos=None, hoje: date | None = None):
        self.ano = ano
        self.hoje = hoje or timezone.localdate()
        qs = equipamentos if equipamentos is not None else Equipamento.objects.all()
        self.equipamentos = list(qs.select_related('tipo', 'unidade', 'setor', 'gerente'))
        ids = [e.pk for e in self.equipamentos]
        self.vinculos = defaultdict(list)
        from .models import VinculoEquipamento
        for v in VinculoEquipamento.objects.filter(equipamento_id__in=ids).order_by('desde', 'id'):
            self.vinculos[v.equipamento_id].append(v)
        self.itens = defaultdict(dict)        # eq -> mes -> item (do ano)
        self.primeiro_item = {}               # eq -> lista de chaves de mês com item (todos os anos)
        meses_item = defaultdict(list)
        for it in ProgramaItem.objects.filter(equipamento_id__in=ids).exclude(situacao=ProgramaItem.CANCELADA):
            meses_item[it.equipamento_id].append(regras.chave_mes(it.ano, it.mes))
            if it.ano == ano and it.situacao in CONTA_NO_PROGRAMA:
                self.itens[it.equipamento_id][it.mes] = it
        self.meses_item = {k: sorted(v) for k, v in meses_item.items()}
        _, fim_ano = regras.limites_do_mes(ano, 12)
        self.vistorias = defaultdict(list)    # concluídas até o fim do ano, em ordem
        for v in (Vistoria.objects.filter(equipamento_id__in=ids, status__in=(Vistoria.CONCLUIDA, Vistoria.VALIDADA),
                                          concluida_em__lte=fim_ano).order_by('concluida_em')):
            self.vistorias[v.equipamento_id].append(v)
        ini_ano, _ = regras.limites_do_mes(ano, 1)
        self.suspensoes = defaultdict(list)
        for s in Suspensao.objects.filter(equipamento_id__in=ids, iniciada_em__lte=fim_ano).exclude(status=Suspensao.CANCELADA):
            if s.encerrada_em is None or s.encerrada_em >= ini_ano:
                self.suspensoes[s.equipamento_id].append(s)

    def vinculo(self, eq, quando):
        atual = None
        for v in self.vinculos.get(eq.pk, []):
            if v.desde <= quando:
                atual = v
            else:
                break
        return atual

    def referencia(self, mes):
        """Instante cujo vínculo vale para o mês: o fim dele, ou agora se o mês ainda corre."""
        _, fim = regras.limites_do_mes(self.ano, mes)
        return min(fim, timezone.now())

    def inicio_elegivel(self, eq, quando) -> int | None:
        """Chave do mês a partir do qual entra no Indicador: 1ª vistoria programada depois da (re)ativação."""
        reativado = None
        anterior = None
        for v in self.vinculos.get(eq.pk, []):
            if v.desde > quando:
                break
            if v.ativo and anterior is not None and not anterior.ativo:
                reativado = regras.chave_mes(timezone.localtime(v.desde).year, timezone.localtime(v.desde).month)
            anterior = v
        for k in self.meses_item.get(eq.pk, []):
            if reativado is None or k >= reativado:
                return k
        return None

    def entrada(self, eq, mes) -> tuple[regras.EntradaMes, dict]:
        ref = self.referencia(mes)
        vinc = self.vinculo(eq, ref)
        ativo = vinc.ativo if vinc else eq.ativo
        inicio = self.inicio_elegivel(eq, ref)
        chave = regras.chave_mes(self.ano, mes)
        elegivel = bool(ativo and inicio is not None and chave >= inicio)
        ini, fim = regras.limites_do_mes(self.ano, mes)
        item = self.itens[eq.pk].get(mes)
        prog = None
        if item is not None and item.situacao == ProgramaItem.PROGRAMADA:
            for v in self.vistorias.get(eq.pk, []):
                if v.item_id == item.pk and ini <= v.concluida_em <= fim:
                    prog = v
        ultima = None
        for v in self.vistorias.get(eq.pk, []):
            if v.concluida_em <= fim:
                ultima = v
            else:
                break
        suspenso = any(s.iniciada_em <= fim and (s.encerrada_em is None or s.encerrada_em >= ini)
                       for s in self.suspensoes.get(eq.pk, []))
        e = regras.EntradaMes(
            elegivel=elegivel, item=item.situacao if item else None,
            programada=prog.resultado_vigente if prog else None,
            programada_validada=bool(prog and prog.status == Vistoria.VALIDADA),
            ultima_valida=ultima.resultado_vigente if ultima else None,
            ultima_validada=bool(ultima and ultima.status == Vistoria.VALIDADA),
            suspenso=suspenso)
        origem = prog if (item and item.situacao == ProgramaItem.PROGRAMADA) else (None if item else ultima)
        return e, {'vinculo': vinc, 'item': item, 'vistoria': origem}


def _passa(vinc, eq, filtros: dict) -> bool:
    if not filtros:
        return True
    base = vinc or eq
    for campo in ('unidade', 'setor', 'gerente', 'tipo'):
        alvo = filtros.get(campo)
        if alvo and str(getattr(base, f'{campo}_id')) != str(alvo):
            return False
    return True


def fechamentos(ano: int) -> dict[int, FechamentoMensal]:
    return {f.mes: f for f in FechamentoMensal.objects.filter(ano=ano, status=FechamentoMensal.FECHADO)}


def apurar_ano(ano: int, filtros: dict | None = None, equipamentos=None, meses=None) -> dict:
    """
    Mapa de resultados: uma linha por equipamento, uma célula por mês, mais o Indicador de cada mês
    e de cada trimestre com a memória de cálculo.
    """
    filtros = {k: v for k, v in (filtros or {}).items() if v}
    meses = meses or list(range(1, 13))
    fechados = fechamentos(ano)
    congelados = defaultdict(dict)
    if fechados:
        for r in (ResultadoMensal.objects.filter(ano=ano, vigente=True, mes__in=list(fechados))
                  .select_related('vistoria')):
            congelados[r.equipamento_id][r.mes] = r
    ctx = Contexto(ano, equipamentos)
    linhas = []
    saidas_mes = defaultdict(list)
    memoria = defaultdict(lambda: {'satisfatorios': [], 'dispensados': [], 'nao_satisfatorios': []})
    for eq in ctx.equipamentos:
        celulas = {}
        for mes in meses:
            if (ano, mes) > (ctx.hoje.year, ctx.hoje.month):
                continue
            if mes in fechados:
                r = congelados[eq.pk].get(mes)
                if r is None or not _passa(r, eq, filtros):
                    continue
                s = regras.SaidaMes(resultado=r.resultado, herdado=r.herdado, considerado=r.considerado,
                                    satisfatorio=r.satisfatorio, suspenso=r.suspenso, sem_validacao=r.sem_validacao)
                origem = r.vistoria
                item_id = r.item_id
            else:
                e, info = ctx.entrada(eq, mes)
                if not _passa(info['vinculo'], eq, filtros):
                    continue
                s = regras.classificar_mes(e)
                if s.resultado is None:
                    continue
                origem = info['vistoria']
                item_id = info['item'].pk if info['item'] else None
            saidas_mes[mes].append(s)
            celulas[mes] = {
                'resultado': s.resultado, 'herdado': s.herdado, 'suspenso': s.suspenso,
                'sem_validacao': s.sem_validacao, 'considerado': s.considerado, 'satisfatorio': s.satisfatorio,
                'vistoria': str(origem.uuid) if origem else None,
                'vistoria_data': timezone.localtime(origem.concluida_em).date().isoformat() if origem and origem.concluida_em else None,
                'item': item_id,
            }
            m = memoria[mes]
            rotulo = eq.tag + ('↻' if s.herdado else '')
            if s.resultado == regras.D and not s.considerado:
                m['dispensados'].append(eq.tag)
            elif s.satisfatorio:
                m['satisfatorios'].append(rotulo + (f' (vistoria de {celulas[mes]["vistoria_data"]})' if celulas[mes]['vistoria_data'] else ''))
            elif s.considerado:
                m['nao_satisfatorios'].append(f'{rotulo} {s.resultado}{" suspenso" if s.suspenso else ""}')
        if celulas:
            linhas.append({
                'equipamento': eq.pk, 'tag': eq.tag, 'descricao': eq.descricao, 'periodicidade': eq.periodicidade,
                'tipo': eq.tipo.descricao, 'setor': eq.setor.nome, 'unidade': eq.unidade.sigla,
                'gerente': (eq.gerente.get_full_name() or eq.gerente.username) if eq.gerente else '',
                'celulas': celulas,
            })
    indicadores = {}
    for mes in meses:
        if (ano, mes) > (ctx.hoje.year, ctx.hoje.month):
            continue
        ind = regras.indicador_mensal(saidas_mes.get(mes, []))
        indicadores[mes] = {
            'percentual': float(ind.percentual) if ind.percentual is not None else None,
            'satisfatorios': ind.satisfatorios, 'considerados': ind.considerados, 'elegiveis': ind.elegiveis,
            'dispensados': ind.dispensados, 'fechado': mes in fechados,
            'fechado_em': fechados[mes].fechado_em.isoformat() if mes in fechados else None,
            'prazo_fechamento': regras.quinto_dia_util(ano, mes).isoformat(),
            'memoria': memoria.get(mes, {'satisfatorios': [], 'dispensados': [], 'nao_satisfatorios': []}),
        }
    trimestres = {}
    fech_tri = {f.trimestre: f for f in FechamentoTrimestral.objects.filter(ano=ano)}
    for t in range(1, 5):
        ms = [m for m in regras.meses_do_trimestre(t) if m in indicadores]
        if not ms:
            continue
        vals = [indicadores[m]['percentual'] for m in ms]
        from decimal import Decimal
        tri = regras.indicador_trimestral([Decimal(str(v)) if v is not None else None for v in vals])
        trimestres[t] = {'percentual': float(tri) if tri is not None else None, 'meses': ms, 'mensais': vals,
                         'completo': len(ms) == 3 and all(indicadores[m]['fechado'] for m in ms),
                         'fechado': t in fech_tri,
                         'fechado_em': fech_tri[t].fechado_em.isoformat() if t in fech_tri else None}
    linhas.sort(key=lambda l: l['tag'])
    return {'ano': ano, 'linhas': linhas, 'indicadores': indicadores, 'trimestres': trimestres}


def resumo_por(ano: int, mes: int, campo: str, equipamentos=None, filtros: dict | None = None) -> list[dict]:
    """Indicador do mês por unidade/setor/gerente/tipo, sobre o conjunto de equipamentos (não média)."""
    dados = apurar_ano(ano, filtros, equipamentos=equipamentos, meses=[mes])
    grupos = defaultdict(list)
    nomes = {}
    eqs = {e.pk: e for e in (equipamentos if equipamentos is not None else Equipamento.objects.select_related('unidade', 'setor', 'gerente', 'tipo'))}
    congelados = {r.equipamento_id: r for r in ResultadoMensal.objects.filter(ano=ano, mes=mes, vigente=True)
                  .select_related('unidade', 'setor', 'gerente', 'tipo')}
    ctx = None
    for l in dados['linhas']:
        c = l['celulas'].get(mes)
        if not c:
            continue
        r = congelados.get(l['equipamento'])
        if r is not None:
            base = r
        else:
            ctx = ctx or Contexto(ano, equipamentos)
            eq = eqs.get(l['equipamento'])
            base = ctx.vinculo(eq, ctx.referencia(mes)) or eq
        obj = getattr(base, campo)
        chave = obj.pk if obj else None
        if campo == 'gerente':
            nomes[chave] = (obj.get_full_name() or obj.username) if obj else 'Sem gerente'
        elif campo == 'unidade':
            nomes[chave] = obj.sigla
        elif campo == 'setor':
            nomes[chave] = f'{obj.unidade.sigla} · {obj.nome}' if obj else '—'
        else:
            nomes[chave] = obj.descricao if obj else '—'
        grupos[chave].append(regras.SaidaMes(resultado=c['resultado'], considerado=c['considerado'],
                                             satisfatorio=c['satisfatorio'], suspenso=c['suspenso']))
    saida = []
    for chave, ss in grupos.items():
        ind = regras.indicador_mensal(ss)
        saida.append({'id': chave, 'nome': nomes.get(chave, '—'),
                      'percentual': float(ind.percentual) if ind.percentual is not None else None,
                      'satisfatorios': ind.satisfatorios, 'considerados': ind.considerados})
    saida.sort(key=lambda x: (x['percentual'] is None, x['percentual'] if x['percentual'] is not None else 0, x['nome']))
    return saida


@transaction.atomic
def fechar_mes(ano: int, mes: int, usuario) -> FechamentoMensal:
    if not regras.mes_encerrado(ano, mes):
        raise ValidationError({'detail': 'Só é possível fechar um mês já encerrado.'})
    if FechamentoMensal.objects.filter(ano=ano, mes=mes, status=FechamentoMensal.FECHADO).exists():
        raise ValidationError({'detail': 'Mês já fechado.'})
    ctx = Contexto(ano)
    fech, _ = FechamentoMensal.objects.update_or_create(
        ano=ano, mes=mes, defaults={'status': FechamentoMensal.FECHADO, 'fechado_por': usuario, 'fechado_em': timezone.now()})
    ResultadoMensal.objects.filter(ano=ano, mes=mes, vigente=True).update(vigente=False)
    novos = []
    for eq in ctx.equipamentos:
        e, info = ctx.entrada(eq, mes)
        s = regras.classificar_mes(e)
        if s.resultado is None:
            continue
        v = info['vinculo']
        base = v or eq
        novos.append(ResultadoMensal(
            fechamento=fech, ano=ano, mes=mes, equipamento=eq, unidade_id=base.unidade_id, setor_id=base.setor_id,
            gerente_id=base.gerente_id, tipo_id=base.tipo_id, periodicidade=base.periodicidade,
            resultado=s.resultado, herdado=s.herdado, suspenso=s.suspenso, sem_validacao=s.sem_validacao,
            vistoria=info['vistoria'], item=info['item'], considerado=s.considerado, satisfatorio=s.satisfatorio))
    ResultadoMensal.objects.bulk_create(novos)
    ind = regras.indicador_mensal([regras.SaidaMes(resultado=n.resultado, considerado=n.considerado,
                                                   satisfatorio=n.satisfatorio) for n in novos])
    auditar(usuario, 'fechamento_mes', 'fechamento', fech.pk, f'{regras.NOMES_MES[mes]}/{ano}: '
            f'{ind.percentual if ind.percentual is not None else "N/A"}% ({ind.satisfatorios}/{ind.considerados})')
    return fech


@transaction.atomic
def reabrir_mes(ano: int, mes: int, usuario, justificativa: str) -> FechamentoMensal:
    if not (justificativa or '').strip():
        raise ValidationError({'justificativa': 'A reabertura exige justificativa.'})
    fech = FechamentoMensal.objects.filter(ano=ano, mes=mes, status=FechamentoMensal.FECHADO).first()
    if fech is None:
        raise ValidationError({'detail': 'Mês não está fechado.'})
    t = regras.trimestre_do_mes(mes)
    if FechamentoTrimestral.objects.filter(ano=ano, trimestre=t).exists():
        raise ValidationError({'detail': f'O {t}º trimestre já foi fechado.'})
    fech.status = FechamentoMensal.REABERTO
    fech.reaberto_por = usuario
    fech.reaberto_em = timezone.now()
    fech.justificativa_reabertura = justificativa.strip()[:500]
    fech.save()
    ResultadoMensal.objects.filter(ano=ano, mes=mes, vigente=True).update(vigente=False)
    auditar(usuario, 'reabertura_mes', 'fechamento', fech.pk, f'{regras.NOMES_MES[mes]}/{ano}: {justificativa}')
    return fech


@transaction.atomic
def fechar_trimestre(ano: int, trimestre: int, usuario) -> FechamentoTrimestral:
    meses = regras.meses_do_trimestre(trimestre)
    fechados = set(FechamentoMensal.objects.filter(ano=ano, mes__in=meses, status=FechamentoMensal.FECHADO)
                   .values_list('mes', flat=True))
    faltam = [regras.NOMES_MES[m] for m in meses if m not in fechados]
    if faltam:
        raise ValidationError({'detail': f'Feche antes os meses: {", ".join(faltam)}.'})
    if FechamentoTrimestral.objects.filter(ano=ano, trimestre=trimestre).exists():
        raise ValidationError({'detail': 'Trimestre já fechado.'})
    dados = apurar_ano(ano, meses=meses)
    tri = dados['trimestres'].get(trimestre, {})
    f = FechamentoTrimestral.objects.create(
        ano=ano, trimestre=trimestre, fechado_por=usuario, indicador=tri.get('percentual'),
        resumo={'mensais': {m: dados['indicadores'][m] for m in meses if m in dados['indicadores']}})
    auditar(usuario, 'fechamento_trimestre', 'fechamento', f.pk, f'{trimestre}º trimestre {ano}: {tri.get("percentual")}%')
    return f
