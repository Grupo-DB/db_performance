"""Concorrentes do calcário: quanto cada empresa vende (CFEM) e quem abastece cada município (estimativa).

Fonte: CFEM da ANM (dadosabertos.anm.gov.br/CFEM, arquivo CFEM_Arrecadacao.csv, ~325 MB, latin-1):
Ano, Mês, Processo, AnoDoProcesso, Tipo_PF_PJ, CPF_CNPJ, Substância, UF, CodigoMunicipio, Município,
QuantidadeComercializada, UnidadeDeMedida, ValorRecolhido, DataCriacao. O site barra download automático
(firewall): o arquivo é baixado pelo navegador e importado com `manage.py importar_cfem <arquivo>`.

O que a CFEM diz e o que não diz:
- diz quanto cada mina VENDEU por mês (todo o calcário: agrícola, brita, cal…), não para onde foi;
- tem linhas repetidas idênticas (exportação) e erros de digitação (3,8 trilhões de t) — `limpar`
  corrige a tonelagem pelo valor pago quando a razão R$/t foge muito da mediana da empresa.

Quem abastece cada município é ESTIMADO (modelo gravitacional): o volume de cada unidade se espalha pelos
municípios até RAIO_KM, na proporção da lavoura × 1/(1 + (d/ESCALA_KM)²).
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

SUBSTANCIAS = ('CALC', 'DOLOM', 'CONCHA', 'MARGA')
DESVIO_MAX = 20     # razão R$/t da linha fora de [mediana/20, mediana×20] = tonelagem digitada errada
RAIO_KM = 500      # calcário viaja longe no RS (São Borja fica a ~350 km de Caçapava); o peso cai com a distância
ESCALA_KM = 100


def _num(s: str) -> float:
    try:
        return float((s or '0').strip().replace(',', '.'))  # decimal com vírgula, sem separador de milhar
    except ValueError:
        return 0.0


def ler_cfem(caminho: str | Path, ano_min: int) -> list[dict]:
    """Linhas de calcário a partir de ano_min, sem as repetidas idênticas, em toneladas."""
    saida, vistos = [], set()
    with open(caminho, encoding='latin-1', newline='') as fh:
        for x in csv.DictReader(fh):
            if not any(s in (x.get('Substância') or '').upper() for s in SUBSTANCIAS):
                continue
            try:
                ano, mes = int(x['Ano']), int(x['Mês'])
            except (TypeError, ValueError):
                continue
            if ano < ano_min:
                continue
            chave = tuple(x.values())
            if chave in vistos:
                continue
            vistos.add(chave)
            un = (x.get('UnidadeDeMedida') or '').strip().lower()
            q = _num(x.get('QuantidadeComercializada'))
            if un == 'kg':
                q /= 1000
            elif un != 't':
                continue  # m³ e outras: poucas linhas e sem densidade confiável
            try:
                processo = (int(x['Processo']), int(x['AnoDoProcesso']))
                cod = int(x['CodigoMunicipio'])
            except (TypeError, ValueError):
                processo, cod = None, 0
            saida.append({'cnpj': (x.get('CPF_CNPJ') or '').strip(), 'ano': ano, 'mes': mes, 't': q,
                          'valor': _num(x.get('ValorRecolhido')), 'processo': processo, 'municipio_ibge': cod,
                          'municipio': (x.get('Município') or '').strip().title(), 'uf': (x.get('UF') or '').strip()})
    return saida


def limpar(linhas: list[dict]) -> list[dict]:
    """Corrige a tonelagem de linhas com R$/t absurdo pela mediana da empresa (ou a geral)."""
    razoes = defaultdict(list)
    for l in linhas:
        if l['t'] > 0 and l['valor'] > 0:
            razoes[l['cnpj']].append(l['valor'] / l['t'])
    todas = [r for rs in razoes.values() for r in rs]
    geral = statistics.median(todas) if todas else None
    med = {c: statistics.median(rs) for c, rs in razoes.items() if len(rs) >= 3}
    for l in linhas:
        m = med.get(l['cnpj'], geral)
        if not m or l['valor'] <= 0:
            continue
        r = l['valor'] / l['t'] if l['t'] > 0 else 0
        if r == 0 or r > m * DESVIO_MAX or r < m / DESVIO_MAX:
            l['t'] = l['valor'] / m
            l['corrigida'] = True
    return linhas


def _mes(ano: int, mes: int) -> str:
    return f'{ano:04d}-{mes:02d}'


RAIO_MINA_AGRO_KM = 40


def montar_unidades(linhas: list[dict], processos: dict, titulares_db: list[str],
                    pedreiras_agro: list[dict] | None = None, centroides: dict | None = None) -> list[dict]:
    """Uma unidade por (CNPJ, município da mina). processos: {(num, ano): {'nome', 'uso'}} do SIGMINE.

    Agro é a UNIDADE: a empresa precisa ter lavra de corretivo de solo (pedreiras_agro, com ponto) a até
    RAIO_MINA_AGRO_KM do município da mina. Sem isso, a Mineração Rio do Ouro entrava com 29 Mt de brita e
    cimento de 16 minas. Sem pedreiras/centros, vale a regra da empresa."""
    db = {t.strip().upper() for t in titulares_db}
    # Agro é a EMPRESA: a Cioccari paga CFEM por processos de "brita", mas tem lavras de corretivo.
    nomes_agro = {p['nome'].strip().upper() for p in processos.values() if p['uso'] in ('Corretivo de solo', 'Fertilizantes')}
    nome = {}
    for l in linhas:
        p = processos.get(l['processo']) if l['processo'] else None
        if p:
            nome.setdefault(l['cnpj'], p['nome'])
    agro = {c: n.strip().upper() in nomes_agro for c, n in nome.items()}
    unid: dict[tuple, dict] = {}
    for l in linhas:
        if not l['cnpj'] or not l['municipio_ibge']:
            continue
        u = unid.setdefault((l['cnpj'], l['municipio_ibge']), {
            'cnpj': l['cnpj'], 'municipio_ibge': l['municipio_ibge'], 'municipio': l['municipio'], 'uf': l['uf'],
            'mensal': defaultdict(float)})
        u['mensal'][_mes(l['ano'], l['mes'])] += max(0.0, l['t'])
    ultimo = ultimo_mes_completo(unid.values())
    if not ultimo:
        return []
    a, m = int(ultimo[:4]), int(ultimo[5:])
    janela = [_mes((a * 12 + m - 1 - k) // 12, (a * 12 + m - 1 - k) % 12 + 1) for k in range(24)]
    pontos = defaultdict(list)
    for p in pedreiras_agro or []:
        pontos[p['titular'].strip().upper()].append((float(p['latitude']), float(p['longitude'])))

    def unidade_agro(cnpj: str, ibge: int) -> bool:
        if not agro.get(cnpj):
            return False
        if not pedreiras_agro or not centroides:
            return True
        c, pts = centroides.get(ibge), pontos.get((nome.get(cnpj) or '').strip().upper())
        if not c or not pts:
            return False
        from .geo import distancias_km
        d = distancias_km(c[0], c[1], np.array([x[0] for x in pts]), np.array([x[1] for x in pts]))
        return bool((d <= RAIO_MINA_AGRO_KM).any())

    saida = []
    for (cnpj, ibge), u in unid.items():
        n = nome.get(cnpj) or f'CNPJ {cnpj}'
        saida.append({**u, 'mensal': {k: round(v, 1) for k, v in sorted(u['mensal'].items())},
                      'nome': n[:120], 'agro': unidade_agro(cnpj, ibge), 'da_db': n.strip().upper() in db,
                      't_12m': round(sum(u['mensal'].get(k, 0) for k in janela[:12]), 1),
                      't_12m_anterior': round(sum(u['mensal'].get(k, 0) for k in janela[12:]), 1), 'ate': ultimo})
    return saida


def ultimo_mes_completo(unidades) -> str:
    """Último mês com volume total ≥ 70% da mediana dos 12 meses antes dele: a CFEM chega aos poucos
    (pagamento e declaração atrasam), e os meses mais recentes vêm pela metade."""
    tot: dict[str, float] = defaultdict(float)
    for u in unidades:
        for m, t in u['mensal'].items():
            tot[m] += t
    meses = sorted(m for m, t in tot.items() if t > 0)
    for i in range(len(meses) - 1, -1, -1):
        antes = [tot[m] for m in meses[max(0, i - 12):i]]
        if len(antes) >= 6 and tot[meses[i]] >= 0.7 * statistics.median(antes):
            return meses[i]
    return meses[-1] if meses else ''


def abastecimento(unidades: list[dict], centroides: dict[int, tuple[float, float]], ha: dict[int, float],
                  raio_km: float = RAIO_KM, escala_km: float = ESCALA_KM) -> dict[int, dict[str, float]]:
    """{ibge: {cnpj: t/ano estimadas}}: volume de cada unidade espalhado pelos municípios do raio."""
    from .geo import distancias_km
    ids = np.array([i for i in centroides if ha.get(i, 0) > 0])
    if not len(ids):
        return {}
    lats = np.array([centroides[i][0] for i in ids])
    lngs = np.array([centroides[i][1] for i in ids])
    pesos_ha = np.array([ha[i] for i in ids])
    saida: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for u in unidades:
        c = centroides.get(u['municipio_ibge'])
        if not c or u['t_12m'] <= 0:
            continue
        d = distancias_km(c[0], c[1], lats, lngs)
        w = np.where(d <= raio_km, pesos_ha / (1 + (d / escala_km) ** 2), 0.0)
        tot = w.sum()
        if tot <= 0:
            continue
        x = u['t_12m'] * w / tot
        for k in np.nonzero(x > 0.5)[0]:
            saida[int(ids[k])][u['cnpj']] += float(x[k])
    return {i: dict(v) for i, v in saida.items()}
