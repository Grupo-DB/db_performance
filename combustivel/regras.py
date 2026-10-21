"""
Regras do combustível, sem acesso a banco: recebem listas e devolvem números — assim os
testes não dependem do SGA.

* ``conferir`` — o que o SgaAbastecimento recusaria (e o que só merece atenção), avaliado NA
  HORA do registro: é o que hoje trava no SGA dias depois ("Funcionário não identificado",
  horímetro menor que o anterior, data fora do período).
* ``painel`` — KPIs, série diária, ranking por equipamento e centro de custo, entradas.
* ``anomalias`` — consumo de cada abastecimento (litros ÷ horas desde o anterior) comparado
  com o próprio histórico do equipamento por mediana e MAD: robusto a um ou outro valor
  absurdo e sem "modelo" para treinar.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

from django.utils import timezone

BLOQUEIO, AVISO = 'bloqueio', 'aviso'

LITROS_MAXIMO = 1500          # nenhum equipamento da frota leva mais que isso de uma vez
TOLERANCIA_ENCERRANTE = 0.01  # 1 % (mínimo de 1 litro)
DIAS_RETROATIVO = 7
HORAS_POR_DIA = 24
JANELA_DUPLICIDADE = timedelta(minutes=30)


def _alerta(codigo, nivel, texto):
    return {'codigo': codigo, 'nivel': nivel, 'texto': texto}


def _f(v):
    return float(v) if v is not None else None


def conferir(dados: dict, *, equipamento: dict | None, funcionario: dict | None,
             ultima_leitura: dict | None, saldo_tanque: float | None, recentes: list[dict]) -> list[dict]:
    """
    ``dados``: litros, horimetro, km, encerrante_inicial/final, abastecido_em, foto_bomba, foto_painel.
    ``recentes``: abastecimentos do mesmo equipamento já no Manager ({abastecido_em, horimetro, km}).
    """
    alertas = []
    litros = _f(dados.get('litros')) or 0
    quando = dados.get('abastecido_em') or timezone.now()
    agora = timezone.now()

    # Identificação — sem ela o SGA não baixa nunca (vira tentativa infinita no log).
    if not equipamento:
        alertas.append(_alerta('EQUIPAMENTO_DESCONHECIDO', BLOQUEIO, 'Equipamento não encontrado no SGA.'))
    elif not equipamento.get('integra'):
        alertas.append(_alerta('EQUIPAMENTO_SEM_IDENT', BLOQUEIO,
                               'Equipamento sem identificação de integração no SGA (EQPIDENTIAB).'))
    if not funcionario:
        alertas.append(_alerta('FUNCIONARIO_DESCONHECIDO', BLOQUEIO, 'Funcionário não encontrado no SGA.'))
    elif not funcionario.get('integra'):
        alertas.append(_alerta('FUNCIONARIO_SEM_IDENT', BLOQUEIO,
                               'Funcionário sem identificação de integração no SGA — o SGA recusa '
                               '("Funcionário não identificado"). Cadastre o FUNIDENTIAB dele.'))

    # Data
    if quando > agora + timedelta(minutes=10):
        alertas.append(_alerta('DATA_FUTURA', BLOQUEIO, 'Data/hora no futuro.'))
    elif quando < agora - timedelta(days=DIAS_RETROATIVO):
        alertas.append(_alerta('DATA_ANTIGA', AVISO,
                               f'Registro com mais de {DIAS_RETROATIVO} dias: o mês pode estar fechado no SGA.'))

    # Quantidade
    if litros <= 0:
        alertas.append(_alerta('LITROS_INVALIDO', BLOQUEIO, 'Quantidade precisa ser maior que zero.'))
    elif litros > LITROS_MAXIMO:
        alertas.append(_alerta('LITROS_ALTO', AVISO, f'Mais de {LITROS_MAXIMO} litros num abastecimento.'))
    if saldo_tanque is not None and litros > saldo_tanque > -1:
        alertas.append(_alerta('ACIMA_DO_SALDO', AVISO,
                               f'O tanque tinha {saldo_tanque:,.0f} L no sistema.'.replace(',', '.')))

    # Encerrante da bomba (o contador que só cresce): fim − início tem de dar os litros.
    ini, fim = _f(dados.get('encerrante_inicial')), _f(dados.get('encerrante_final'))
    if ini is not None and fim is not None:
        if fim < ini:
            alertas.append(_alerta('ENCERRANTE_INVERTIDO', BLOQUEIO, 'Encerrante final menor que o inicial.'))
        else:
            diferenca = abs((fim - ini) - litros)
            if diferenca > max(1.0, litros * TOLERANCIA_ENCERRANTE):
                alertas.append(_alerta('ENCERRANTE_DIVERGE', AVISO,
                                       f'Encerrante marca {fim - ini:.2f} L e foram informados {litros:.2f} L.'))

    # Horímetro / km contra a última leitura (SGA ou Manager, a mais recente).
    usa_hr = equipamento.get('usa_horimetro') if equipamento else False
    usa_km = equipamento.get('usa_km') if equipamento else False
    hr, km = _f(dados.get('horimetro')), _f(dados.get('km'))
    if usa_hr and hr is None:
        alertas.append(_alerta('SEM_HORIMETRO', AVISO, 'Equipamento controla horímetro e ele não foi informado.'))
    if usa_km and km is None and not usa_hr:
        alertas.append(_alerta('SEM_KM', AVISO, 'Veículo controla km e ele não foi informado.'))

    anterior = _leitura_anterior(ultima_leitura, recentes, quando)
    if hr is not None and anterior.get('horimetro'):
        ant = anterior['horimetro']
        if hr < ant:
            alertas.append(_alerta('HORIMETRO_REGRESSIVO', BLOQUEIO,
                                   f'Horímetro {hr:g} menor que o anterior ({ant:g}) — o SGA recusa.'))
        elif anterior.get('data'):
            horas = max((quando - anterior['data']).total_seconds() / 3600, 0)
            if hr - ant > horas + HORAS_POR_DIA:
                alertas.append(_alerta('HORIMETRO_SALTO', AVISO,
                                       f'Horímetro andou {hr - ant:g} h em {horas:.0f} h de relógio.'))
    if km is not None and anterior.get('km') and km < anterior['km']:
        alertas.append(_alerta('KM_REGRESSIVO', BLOQUEIO, f'Km {km:g} menor que o anterior ({anterior["km"]:g}).'))

    # Duplicidade: mesmo equipamento abastecido de novo em 30 minutos.
    for r in recentes:
        if r.get('abastecido_em') and abs(r['abastecido_em'] - quando) <= JANELA_DUPLICIDADE:
            alertas.append(_alerta('POSSIVEL_DUPLICIDADE', AVISO, 'Mesmo equipamento abastecido há menos de 30 minutos.'))
            break

    if not dados.get('foto_bomba'):
        alertas.append(_alerta('SEM_FOTO_BOMBA', AVISO, 'Sem foto do visor da bomba.'))
    if not dados.get('foto_painel') and (usa_hr or usa_km):
        alertas.append(_alerta('SEM_FOTO_PAINEL', AVISO, 'Sem foto do painel (horímetro/km).'))
    return alertas


def _leitura_anterior(ultima_erp, recentes, quando) -> dict:
    """A leitura mais recente ANTES deste abastecimento, venha do SGA ou do Manager."""
    candidatas = []
    if ultima_erp:
        data = ultima_erp.get('data')
        if isinstance(data, str):
            data = _data(data)
        candidatas.append({'data': data, 'horimetro': ultima_erp.get('horimetro'), 'km': ultima_erp.get('km')})
    for r in recentes:
        if r.get('abastecido_em') and r['abastecido_em'] < quando:
            candidatas.append({'data': r['abastecido_em'], 'horimetro': _f(r.get('horimetro')), 'km': _f(r.get('km'))})
    candidatas = [c for c in candidatas if c.get('data')]
    if not candidatas:
        return {}
    melhor = {}
    for c in sorted(candidatas, key=lambda c: c['data']):
        if c['data'] < quando:
            melhor = {
                'data': c['data'],
                'horimetro': max(filter(None, [melhor.get('horimetro'), c.get('horimetro')]), default=None),
                'km': max(filter(None, [melhor.get('km'), c.get('km')]), default=None),
            }
    return melhor


def _data(texto):
    if not texto:
        return None
    try:
        d = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return timezone.make_aware(d) if timezone.is_naive(d) else d


def bloqueia(alertas: list[dict]) -> bool:
    return any(a['nivel'] == BLOQUEIO for a in alertas)


# ── Painel ───────────────────────────────────────────────────────────────────────
def painel(baixas: list[dict], entradas: list[dict], leituras: list[dict], equipamentos: dict[int, dict],
           entregas_comboio: list[dict] | None = None) -> dict:
    litros = sum(b['litros'] for b in baixas)
    custo = sum(b['custo'] for b in baixas)
    custo_litro = custo / litros if litros else 0.0
    # Ranking e centros de custo pelo consumo REAL: cada entrega do comboio sai do caminhão e vai
    # para a máquina que recebeu, ao custo médio do período. Os totais não mudam.
    realocadas = []
    for e in entregas_comboio or []:
        cc_destino = e.get('centro_custo') or equipamentos.get(e['equipamento'], {}).get('centro_custo')
        cc_comboio = equipamentos.get(e['comboio'], {}).get('centro_custo')
        valor = e['litros'] * custo_litro
        realocadas.append({'equipamento': e['equipamento'], 'centro_custo': cc_destino, 'litros': e['litros'],
                           'custo': valor, 'comboio': True})
        realocadas.append({'equipamento': e['comboio'], 'centro_custo': cc_comboio, 'litros': -e['litros'],
                           'custo': -valor, 'comboio': True})
    comprados = sum(e['litros'] for e in entradas)
    gasto_compra = sum(e['total'] for e in entradas)

    # Série diária por produto.
    por_dia = defaultdict(lambda: {'litros': 0.0, 'custo': 0.0, 'por_item': defaultdict(float)})
    for b in baixas:
        dia = (b['data'] or '')[:10]
        por_dia[dia]['litros'] += b['litros']
        por_dia[dia]['custo'] += b['custo']
        por_dia[dia]['por_item'][b['item']] += b['litros']
    compras_dia = defaultdict(float)
    for e in entradas:
        compras_dia[e['data']] += e['litros']
    dias = sorted(set(por_dia) | set(compras_dia))
    serie = [{
        'dia': d, 'litros': round(por_dia[d]['litros'], 2), 'custo': round(por_dia[d]['custo'], 2),
        'por_item': {str(k): round(v, 2) for k, v in por_dia[d]['por_item'].items()},
        'entrada': round(compras_dia.get(d, 0.0), 2),
    } for d in dias if d]

    # Horas e km trabalhados no período, pelo horímetro/km dos abastecimentos aceitos.
    leit_eqp = defaultdict(list)
    for l in leituras:
        if l['equipamento']:
            leit_eqp[l['equipamento']].append(l)
    trabalho = {}
    for eqp, ls in leit_eqp.items():
        ls.sort(key=lambda l: l['data'] or '')
        hrs = [l['horimetro'] for l in ls if l['horimetro']]
        kms = [l['km'] for l in ls if l['km']]
        trabalho[eqp] = {
            'horas': (max(hrs) - min(hrs)) if len(hrs) > 1 else None,
            'km': (max(kms) - min(kms)) if len(kms) > 1 else None,
            # Litros que "pagam" esse intervalo: todos menos o primeiro abastecimento (o que
            # encheu o tanque ANTES da primeira leitura do período).
            'litros_intervalo': sum(l['litros'] for l in ls[1:]) if len(ls) > 1 else None,
        }

    eqp_tot = defaultdict(lambda: {'litros': 0.0, 'custo': 0.0, 'abastecimentos': 0, 'via_comboio': 0.0})
    cc_tot = defaultdict(lambda: {'litros': 0.0, 'custo': 0.0})
    origem = defaultdict(lambda: {'litros': 0.0, 'abastecimentos': 0})
    for r_ in realocadas:
        t = eqp_tot[r_['equipamento']]
        t['litros'] += r_['litros']
        t['custo'] += r_['custo']
        if r_['litros'] > 0:
            t['via_comboio'] += r_['litros']
            t['abastecimentos'] += 1
        cc_tot[r_['centro_custo']]['litros'] += r_['litros']
        cc_tot[r_['centro_custo']]['custo'] += r_['custo']
    for b in baixas:
        if b['equipamento']:
            t = eqp_tot[b['equipamento']]
            t['litros'] += b['litros']
            t['custo'] += b['custo']
            t['abastecimentos'] += 1 if b['litros'] > 0 else 0
        cc = b['centro_custo'] or (equipamentos.get(b['equipamento'] or 0, {}).get('centro_custo'))
        cc_tot[cc]['litros'] += b['litros']
        cc_tot[cc]['custo'] += b['custo']
        origem[b['origem']]['litros'] += b['litros']
        origem[b['origem']]['abastecimentos'] += 1 if b['litros'] > 0 else 0

    nomes_cc = {e['centro_custo']: e['centro_custo_nome'] for e in equipamentos.values() if e.get('centro_custo')}
    ranking = []
    for eqp, t in eqp_tot.items():
        info = equipamentos.get(eqp, {})
        tr = trabalho.get(eqp, {})
        li = tr.get('litros_intervalo')
        ranking.append({
            'equipamento': eqp, 'nome': info.get('nome') or f'Equipamento {eqp}', 'placa': info.get('placa', ''),
            'centro_custo_nome': info.get('centro_custo_nome', ''),
            'litros': round(t['litros'], 2), 'custo': round(t['custo'], 2), 'abastecimentos': t['abastecimentos'],
            'via_comboio': round(t['via_comboio'], 2),
            'horas': round(tr['horas'], 1) if tr.get('horas') else None,
            'km': round(tr['km'], 1) if tr.get('km') else None,
            'litros_hora': round(li / tr['horas'], 2) if li and tr.get('horas') else None,
            'km_litro': round(tr['km'] / li, 2) if li and tr.get('km') else None,
        })
    ranking = [r for r in ranking if abs(r['litros']) > 0.01]
    ranking.sort(key=lambda r: r['litros'], reverse=True)

    centros = sorted(({'centro_custo': cc, 'nome': nomes_cc.get(cc) or ('Sem centro de custo' if not cc else f'CC {cc}'),
                       'litros': round(v['litros'], 2), 'custo': round(v['custo'], 2)} for cc, v in cc_tot.items()),
                     key=lambda c: c['litros'], reverse=True)

    return {
        'kpis': {
            'litros': round(litros, 2), 'custo': round(custo, 2),
            'custo_litro': round(custo / litros, 4) if litros else None,
            'comprados': round(comprados, 2), 'gasto_compra': round(gasto_compra, 2),
            'preco_compra': round(gasto_compra / comprados, 4) if comprados else None,
            'abastecimentos': sum(1 for b in baixas if b['litros'] > 0),
            'equipamentos': len(eqp_tot),
            'media_dia': round(litros / max(len(serie), 1), 2),
        },
        'serie': serie,
        'ranking': ranking,
        'centros_custo': centros,
        'origens': {k: {'litros': round(v['litros'], 2), 'abastecimentos': v['abastecimentos']} for k, v in origem.items()},
        'entradas': sorted(entradas, key=lambda e: e['data'] or '', reverse=True),
    }


def anomalias(leituras: list[dict], equipamentos: dict[int, dict], limite=5.0, minimo_amostras=6) -> list[dict]:
    """
    Litros por hora de cada abastecimento contra a mediana do próprio equipamento.
    Escore robusto = |x − mediana| / (1,4826 × MAD); acima de ``limite`` vira alerta.
    """
    por_eqp = defaultdict(list)
    for l in leituras:
        if l['equipamento'] and l['horimetro'] and l['data']:
            por_eqp[l['equipamento']].append(l)
    achados = []
    for eqp, ls in por_eqp.items():
        ls.sort(key=lambda l: l['data'])
        taxas = []
        for ant, atual in zip(ls, ls[1:]):
            horas = atual['horimetro'] - ant['horimetro']
            # Menos de 3 h entre dois abastecimentos é "completar o tanque": os litros não
            # correspondem às horas e qualquer conta por hora sai absurda.
            if 3 <= horas <= 500:
                taxas.append((atual, atual['litros'] / horas, horas))
        if len(taxas) < minimo_amostras:
            continue
        valores = [t[1] for t in taxas]
        med = median(valores)
        mad = median(abs(v - med) for v in valores) or (med * 0.1) or 1
        for leitura, taxa, horas in taxas:
            escore = abs(taxa - med) / (1.4826 * mad)
            if escore >= limite:
                info = equipamentos.get(eqp, {})
                achados.append({
                    'equipamento': eqp, 'nome': info.get('nome') or f'Equipamento {eqp}',
                    'data': leitura['data'], 'litros': leitura['litros'], 'horas': round(horas, 1),
                    'litros_hora': round(taxa, 2), 'mediana': round(med, 2), 'escore': round(escore, 1),
                    'tipo': 'ALTO' if taxa > med else 'BAIXO',
                })
    achados.sort(key=lambda a: a['escore'], reverse=True)
    return achados


def autonomia(saldo: float, serie: list[dict], dias=14) -> float | None:
    """Dias até esvaziar no ritmo dos últimos ``dias`` dias com movimento."""
    recentes = [s['litros'] for s in serie[-dias:] if s['litros'] > 0]
    if not recentes or saldo is None:
        return None
    media = sum(recentes) / len(recentes)
    return round(saldo / media, 1) if media > 0 else None
