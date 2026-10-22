"""
Lubrificação: consumo de óleo/graxa (baixas do SGA), próximas preventivas por horímetro e as
leituras de horímetro que o SGA guarda erradas. SÓ LEITURA do SGA, como em ``erp.py``.

Onde está cada coisa (levantado em 21/10/2026):

* Lubrificantes = itens dos grupos de almoxarifado ``ESTOQUE.ESTQGALM`` 283 Lubrificante
  (automotivo), 306 Graxa (automotivo), 1838 Graxa (industrial) e 1839 Lubrificante (industrial).
  Pelo NOME não dá: "OLEO" pega óleo de soja e cilindro hidráulico, e "ADITIVO" pega a embalagem da
  argamassa. Unidade em ``ESPECIE`` (2 LT, 3 BD, 5 UN, 7 KG, 8 GL).
* Saída: ``BAIXAESTOQUE`` (BESTSIT 8 ativa, 10 devolução), ``BESTMAN`` = OS de manutenção (0 = sem OS).
* Dois "almoxarifados" por item: a referência de estoque (``QUANTESTOQUETIPOREF``, tipo 0) 0 = GERAL
  e 100 = FABRICA. A nota entra em GERAL; o almoxarifado passa um lote para FABRICA (o lubrificante
  vai para a oficina/lubrificador); no consumo, a quantidade usada VOLTA de FABRICA para GERAL e sai
  a baixa de GERAL para o equipamento. Saldo em FABRICA = entregue e ainda sem baixa. As
  transferências estão em ``MOVESTOQUE`` (MESTQREFTIPO 3, um par −/+ entre MESTQREF 0 e 100);
  1 = nota de entrada, 2 = baixa. Só o automotivo (283/306) usa; o industrial baixa direto.
* Preventivas: ``PLANOMANUTENCAO`` (PMANTPER 1 = horas, PMANPER = período) e
  ``MANUTENCAOPENDENTE``. Esta última é uma FOTO por rodada de cálculo: ``MPENCOD`` é o número da
  rodada (o mesmo para todos os equipamentos), então vale a linha de maior MPENCOD por
  equipamento + plano. Plano cuja última linha é de rodada antiga = o SGA parou de recalcular (é
  daí que saem as "vencidas" de 3 mil horas).
* Escala: o contador de cada equipamento no SGA tem a SUA escala (EH-04 guarda 236170 para
  23.617 h, CF-16 guarda 272700 para 2.727 h, CF-11 guarda em horas). ``MPENRESTHRKM`` já vem em
  horas. A escala certa sai da comparação com o horímetro dos abastecimentos.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from .erp import CACHE_CADASTRO, CACHE_MOVIMENTO, _cacheado, _num, _periodo, _rows, _texto, tag_do_nome

GRUPOS = {283: 'Lubrificante automotivo', 306: 'Graxa automotiva', 1838: 'Graxa industrial', 1839: 'Lubrificante industrial'}
UNIDADES = {2: 'L', 3: 'BD', 5: 'UN', 7: 'kg', 8: 'GL'}
# Do mesmo grupo, mas não é óleo nem graxa (aditivo de radiador, fluido de freio, spray…).
NAO_LUBRIFICANTE = ('ADITIVO', 'ARREFEC', 'RADIADOR', 'FREIO', 'DESENGRIP', 'LIMPEZA', 'GRAFITE EM PO', 'CORTE', 'USINAGEM')

OLEO, GRAXA, OUTROS = 'OLEO', 'GRAXA', 'OUTROS'
CATEGORIAS = {OLEO: 'Óleo', GRAXA: 'Graxa', OUTROS: 'Fluidos e aditivos'}


def categoria(nome: str, grupo: int) -> str:
    n = _texto(nome).upper()
    if any(p in n for p in NAO_LUBRIFICANTE):
        return OUTROS
    if grupo in (306, 1838) or 'GRAXA' in n:
        return GRAXA if 'FLUIDO' not in n else OUTROS
    return OUTROS if 'FLUIDO' in n else OLEO


# ── SGA ──────────────────────────────────────────────────────────────────────────
def produtos() -> list[dict]:
    """Lubrificantes com saída no último ano (a lista do registro de campo), mais usados primeiro."""
    def buscar():
        linhas = _rows("""
            SELECT e.ESTQCOD cod, e.ESTQNOME nome, e.ESTQGALM grupo, e.ESTQESP esp, COUNT(b.BESTCOD) usos
            FROM ESTOQUE e
            JOIN BAIXAESTOQUE b ON b.BESTESTQ = e.ESTQCOD AND b.BESTSIT = 8 AND b.BESTDATA >= :desde
            WHERE e.ESTQGALM IN :grupos AND ISNULL(e.ESTQBLOQ, 'N') <> 'S'
            GROUP BY e.ESTQCOD, e.ESTQNOME, e.ESTQGALM, e.ESTQESP
            ORDER BY COUNT(b.BESTCOD) DESC""",
            expandir=('grupos',), grupos=list(GRUPOS), desde=datetime.now() - timedelta(days=365))
        return [{
            'cod': int(l['cod']), 'nome': _texto(l['nome']), 'grupo': int(l['grupo']),
            'grupo_nome': GRUPOS.get(int(l['grupo']), ''), 'categoria': categoria(l['nome'], int(l['grupo'])),
            'unidade': UNIDADES.get(int(l['esp'] or 0), ''), 'usos': int(l['usos']),
        } for l in linhas]
    fotos = com_foto()
    saldos = {e['cod']: e for e in estoque()}
    return [{**p, 'tem_foto': p['cod'] in fotos,
             'geral': saldos.get(p['cod'], {}).get('geral', 0.0), 'fabrica': saldos.get(p['cod'], {}).get('fabrica', 0.0),
             'custo_medio': saldos.get(p['cod'], {}).get('custo_medio', 0.0)}
            for p in _cacheado('comb:lub:produtos', CACHE_CADASTRO, buscar)]


def baixas(inicio: date, fim: date) -> list[dict]:
    """Saídas de lubrificante do período, com equipamento, centro de custo, OS e custo."""
    de, ate = _periodo(inicio, fim)

    def buscar():
        linhas = _rows("""
            SELECT b.BESTCOD cod, b.BESTDATA data, b.BESTESTQ item, e.ESTQNOME nome, e.ESTQGALM grupo, e.ESTQESP esp,
                   b.BESTQUANT quant, b.BESTCUSTO custo, b.BESTEQP eqp, b.BESTCC cc, b.BESTMAN os, b.BESTSIT sit
            FROM BAIXAESTOQUE b JOIN ESTOQUE e ON e.ESTQCOD = b.BESTESTQ
            WHERE e.ESTQGALM IN :grupos AND b.BESTDATA >= :de AND b.BESTDATA < :ate AND b.BESTSIT IN (8, 10)""",
            expandir=('grupos',), grupos=list(GRUPOS), de=de, ate=ate)
        saida = []
        for l in linhas:
            sinal = -1 if int(l['sit']) == 10 else 1
            grupo = int(l['grupo'])
            saida.append({
                'cod': int(l['cod']), 'data': l['data'].isoformat() if l['data'] else None,
                'item': int(l['item']), 'nome': _texto(l['nome']), 'grupo': grupo,
                'categoria': categoria(l['nome'], grupo), 'unidade': UNIDADES.get(int(l['esp'] or 0), ''),
                'quantidade': sinal * _num(l['quant']), 'custo': sinal * _num(l['custo']),
                'equipamento': int(l['eqp'] or 0) or None, 'centro_custo': int(l['cc'] or 0) or None,
                'os': int(l['os'] or 0) or None,
            })
        return saida
    return _cacheado(f'comb:lub:baixas:{inicio}:{fim}', CACHE_MOVIMENTO, buscar)


def com_foto() -> set[int]:
    """Lubrificantes que têm foto no cadastro do SGA (``ESTOQUEFOTO``, BMP gravado no banco)."""
    def buscar():
        linhas = _rows("""
            SELECT DISTINCT f.ESTQFESTQ cod FROM ESTOQUEFOTO f JOIN ESTOQUE e ON e.ESTQCOD = f.ESTQFESTQ
            WHERE e.ESTQGALM IN :grupos AND f.ESTQFFOTO IS NOT NULL""", expandir=('grupos',), grupos=list(GRUPOS))
        return [int(l['cod']) for l in linhas]
    return set(_cacheado('comb:lub:com_foto', CACHE_CADASTRO, buscar))


def foto_bruta(cod: int) -> bytes | None:
    """Foto do item como está no SGA (BMP de até 4 MB) — só de lubrificante."""
    linhas = _rows("""
        SELECT TOP 1 f.ESTQFFOTO foto FROM ESTOQUEFOTO f JOIN ESTOQUE e ON e.ESTQCOD = f.ESTQFESTQ
        WHERE f.ESTQFESTQ = :cod AND e.ESTQGALM IN :grupos""", expandir=('grupos',), cod=cod, grupos=list(GRUPOS))
    return bytes(linhas[0]['foto']) if linhas and linhas[0]['foto'] else None


REF_GERAL, REF_FABRICA = 0, 100


def estoque() -> list[dict]:
    """Saldo de cada lubrificante em GERAL e em FABRICA (QUANTESTOQUE, empresa 1, tipo 0) e o custo médio."""
    def buscar():
        linhas = _rows("""
            SELECT q.QESTQESTQ item, e.ESTQNOME nome, e.ESTQGALM grupo, e.ESTQESP esp, q.QESTQREF ref,
                   SUM(q.QESTQESTOQUE) saldo,
                   -- Linha de outra filial com saldo zero guarda custo velho (R$ 490/L no 15W-40): pondera pelo saldo.
                   SUM(CASE WHEN q.QESTQESTOQUE > 0 THEN q.QESTQESTOQUE * q.QESTQCUSTO ELSE 0 END) valor,
                   SUM(CASE WHEN q.QESTQESTOQUE > 0 THEN q.QESTQESTOQUE ELSE 0 END) positivo,
                   -- Mínimo/máximo do cadastro de estoque do SGA (vale a linha da matriz, GERAL).
                   MAX(CASE WHEN q.QESTQFIL = 0 THEN q.QESTQESTMIN ELSE 0 END) minimo,
                   MAX(CASE WHEN q.QESTQFIL = 0 THEN q.QESTQESTMAX ELSE 0 END) maximo
            FROM QUANTESTOQUE q JOIN ESTOQUE e ON e.ESTQCOD = q.QESTQESTQ
            WHERE e.ESTQGALM IN :grupos AND q.QESTQEMP = 1 AND q.QESTQTIPO = 0 AND q.QESTQREF IN (0, 100)
            GROUP BY q.QESTQESTQ, e.ESTQNOME, e.ESTQGALM, e.ESTQESP, q.QESTQREF""",
            expandir=('grupos',), grupos=list(GRUPOS))
        itens = {}
        for l in linhas:
            grupo = int(l['grupo'])
            i = itens.setdefault(int(l['item']), {
                'cod': int(l['item']), 'nome': _texto(l['nome']), 'grupo': GRUPOS.get(grupo, ''),
                'categoria': categoria(l['nome'], grupo), 'unidade': UNIDADES.get(int(l['esp'] or 0), ''),
                'geral': 0.0, 'fabrica': 0.0, '_valor': 0.0, '_positivo': 0.0, 'minimo_sga': 0.0, 'maximo_sga': 0.0})
            i['fabrica' if int(l['ref']) == REF_FABRICA else 'geral'] += _num(l['saldo'])
            if int(l['ref']) != REF_FABRICA:
                i['minimo_sga'] = max(i['minimo_sga'], _num(l['minimo']))
                i['maximo_sga'] = max(i['maximo_sga'], _num(l['maximo']))
            i['_valor'] += _num(l['valor'])
            i['_positivo'] += _num(l['positivo'])
        for i in itens.values():
            valor, positivo = i.pop('_valor'), i.pop('_positivo')
            i['custo_medio'] = round(valor / positivo, 4) if positivo else 0.0
        return list(itens.values())
    return _cacheado('comb:lub:estoque:v3', CACHE_MOVIMENTO, buscar)


DIAS_CONSUMO = 90
ATENCAO_FOLGA = 1.25      # até 25% acima do mínimo
ATENCAO_DIAS = 15         # ou chega ao mínimo em menos de 15 dias


def situacao_estoque(estoque_: list[dict], limites: dict[int, dict], consumo: dict[int, float], fotos: set[int]) -> dict:
    """
    Estoque de cada lubrificante contra o mínimo (o do Manager, se a gestão definiu; senão o do SGA).
    Saldo = GERAL + FABRICA (o que está na oficina também está disponível). ``consumo`` = quantidade
    baixada nos últimos ``DIAS_CONSUMO`` dias, por item.
    """
    itens = []
    for e in estoque_:
        lim = limites.get(e['cod'], {})
        if lim.get('ignorar'):
            continue
        minimo = lim['minimo'] if lim.get('minimo') is not None else (e['minimo_sga'] or None)
        maximo = lim['maximo'] if lim.get('maximo') is not None else (e['maximo_sga'] or None)
        saldo = max(e['geral'], 0) + max(e['fabrica'], 0)
        por_dia = max(consumo.get(e['cod'], 0.0), 0.0) / DIAS_CONSUMO
        dias_cobertura = round(saldo / por_dia, 0) if por_dia > 0 else None
        dias_ate_minimo = round((saldo - minimo) / por_dia, 0) if por_dia > 0 and minimo else None
        if not minimo and not por_dia and saldo <= 0:
            continue    # sem uso, sem saldo e sem mínimo: não interessa
        if not minimo:
            situacao = 'SEM_MINIMO'
        elif saldo <= 0:
            situacao = 'ZERADO'
        elif saldo < minimo:
            situacao = 'ABAIXO'
        elif saldo < minimo * ATENCAO_FOLGA or (dias_ate_minimo is not None and dias_ate_minimo < ATENCAO_DIAS):
            situacao = 'ATENCAO'
        else:
            situacao = 'OK'
        # Sugestão de compra: até o máximo; sem máximo cadastrado, até o dobro do mínimo.
        alvo = maximo or ((minimo or 0) * 2)
        repor = round(max(alvo - saldo, 0), 2) if situacao in ('ZERADO', 'ABAIXO', 'ATENCAO') else 0.0
        itens.append({
            'cod': e['cod'], 'nome': e['nome'], 'grupo': e['grupo'], 'categoria': e['categoria'], 'unidade': e['unidade'],
            'geral': e['geral'], 'fabrica': e['fabrica'], 'saldo': round(saldo, 2), 'custo_medio': e['custo_medio'],
            'minimo': minimo, 'maximo': maximo, 'minimo_sga': e['minimo_sga'] or None, 'maximo_sga': e['maximo_sga'] or None,
            'origem_minimo': 'MANAGER' if lim.get('minimo') is not None else ('SGA' if e['minimo_sga'] else None),
            'consumo_dia': round(por_dia, 3), 'dias_cobertura': dias_cobertura, 'dias_ate_minimo': dias_ate_minimo,
            'situacao': situacao, 'repor': repor, 'valor_repor': round(repor * e['custo_medio'], 2),
            'alerta': lim.get('alerta', True), 'observacao': lim.get('observacao', ''), 'tem_foto': e['cod'] in fotos,
        })
    ordem = {'ZERADO': 0, 'ABAIXO': 1, 'ATENCAO': 2, 'OK': 3, 'SEM_MINIMO': 4}
    itens.sort(key=lambda i: (ordem[i['situacao']], i['dias_ate_minimo'] if i['dias_ate_minimo'] is not None else 1e9, i['nome']))
    resumo = {s: sum(1 for i in itens if i['situacao'] == s) for s in ordem}
    resumo['valor_repor'] = round(sum(i['valor_repor'] for i in itens), 2)
    resumo['alertas'] = sum(1 for i in itens if i['situacao'] in ('ZERADO', 'ABAIXO') and i['alerta'])
    return {'resumo': resumo, 'itens': itens, 'dias_consumo': DIAS_CONSUMO}


def transferencias(inicio: date, fim: date) -> dict[int, dict]:
    """Por item: quanto foi de GERAL para FABRICA e quanto voltou de FABRICA (para a baixa) no período."""
    de, ate = _periodo(inicio, fim)

    def buscar():
        linhas = _rows("""
            SELECT m.MESTQESTQ item,
                   SUM(CASE WHEN m.MESTQQUANT > 0 THEN m.MESTQQUANT ELSE 0 END) entrou,
                   SUM(CASE WHEN m.MESTQQUANT < 0 THEN -m.MESTQQUANT ELSE 0 END) saiu,
                   COUNT(*) n
            FROM MOVESTOQUE m JOIN ESTOQUE e ON e.ESTQCOD = m.MESTQESTQ
            WHERE e.ESTQGALM IN :grupos AND m.MESTQREFTIPO = 3 AND m.MESTQTIPO = 0 AND m.MESTQREF = 100
              AND m.MESTQDATA >= :de AND m.MESTQDATA < :ate
            GROUP BY m.MESTQESTQ""", expandir=('grupos',), grupos=list(GRUPOS), de=de, ate=ate)
        return {str(int(l['item'])): {'para_fabrica': _num(l['entrou']), 'da_fabrica': _num(l['saiu']), 'movimentos': int(l['n'])}
                for l in linhas}
    bruto = _cacheado(f'comb:lub:transf:{inicio}:{fim}', CACHE_MOVIMENTO, buscar)
    return {int(k): v for k, v in bruto.items()}


def fabrica(estoque_: list[dict], transf: dict[int, dict]) -> dict:
    """O que está na FABRICA sem baixa (valor pelo custo médio) e o que entrou/voltou no período."""
    itens = []
    tot = {'valor_fabrica': 0.0, 'valor_para_fabrica': 0.0, 'valor_da_fabrica': 0.0, 'valor_geral': 0.0}
    for e in estoque_:
        t = transf.get(e['cod'], {'para_fabrica': 0.0, 'da_fabrica': 0.0, 'movimentos': 0})
        c = e['custo_medio']
        tot['valor_geral'] += max(e['geral'], 0) * c
        tot['valor_fabrica'] += max(e['fabrica'], 0) * c
        tot['valor_para_fabrica'] += t['para_fabrica'] * c
        tot['valor_da_fabrica'] += t['da_fabrica'] * c
        if e['fabrica'] > 0 or t['movimentos']:
            itens.append({**e, **t, 'valor_fabrica': round(max(e['fabrica'], 0) * c, 2)})
    itens.sort(key=lambda i: i['valor_fabrica'], reverse=True)
    return {'totais': {k: round(v, 2) for k, v in tot.items()}, 'itens': itens}


def pendentes() -> dict:
    """Última foto de cada plano por horas (equipamento + plano) e o número da rodada mais recente."""
    def buscar():
        rodada = _rows('SELECT MAX(MPENCOD) r FROM MANUTENCAOPENDENTE')[0]['r']
        linhas = _rows("""
            WITH u AS (
                SELECT p.*, ROW_NUMBER() OVER (PARTITION BY p.MPENEQP, p.MPENPMAN ORDER BY p.MPENCOD DESC) rn
                FROM MANUTENCAOPENDENTE p)
            SELECT u.MPENCOD rodada, u.MPENEQP eqp, u.MPENPMAN plano, pm.PMANNOME plano_nome, pm.PMANPER periodo,
                   pm.PMANCMAN classe, u.MPENULTMAN ult_os, u.MPENULTHRKM ult, u.MPENDTULTHRKM dt_ult,
                   u.MPENULTHRKMREG reg, u.MPENDTULTHRKMREG dt_reg, u.MPENPROXHRKM prox, u.MPENRESTHRKM rest,
                   u.MPENVENCIDA vencida, u.MPENESTIMHRKMDIA por_dia, e.EQPNOME eqp_nome, e.EQPINATIVO inativo
            FROM u JOIN PLANOMANUTENCAO pm ON pm.PMANCOD = u.MPENPMAN
            LEFT JOIN EQUIPAMENTO e ON e.EQPCOD = u.MPENEQP
            WHERE u.rn = 1 AND pm.PMANATIVO = 'S' AND pm.PMANTPER = 1 AND u.MPENEQP IS NOT NULL""")
        return {'rodada': int(rodada or 0), 'planos': [{
            'rodada': int(l['rodada']), 'equipamento': int(l['eqp']), 'plano': int(l['plano']),
            'plano_nome': _texto(l['plano_nome']), 'periodo': _num(l['periodo']), 'classe': int(l['classe'] or 0),
            'ultima_os': int(l['ult_os'] or 0) or None,
            'ultima': _num(l['ult']), 'data_ultima': l['dt_ult'].isoformat() if l['dt_ult'] else None,
            'registro': _num(l['reg']), 'data_registro': l['dt_reg'].isoformat() if l['dt_reg'] else None,
            'proxima': _num(l['prox']), 'restante': _num(l['rest']), 'vencida': _texto(l['vencida']) == 'S',
            'por_dia': _num(l['por_dia']), 'nome': _texto(l['eqp_nome']), 'inativo': _texto(l['inativo']) == 'S',
        } for l in linhas]}
    return _cacheado('comb:lub:pendentes:v2', CACHE_MOVIMENTO, buscar)


# ── Contas ───────────────────────────────────────────────────────────────────────
def _dt(v) -> datetime:
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return d.replace(tzinfo=None)


def _par_ok(ant: dict, atual: dict) -> bool:
    """
    O horímetro andou para a frente num ritmo possível: até 24 h por dia, com folga de 6 h (a hora
    do lançamento nem sempre é a do abastecimento) e 2 h para trás (digitação miúda).
    """
    dias = max((_dt(atual['data']) - _dt(ant['data'])).total_seconds() / 86400, 1 / 24)
    return -2 <= atual['horimetro'] - ant['horimetro'] <= 24 * dias + 6


def _por_equipamento(leituras: list[dict]) -> dict[int, list[dict]]:
    por_eqp = defaultdict(list)
    for l in leituras:
        if l.get('equipamento') and l.get('horimetro') and l.get('data'):
            por_eqp[l['equipamento']].append(l)
    for ls in por_eqp.values():
        ls.sort(key=lambda x: _dt(x['data']))
    return por_eqp


def _confirmadas(ls: list[dict]) -> list[dict]:
    """
    Leituras confirmadas pela vizinha (o par anterior→atual ou atual→seguinte é possível).
    Uma leitura errada isolada fica de fora; horímetro trocado/zerado vale a partir da 2ª leitura
    da série nova (o filtro "só para a frente" travaria para sempre no número antigo).
    """
    ok = set()
    for k in range(1, len(ls)):
        if _par_ok(ls[k - 1], ls[k]):
            ok.update((k - 1, k))
    return [l for k, l in enumerate(ls) if k in ok]


def horimetros(leituras: list[dict]) -> dict[int, dict]:
    """
    Horímetro atual de cada equipamento (a leitura confirmada mais recente) e o ritmo em horas por
    dia nos últimos 45 dias. ``leituras``: [{equipamento, data, horimetro, origem}].
    """
    resultado = {}
    for eqp, ls in _por_equipamento(leituras).items():
        boas = _confirmadas(ls)
        if not boas:
            continue
        ultima = boas[-1]
        # Ritmo só na série atual (depois de uma troca de horímetro a anterior não serve).
        serie = [ultima]
        for l in reversed(boas[:-1]):
            if not _par_ok(l, serie[-1]) or _dt(l['data']) < _dt(ultima['data']) - timedelta(days=45):
                break
            serie.append(l)
        por_dia = None
        if len(serie) >= 2:
            dias = (_dt(serie[0]['data']) - _dt(serie[-1]['data'])).total_seconds() / 86400
            if dias >= 3:
                por_dia = round((serie[0]['horimetro'] - serie[-1]['horimetro']) / dias, 2)
        resultado[eqp] = {'horimetro': ultima['horimetro'], 'data': str(ultima['data']), 'origem': ultima.get('origem', 'SGA'),
                          'por_dia': por_dia}
    return resultado


def horas_no_periodo(leituras: list[dict], inicio: date, fim: date) -> dict[int, float]:
    """Horas trabalhadas no período por equipamento: soma dos avanços possíveis do horímetro."""
    saida = {}
    for eqp, ls in _por_equipamento(leituras).items():
        ls = [l for l in ls if inicio.isoformat() <= str(l['data'])[:10] <= fim.isoformat()]
        horas = sum(b['horimetro'] - a['horimetro'] for a, b in zip(ls, ls[1:]) if _par_ok(a, b))
        if horas > 0:
            saida[eqp] = round(horas, 1)
    return saida


def leituras_suspeitas(leituras: list[dict], equipamentos: dict[int, dict], desde: date) -> list[dict]:
    """Horímetro que volta ou salta mais do que o relógio permite — é o que estraga a preventiva no SGA."""
    achados = []
    for eqp, ls in _por_equipamento(leituras).items():
        for k in range(1, len(ls)):
            ant, atual = ls[k - 1], ls[k]
            if str(atual['data'])[:10] < desde.isoformat() or _par_ok(ant, atual):
                continue
            if -10 < atual['horimetro'] - ant['horimetro'] < 0:
                continue   # poucas horas para trás: digitação, não estraga a preventiva
            dias = max((_dt(atual['data']) - _dt(ant['data'])).total_seconds() / 86400, 1 / 24)
            delta = atual['horimetro'] - ant['horimetro']
            seguinte = ls[k + 1] if k + 1 < len(ls) else None
            if delta < 0:
                # Volta e a série segue dali = horímetro trocado/zerado; volta e retoma o antigo = digitação.
                tipo = 'REINICIOU' if seguinte and _par_ok(atual, seguinte) and atual['horimetro'] < ant['horimetro'] * 0.5 else 'VOLTOU'
            else:
                tipo = 'SALTO'
            info = equipamentos.get(eqp, {})
            achados.append({
                'equipamento': eqp, 'tag': info.get('tag') or tag_do_nome(info.get('nome', '')) or str(eqp),
                'descricao': info.get('descricao', ''), 'data': str(atual['data']), 'tipo': tipo,
                'anterior': ant['horimetro'], 'leitura': atual['horimetro'], 'diferenca': round(delta, 1),
                'dias': round(dias, 1), 'origem': atual.get('origem', 'SGA'),
                'seguinte': seguinte['horimetro'] if seguinte else None,
            })
    achados.sort(key=lambda a: a['data'], reverse=True)
    return achados


ESCALAS = (1, 10, 100, 1000)


def _escala_que_bate(valor: float, referencia: float, tolerancia=0.2):
    """Potência de 10 que leva ``valor`` (contador do SGA) para perto de ``referencia`` (horas)."""
    if not valor or not referencia or referencia <= 0:
        return None
    for f in ESCALAS:
        if abs(valor / f - referencia) <= max(referencia * tolerancia, 50):
            return f
    return None


def _escala_do_plano(p: dict):
    if p['proxima'] <= p['ultima'] or not p['periodo']:
        return None
    razao = (p['proxima'] - p['ultima']) / p['periodo']
    return next((f for f in ESCALAS if abs(razao - f) <= f * 0.05), None)


def preventivas(pend: dict, atuais: dict[int, dict], equipamentos: dict[int, dict], hoje: date) -> list[dict]:
    """
    Próxima preventiva de cada plano por horas, recalculada pelo horímetro que entra no
    abastecimento, com o motivo quando o número do SGA não fecha.
    """
    saida = []
    for p in pend['planos']:
        eqp = p['equipamento']
        info = equipamentos.get(eqp) or {'nome': p.get('nome', ''), 'tag': tag_do_nome(p.get('nome', '')),
                                         'descricao': p.get('nome', '').split(' - ', 1)[-1] if ' - ' in p.get('nome', '') else ''}
        atual = atuais.get(eqp)
        alertas = []
        if p.get('inativo'):
            alertas.append({'codigo': 'EQUIPAMENTO_INATIVO', 'texto': 'Equipamento inativo no SGA com o plano ainda ativo: desative o plano.'})
        if p['rodada'] < pend['rodada']:
            alertas.append({'codigo': 'PARADO', 'texto': 'O SGA parou de recalcular este plano'
                            + (f" (último registro em {p['data_registro'][:10]})" if p['data_registro'] else '')
                            + ': a situação dele no SGA não vale mais.'})
        f_plano = _escala_do_plano(p)
        f_leitura = _escala_que_bate(p['registro'], atual['horimetro']) if atual else None
        if not atual:
            alertas.append({'codigo': 'SEM_LEITURA', 'texto': 'Sem horímetro nos abastecimentos dos últimos 4 meses.'})
        elif not f_leitura:
            alertas.append({'codigo': 'HORIMETRO_DIVERGENTE',
                            'texto': f"O SGA registra {p['registro']:,.0f} no contador e o abastecimento {atual['horimetro']:,.1f} h: "
                                     'não há escala que feche — horímetro trocado ou lançado errado.'.replace(',', '.')})
        if f_plano is None:
            alertas.append({'codigo': 'PROXIMA_INVALIDA', 'texto': 'Próxima do SGA não bate com o período do plano.'})
        elif f_leitura and f_plano != f_leitura:
            alertas.append({'codigo': 'ESCALA', 'texto': f'A próxima do SGA foi calculada em outra escala (×{f_plano} '
                            f'em vez de ×{f_leitura}): o "faltam" do SGA não vale.'})
        f = f_leitura or (None if atual else f_plano)   # leitura que não fecha: não inventa a próxima
        if atual and f_leitura and p['data_registro'] and _dt(p['data_registro']) > _dt(atual['data']) \
                and p['registro'] / f_leitura >= atual['horimetro']:
            # O SGA tem leitura mais nova que a dos abastecimentos (OS, apontamento): vale a dele.
            atual = {**atual, 'horimetro': round(p['registro'] / f_leitura, 1), 'data': p['data_registro'], 'origem': 'SGA (manutenção)'}
        ultima_h = proxima_h = restante = None
        if f:
            ultima_h = round(p['ultima'] / f, 1)
            proxima_h = round(ultima_h + p['periodo'], 1)
            if atual and f_leitura:
                if ultima_h > atual['horimetro'] + p['periodo'] or ultima_h <= 0:
                    alertas.append({'codigo': 'ULTIMA_INVALIDA', 'texto': f'A última preventiva está com horímetro {ultima_h:,.0f} h, '
                                    f"acima do atual ({atual['horimetro']:,.0f} h).".replace(',', '.')})
                    ultima_h = proxima_h = None
                else:
                    restante = round(proxima_h - atual['horimetro'], 1)
        if restante is None and not atual and not any(a['codigo'] == 'PARADO' for a in alertas):
            restante = round(p['restante'], 1)   # sem leitura nossa, o do SGA é o que há
        por_dia = (atual or {}).get('por_dia') or p['por_dia'] or None
        previsao = None
        if restante is not None and por_dia and por_dia > 0 and restante >= 0:
            previsao = (hoje + timedelta(days=int(restante / por_dia))).isoformat()
        if restante is None:
            situacao = 'INDEFINIDA'
        elif restante < 0:
            situacao = 'VENCIDA'
        elif restante <= max(50, p['periodo'] * 0.1):
            situacao = 'PROXIMA'
        else:
            situacao = 'EM_DIA'
        saida.append({
            'equipamento': eqp, 'tag': info.get('tag') or tag_do_nome(info.get('nome', '')) or str(eqp),
            'descricao': info.get('descricao', ''), 'plano': p['plano'], 'plano_nome': p['plano_nome'],
            'periodo': p['periodo'], 'ultima_os': p['ultima_os'], 'data_ultima': p['data_ultima'],
            'ultima_h': ultima_h, 'proxima_h': proxima_h, 'horimetro': (atual or {}).get('horimetro'),
            'data_horimetro': (atual or {}).get('data'), 'origem_horimetro': (atual or {}).get('origem'),
            'por_dia': por_dia, 'restante': restante, 'previsao': previsao, 'situacao': situacao,
            'escala': f, 'sga_restante': round(p['restante'], 1), 'sga_vencida': p['vencida'],
            # Vencida no SGA que não é vencida de verdade (ou não dá para saber): o susto do relatório deles.
            'vencida_fantasma': p['vencida'] and situacao != 'VENCIDA',
            'alertas': alertas,
        })
    ordem = {'VENCIDA': 0, 'PROXIMA': 1, 'EM_DIA': 2, 'INDEFINIDA': 3}
    saida.sort(key=lambda x: (ordem[x['situacao']], x['restante'] if x['restante'] is not None else 1e9))
    return saida


def painel(baixas_: list[dict], horas: dict[int, float], equipamentos: dict[int, dict], campo: list[dict]) -> dict:
    """Consumo e custo de lubrificantes do período por produto, equipamento, categoria e mês."""
    tot = {'custo': 0.0, 'baixas': 0, 'oleo_l': 0.0, 'graxa_kg': 0.0, 'custo_sem_os': 0.0, 'baixas_sem_os': 0,
           'custo_sem_equipamento': 0.0}
    prod, eqps, cats, meses, ccs = {}, {}, defaultdict(float), defaultdict(lambda: defaultdict(float)), defaultdict(float)
    for b in baixas_:
        tot['custo'] += b['custo']
        tot['baixas'] += 1
        litros = b['quantidade'] if b['unidade'] == 'L' else 0.0
        kg = b['quantidade'] if b['unidade'] == 'kg' else 0.0
        if b['categoria'] == OLEO:
            tot['oleo_l'] += litros
        elif b['categoria'] == GRAXA:
            tot['graxa_kg'] += kg
        if not b['os']:
            tot['custo_sem_os'] += b['custo']
            tot['baixas_sem_os'] += 1
        cats[b['categoria']] += b['custo']
        meses[(b['data'] or '')[:7]][b['categoria']] += b['custo']
        p = prod.setdefault(b['item'], {'cod': b['item'], 'nome': b['nome'], 'categoria': b['categoria'],
                                         'grupo': GRUPOS.get(b['grupo'], ''), 'unidade': b['unidade'],
                                         'quantidade': 0.0, 'custo': 0.0, 'baixas': 0, 'sem_os': 0, '_eqp': set()})
        p['quantidade'] += b['quantidade']
        p['custo'] += b['custo']
        p['baixas'] += 1
        p['sem_os'] += 0 if b['os'] else 1
        if b['equipamento']:
            p['_eqp'].add(b['equipamento'])
            info = equipamentos.get(b['equipamento'], {})
            e = eqps.setdefault(b['equipamento'], {
                'equipamento': b['equipamento'], 'tag': info.get('tag') or tag_do_nome(info.get('nome', '')) or str(b['equipamento']),
                'descricao': info.get('descricao', ''), 'custo': 0.0, 'oleo_l': 0.0, 'graxa_kg': 0.0, 'baixas': 0, 'sem_os': 0})
            e['custo'] += b['custo']
            e['oleo_l'] += litros if b['categoria'] == OLEO else 0.0
            e['graxa_kg'] += kg if b['categoria'] == GRAXA else 0.0
            e['baixas'] += 1
            e['sem_os'] += 0 if b['os'] else 1
        else:
            tot['custo_sem_equipamento'] += b['custo']
            ccs[b['centro_custo'] or 0] += b['custo']
    for e in eqps.values():
        h = horas.get(e['equipamento'])
        e['horas'] = h
        e['oleo_l_1000h'] = round(e['oleo_l'] / h * 1000, 1) if h and h >= 20 and e['oleo_l'] else None
        e['custo_hora'] = round(e['custo'] / h, 2) if h and h >= 20 else None
        for k in ('custo', 'oleo_l', 'graxa_kg'):
            e[k] = round(e[k], 2)
    produtos_ = []
    for p in prod.values():
        p['equipamentos'] = len(p.pop('_eqp'))
        p['quantidade'], p['custo'] = round(p['quantidade'], 2), round(p['custo'], 2)
        produtos_.append(p)
    produtos_.sort(key=lambda p: p['custo'], reverse=True)
    campo_tot = defaultdict(lambda: {'registros': 0, 'quantidade': 0.0})
    for c in campo:
        campo_tot[c['tipo']]['registros'] += 1
        campo_tot[c['tipo']]['quantidade'] += float(c['quantidade'])
    return {
        'totais': {k: round(v, 2) if isinstance(v, float) else v for k, v in tot.items()}
                  | {'pct_sem_os': round(tot['custo_sem_os'] / tot['custo'] * 100, 1) if tot['custo'] else 0,
                     'equipamentos': len(eqps)},
        'produtos': produtos_,
        'equipamentos': sorted(eqps.values(), key=lambda e: e['custo'], reverse=True),
        'categorias': [{'categoria': k, 'nome': CATEGORIAS[k], 'custo': round(v, 2)} for k, v in sorted(cats.items(), key=lambda x: -x[1])],
        'meses': [{'mes': m, **{k: round(v, 2) for k, v in vs.items()}} for m, vs in sorted(meses.items()) if m],
        'centros_custo': [{'centro_custo': k or None, 'custo': round(v, 2)} for k, v in sorted(ccs.items(), key=lambda x: -x[1])[:10]],
        'campo': {k: {'registros': v['registros'], 'quantidade': round(v['quantidade'], 2)} for k, v in campo_tot.items()},
    }
