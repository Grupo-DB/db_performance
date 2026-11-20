"""Dados públicos do campo para o Comercial Agro (pedido de 19/11/2026: "implemente os 3").

1. Mercado por município: IBGE/PAM (área plantada por cultura) × dose ÷ ciclo = potencial em
   t/ano, comparado com o vendido no SGA (cidade do cliente → CIDADE.CIDCODIBGE).
2. Imóvel do produtor: o ponto do check-in cai num polígono do CAR/SICAR → área do imóvel e,
   com o MapBiomas, quanto dele é lavoura.
3. Prospecção: imóveis do CAR de um município, com % de lavoura, cruzados com quem já tem
   contato no app ou compra no SGA.

Fontes (testadas em 19/11/2026):
- SIDRA: https://apisidra.ibge.gov.br/values/t/5457/... (v 8331 = área plantada, c782 = cultura).
- Malha municipal do RS: servicodados.ibge.gov.br/api/v3/malhas/estados/43 (GeoJSON).
- CAR: WFS público geoserver.car.gov.br, camada sicar:sicar_imoveis_rs (cod_imovel, area,
  cod_municipio_ibge, m_fiscal, geo_area_imovel). Sem nome nem CPF do dono.
- MapBiomas: o download direto do bucket público dá 403; o recorte do RS em GeoTIFF é baixado
  pela plataforma e convertido uma vez com `manage.py importar_mapbiomas` (precisa de rasterio
  só onde a conversão roda) num bitmap de lavoura de 1 bit/pixel (.npy, ~90 MB para o RS a 30 m),
  lido aqui por janela com numpy (mmap), sem rasterio.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import requests
import requests.adapters
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

TIMEOUT = 60
UF_IBGE = 43

# ── 1. IBGE/PAM ─────────────────────────────────────────────────────────────

# Culturas que recebem calcário (código da classificação 782 do SIDRA → rótulo). As 8 primeiras
# são as do RS; cana, algodão, feijão e café entraram com a visão do Brasil (19/11/2026) e ficam
# fora do cenário até alguém marcar.
CULTURAS_PAM = {
    40124: 'Soja', 40122: 'Milho', 40127: 'Trigo', 40102: 'Arroz', 40103: 'Aveia',
    40109: 'Cevada', 83390: 'Canola', 40125: 'Sorgo',
    40106: 'Cana-de-açúcar', 40099: 'Algodão', 40112: 'Feijão', 40139: 'Café',
}
UFS = {
    11: ('RO', 'Rondônia'), 12: ('AC', 'Acre'), 13: ('AM', 'Amazonas'), 14: ('RR', 'Roraima'), 15: ('PA', 'Pará'),
    16: ('AP', 'Amapá'), 17: ('TO', 'Tocantins'), 21: ('MA', 'Maranhão'), 22: ('PI', 'Piauí'), 23: ('CE', 'Ceará'),
    24: ('RN', 'Rio Grande do Norte'), 25: ('PB', 'Paraíba'), 26: ('PE', 'Pernambuco'), 27: ('AL', 'Alagoas'),
    28: ('SE', 'Sergipe'), 29: ('BA', 'Bahia'), 31: ('MG', 'Minas Gerais'), 32: ('ES', 'Espírito Santo'),
    33: ('RJ', 'Rio de Janeiro'), 35: ('SP', 'São Paulo'), 41: ('PR', 'Paraná'), 42: ('SC', 'Santa Catarina'),
    43: ('RS', 'Rio Grande do Sul'), 50: ('MS', 'Mato Grosso do Sul'), 51: ('MT', 'Mato Grosso'), 52: ('GO', 'Goiás'),
    53: ('DF', 'Distrito Federal'),
}
# Calagem média para o potencial do município: 2 t/ha a cada 4 anos = 0,5 t/ha/ano.
DOSE_T_HA = 2.0
CICLO_ANOS = 4

# Brasil inteiro, uma cultura por chamada (~5.570 valores, ~1 s cada; o SIDRA corta em 50 mil valores).
SIDRA_URL = 'https://apisidra.ibge.gov.br/values/t/5457/n6/all/v/8331/p/{periodo}/c782/{cultura}?formato=json'
MALHA_UFS_URL = ('https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR'
                 '?intrarregiao=UF&formato=application/vnd.geo%2Bjson&qualidade=minima')
MALHA_URL = ('https://servicodados.ibge.gov.br/api/v3/malhas/estados/{uf}'
             '?intrarregiao=municipio&formato=application/vnd.geo%2Bjson&qualidade=minima')
MUNICIPIOS_URL = 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios'


def baixar_pam(periodo: str = 'last 1') -> list[dict]:
    """Linhas {ano, municipio_ibge, municipio, cultura, hectares} do SIDRA, Brasil inteiro (sem as vazias '-', '...')."""
    linhas = []
    for cod in CULTURAS_PAM:
        r = requests.get(SIDRA_URL.format(periodo=periodo.replace(' ', '%20'), cultura=cod), timeout=TIMEOUT)
        r.raise_for_status()
        linhas += ler_pam(r.json())
    return linhas


def ler_pam(dados: list[dict]) -> list[dict]:
    linhas = []
    for d in dados[1:]:  # a primeira linha é o cabeçalho
        try:
            ha = float(d['V'])
        except (TypeError, ValueError):
            continue  # '-' (zero), '...' (sem dado), 'X' (sigilo)
        if ha <= 0:
            continue
        linhas.append({'ano': int(d['D3C']), 'municipio_ibge': int(d['D1C']),
                       'municipio': d['D1N'].rsplit(' - ', 1)[0], 'cultura': CULTURAS_PAM.get(int(d['D4C']), d['D4N']),
                       'hectares': ha})
    return linhas


def potencial_t(hectares: float, dose: float = DOSE_T_HA, ciclo: int = CICLO_ANOS) -> float:
    return round(hectares * dose / ciclo, 1)


def malha_rs() -> dict:
    return malha(UF_IBGE)


def malha(uf: int | None) -> dict:
    """GeoJSON dos municípios da UF (IBGE, qualidade mínima, ~250 kB no RS) ou, com `uf=None`, dos 27
    estados (~100 kB); `properties.ibge` = código do município ou da UF. Cache de 30 dias."""
    chave = f'comercialAgro:malha:{uf or "BR"}'
    m = cache.get(chave)
    if m is None:
        r = requests.get(MALHA_URL.format(uf=uf) if uf else MALHA_UFS_URL, timeout=TIMEOUT)
        r.raise_for_status()
        m = r.json()
        for f in m.get('features', []):
            f['properties'] = {'ibge': int(f['properties'].get('codarea'))}
            f['geometry'] = _arredondar(f['geometry'], 4)
        cache.set(chave, m, 30 * 86400)
    return m


def municipios_rs() -> dict[int, str]:
    return municipios(UF_IBGE)


def municipios(uf: int) -> dict[int, str]:
    chave = f'comercialAgro:municipios:{uf}'
    m = cache.get(chave)
    if m is None:
        r = requests.get(MUNICIPIOS_URL.format(uf=uf), timeout=TIMEOUT)
        r.raise_for_status()
        m = {int(x['id']): x['nome'] for x in r.json()}
        cache.set(chave, m, 30 * 86400)
    return m


# ── Área real: milho 2ª safra (IBGE 839) e pastagem (Censo Agro 2017, IBGE 6881) ─────────────

SIDRA_MILHO_2A = ('https://apisidra.ibge.gov.br/values/t/839/n6/all/v/109/p/{periodo}/c81/114254?formato=json')
# Censo 2017: área dos estabelecimentos por utilização das terras (só pastagem plantada; a natural quase não recebe calcário).
SIDRA_PASTAGEM = ('https://apisidra.ibge.gov.br/values/t/6881/n6/all/v/184/p/all/c829/46302/c222/{categoria}'
                  '/c218/46502/c12517/113601/c12567/41151?formato=json')
PASTAGENS = {40678: 'Pastagem degradada', 113469: 'Pastagem boa'}
MILHO_2A = 'Milho 2ª safra'


def _linhas_sidra(dados: list[dict], cultura: str, cod_coluna: str = 'D3C') -> list[dict]:
    linhas = []
    for d in dados[1:]:
        try:
            ha = float(d['V'])
        except (TypeError, ValueError):
            continue
        if ha > 0:
            linhas.append({'ano': int(d[cod_coluna]), 'municipio_ibge': int(d['D1C']),
                           'municipio': d['D1N'].rsplit(' - ', 1)[0], 'cultura': cultura, 'hectares': ha})
    return linhas


def baixar_milho_2a(periodo: str = 'last 1') -> list[dict]:
    """Milho 2ª safra (safrinha) por município — ~1 s. Vai para o grupo de inverno do cenário."""
    r = requests.get(SIDRA_MILHO_2A.format(periodo=periodo.replace(' ', '%20')), timeout=TIMEOUT)
    r.raise_for_status()
    return _linhas_sidra(r.json(), MILHO_2A)


def baixar_pastagem() -> list[dict]:
    """Pastagem plantada (boa e degradada) do Censo 2017 — ~1 min por categoria; roda no importar_pam."""
    linhas = []
    for cod, nome in PASTAGENS.items():
        r = requests.get(SIDRA_PASTAGEM.format(categoria=cod), timeout=300)
        r.raise_for_status()
        linhas += _linhas_sidra(r.json(), nome)
    return linhas


def separar_milho(linhas: list[dict]) -> list[dict]:
    """O PAM traz o milho total; com a 2ª safra baixada, "Milho" passa a ser só a 1ª (verão)."""
    safrinha = {(l['ano'], l['municipio_ibge']): l['hectares'] for l in linhas if l['cultura'] == MILHO_2A}
    for l in linhas:
        if l['cultura'] == 'Milho':
            l['hectares'] = max(0.0, l['hectares'] - safrinha.get((l['ano'], l['municipio_ibge']), 0.0))
    return [l for l in linhas if l['hectares'] > 0]


# ── Centro de cada município (para raio de concorrência e de revenda) ────────────────────────────

MALHA_MUN_BR_URL = ('https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR'
                    '?intrarregiao=municipio&formato=application/vnd.geo%2Bjson&qualidade=minima')


def centroides_municipios() -> dict[int, tuple[float, float]]:
    """{ibge: (lat, lng)} dos 5.570 municípios; calculado uma vez da malha do IBGE e guardado em arquivo."""
    m = cache.get('comercialAgro:centroides')
    if m is not None:
        return m
    arq = pasta_mapas().parent / 'centroides_municipios.json'
    if arq.exists():
        m = {int(k): tuple(v) for k, v in json.loads(arq.read_text()).items()}
    else:
        r = requests.get(MALHA_MUN_BR_URL, timeout=TIMEOUT)
        r.raise_for_status()
        m = {int(f['properties']['codarea']): tuple(round(x, 4) for x in centroide(f['geometry']))
             for f in r.json().get('features', []) if f.get('geometry')}
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(json.dumps({str(k): v for k, v in m.items()}))
    cache.set('comercialAgro:centroides', m, 30 * 86400)
    return m


def distancias_km(lat: float, lng: float, lats: np.ndarray, lngs: np.ndarray) -> np.ndarray:
    """Distância em linha reta (haversine) de um ponto a vários."""
    p1, p2 = np.radians(lat), np.radians(lats)
    dl = np.radians(lngs - lng)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


# ── Concorrência: lavras de calcário agrícola na ANM (SIGMINE) ───────────────────────────────────

ANM_URL = 'https://geo.anm.gov.br/arcgis/rest/services/SIGMINE/dados_anm/MapServer/0/query'
ANM_FILTRO = ("USO IN ('Corretivo de solo','Fertilizantes') AND FASE IN ('CONCESSÃO DE LAVRA','LICENCIAMENTO') "
              "AND (SUBS LIKE '%CALC%' OR SUBS LIKE '%DOLOM%' OR SUBS LIKE '%CONCHA%')")
# O geo.anm.gov.br não manda o certificado intermediário da Sectigo (20/11/2026): sem ele a
# verificação falha. Vai junto do projeto (válido até 2036) e é somado ao bundle do certifi —
# a verificação continua ligada.
ANM_INTERMEDIARIO = Path(__file__).resolve().parent / 'certs' / 'sectigo_public_server_auth_ca_ov_r36.pem'
BRASIL_RAIOS_KM = (50, 100, 150, 200, 300)

# Consumo aparente de calcário agrícola por UF (t), ABRACAL "Calcário agrícola Brasil – 2025"
# (abracal.com.br/site/estatisticas, publicado em 27/04/2026). As outras 17 UFs vêm só somadas.
ABRACAL_ANO = 2025
CONSUMO_ABRACAL = {51: 13_710_700, 52: 9_125_400, 31: 7_058_900, 41: 5_066_400, 50: 4_952_000,
                   35: 4_786_400, 17: 4_303_300, 43: 3_760_400, 42: 1_351_900, 29: 1_122_800}
ABRACAL_OUTROS_T = 6_065_900


def _ca_anm() -> str:
    import certifi
    import tempfile
    destino = Path(tempfile.gettempdir()) / 'comercialAgro_anm_ca.pem'
    if not destino.exists():
        destino.write_text(Path(certifi.where()).read_text() + '\n' + ANM_INTERMEDIARIO.read_text())
    return str(destino)


def baixar_processos_calcario() -> dict[tuple[int, int], dict]:
    """Todos os processos de calcário na ANM (qualquer fase e uso, ~8.900): (número, ano) → titular e uso.
    Liga a CFEM (que só tem CNPJ e processo) ao nome da empresa."""
    onde = "(SUBS LIKE '%CALC%' OR SUBS LIKE '%DOLOM%' OR SUBS LIKE '%CONCHA%' OR SUBS LIKE '%MARGA%')"
    saida, inicio = {}, 0
    while True:
        r = requests.get(ANM_URL, params={'where': onde, 'outFields': 'PROCESSO,NOME,USO', 'returnGeometry': 'false',
                                          'orderByFields': 'OBJECTID', 'resultOffset': inicio, 'resultRecordCount': 2000,
                                          'f': 'json'}, timeout=TIMEOUT, verify=_ca_anm())
        r.raise_for_status()
        d = r.json()
        if 'error' in d:
            raise RuntimeError(d['error'])
        feats = d.get('features', [])
        for f in feats:
            a = f['attributes']
            try:
                n, ano = (int(x) for x in str(a['PROCESSO']).split('/'))
            except (ValueError, AttributeError):
                continue
            saida[(n, ano)] = {'nome': (a.get('NOME') or '').strip(), 'uso': a.get('USO') or ''}
        inicio += len(feats)
        if not d.get('exceededTransferLimit') or not feats:
            return saida


def baixar_pedreiras() -> list[dict]:
    """Lavras ativas de calcário agrícola no Brasil (~540, 1 s). Ponto = média do 1º anel do polígono."""
    r = requests.get(ANM_URL, params={
        'where': ANM_FILTRO, 'outFields': 'PROCESSO,FASE,NOME,SUBS,UF,AREA_HA', 'returnGeometry': 'true',
        'outSR': 4326, 'geometryPrecision': 5, 'f': 'json'}, timeout=TIMEOUT, verify=_ca_anm())
    r.raise_for_status()
    d = r.json()
    if 'error' in d:
        raise RuntimeError(d['error'])
    saida = []
    for f in d.get('features', []):
        a, g = f.get('attributes', {}), f.get('geometry') or {}
        anel = (g.get('rings') or [[]])[0]
        if not anel:
            continue
        pts = np.asarray(anel, dtype=float)
        saida.append({'processo': a['PROCESSO'], 'fase': (a.get('FASE') or '')[:40], 'titular': (a.get('NOME') or '')[:120],
                      'substancia': (a.get('SUBS') or '')[:60], 'uf': (a.get('UF') or '')[:2],
                      'area_ha': round(float(a.get('AREA_HA') or 0), 2),
                      'latitude': round(float(pts[:, 1].mean()), 5), 'longitude': round(float(pts[:, 0].mean()), 5)})
    return saida


# ── 2/3. CAR/SICAR ──────────────────────────────────────────────────────────

CAR_WFS = 'https://geoserver.car.gov.br/geoserver/sicar/wfs'
CAR_CAMADA = 'sicar:sicar_imoveis_rs'  # uma camada por UF: sicar_imoveis_ac … sicar_imoveis_to (27, conferido 19/11/2026)


def camada_car(uf: int | None) -> str:
    sigla = UFS.get(int(uf or 0), ('RS', ''))[0]
    return f'sicar:sicar_imoveis_{sigla.lower()}'


def uf_do_codigo_car(codigo: str) -> int:
    """O código do CAR começa pela sigla da UF ("RS-4303004-…")."""
    sigla = (codigo or '')[:2].upper()
    return next((c for c, (s, _) in UFS.items() if s == sigla), UF_IBGE)


def uf_do_ponto(lat: float, lng: float) -> int | None:
    """UF que contém o ponto, pela malha dos estados do IBGE (cache de 30 dias)."""
    px, py = np.array([float(lng)]), np.array([float(lat)])
    for f in malha(None).get('features', []):
        if dentro(px, py, f['geometry'])[0]:
            return int(f['properties']['ibge'])
    return None
CAR_PAGINA = 1000

# O servidor do CAR (19/11/2026) só negocia TLS 1.2 com troca de chave RSA (AES256-GCM-SHA384,
# AES256-SHA256, AES128-SHA); recusa ECDHE/DHE. O urllib3 2.x recente tirou essas cifras da lista
# padrão, e na VM dava "SSLV3_ALERT_HANDSHAKE_FAILURE" (o curl passava). Acrescenta só essas,
# só para o CAR, e mantém a verificação do certificado.
CIFRAS_CAR = 'DEFAULT:AES256-GCM-SHA384:AES128-GCM-SHA256:AES256-SHA256:AES128-SHA256:AES256-SHA:AES128-SHA'


class _AdaptadorCar(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        import ssl
        ctx = ssl.create_default_context()
        ctx.set_ciphers(CIFRAS_CAR)
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


_sessao_car = None


def _sessao() -> requests.Session:
    global _sessao_car
    if _sessao_car is None:
        s = requests.Session()
        s.mount('https://geoserver.car.gov.br', _AdaptadorCar())
        _sessao_car = s
    return _sessao_car


def _wfs(cql: str, count: int, start: int = 0, versao: str = '2.0.0', uf: int | None = None) -> dict:
    """GetFeature no WFS do CAR. Filtro com coordenada vai na versão 1.0.0: na 2.0.0 o POINT do
    CQL é lido como (lat lng), mas o GeoJSON de saída vem (lng lat) — testado em 19/11/2026."""
    r = _sessao().get(CAR_WFS, params={
        'service': 'WFS', 'version': versao, 'request': 'GetFeature', 'typeNames': camada_car(uf), 'typeName': camada_car(uf),
        'outputFormat': 'application/json', 'count': count, 'maxFeatures': count, 'startIndex': start, 'CQL_FILTER': cql,
    }, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def car_no_ponto(lat: float, lng: float) -> dict | None:
    """Imóvel do CAR que contém o ponto (o maior, se houver sobreposição de declarações), na camada da UF do ponto."""
    try:
        uf = uf_do_ponto(lat, lng)
    except Exception as exc:  # malha do IBGE fora: tenta o RS
        logger.warning('Comercial Agro: UF do ponto sem a malha: %s', exc)
        uf = UF_IBGE
    if uf is None:
        return None  # fora do Brasil (ou no mar)
    fc = _wfs(f'INTERSECTS(geo_area_imovel,POINT({float(lng):.6f} {float(lat):.6f}))', 10, versao='1.0.0', uf=uf)
    feats = [imovel(f) for f in fc.get('features', []) if f.get('geometry')]
    feats = [f for f in feats if f['status'] != 'CA']  # cancelado
    return max(feats, key=lambda f: f['area_ha']) if feats else None


def car_codigo(codigo: str) -> dict | None:
    cod = ''.join(ch for ch in codigo if ch.isalnum() or ch == '-')
    fc = _wfs(f"cod_imovel='{cod}'", 1, uf=uf_do_codigo_car(cod))
    feats = [imovel(f) for f in fc.get('features', []) if f.get('geometry')]
    return feats[0] if feats else None


def car_municipio(ibge: int, area_minima: float) -> list[dict]:
    """Todos os imóveis do município com área ≥ area_minima (paginado de 1000 em 1000)."""
    saida, start = [], 0
    while True:
        fc = _wfs(f'cod_municipio_ibge={int(ibge)} AND area>={float(area_minima)}', CAR_PAGINA, start, uf=int(ibge) // 100000)
        feats = fc.get('features', [])
        saida += [imovel(f) for f in feats if f.get('geometry')]
        start += len(feats)
        if len(feats) < CAR_PAGINA or start >= (fc.get('numberMatched') or 0):
            return saida


def imovel(feature: dict) -> dict:
    p = feature.get('properties', {})
    geom = _arredondar(feature['geometry'], 5)
    lat, lng = centroide(geom)
    return {
        'codigo': p.get('cod_imovel'), 'municipio_ibge': int(p.get('cod_municipio_ibge') or 0),
        'municipio': p.get('municipio') or '', 'area_ha': round(float(p.get('area') or 0), 2),
        'modulos_fiscais': round(float(p['m_fiscal']), 2) if p.get('m_fiscal') is not None else None,
        'status': p.get('status_imovel') or '', 'tipo': p.get('tipo_imovel') or '',
        'latitude': round(lat, 6), 'longitude': round(lng, 6), 'geometria': geom,
    }


def _arredondar(geom: dict, casas: int) -> dict:
    def r(c):
        return [round(c[0], casas), round(c[1], casas)] if isinstance(c[0], (int, float)) else [r(x) for x in c]
    return {'type': geom['type'], 'coordinates': r(geom['coordinates'])}


def _aneis(geom: dict) -> list[list[list[float]]]:
    """Anéis (externos e furos) de Polygon/MultiPolygon, como listas [lng, lat]."""
    if geom['type'] == 'Polygon':
        return list(geom['coordinates'])
    if geom['type'] == 'MultiPolygon':
        return [anel for poly in geom['coordinates'] for anel in poly]
    return []


def _rdp(pts: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker iterativo (pilha) para um anel."""
    if len(pts) < 5:
        return pts
    manter = np.zeros(len(pts), dtype=bool)
    manter[0] = manter[-1] = True
    pilha = [(0, len(pts) - 1)]
    while pilha:
        i, j = pilha.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        seg = b - a
        n = np.hypot(*seg) or 1e-12
        meio = pts[i + 1:j]
        d = np.abs(seg[0] * (meio[:, 1] - a[1]) - seg[1] * (meio[:, 0] - a[0])) / n
        k = int(d.argmax())
        if d[k] > tol:
            manter[i + 1 + k] = True
            pilha += [(i, i + 1 + k), (i + 1 + k, j)]
    return pts[manter]


def simplificar(geom: dict, tol: float = 0.0002) -> dict:
    """Geometria leve para desenhar (≈20 m): anéis com menos de 4 pontos depois disso caem."""
    def anel(a):
        pts = np.asarray(a, dtype=float)
        # Anel fechado (1º = último): o segmento base teria comprimento zero. Parte no ponto
        # mais distante do início e simplifica as duas metades.
        k = int(np.hypot(*(pts - pts[0]).T).argmax())
        r = np.vstack([_rdp(pts[:k + 1], tol)[:-1], _rdp(pts[k:], tol)]) if 0 < k < len(pts) - 1 else pts
        return [[round(x, 5), round(y, 5)] for x, y in r] if len(r) >= 4 else None

    polys = [geom['coordinates']] if geom['type'] == 'Polygon' else geom['coordinates']
    saida = []
    for poly in polys:
        aneis = [anel(a) for a in poly]
        if aneis and aneis[0]:
            saida.append([a for a in aneis if a])
    return {'type': 'MultiPolygon', 'coordinates': saida}


def centroide(geom: dict) -> tuple[float, float]:
    """Centro de massa (plano, bom o bastante para um imóvel) do primeiro/maior polígono. → (lat, lng)."""
    polys = [geom['coordinates']] if geom['type'] == 'Polygon' else geom['coordinates']
    melhor, maior = None, -1.0
    for poly in polys:
        anel = np.asarray(poly[0], dtype=float)
        x, y = anel[:, 0], anel[:, 1]
        cruz = x[:-1] * y[1:] - x[1:] * y[:-1]
        a = cruz.sum() / 2
        if abs(a) > maior and abs(a) > 0:
            cx = ((x[:-1] + x[1:]) * cruz).sum() / (6 * a)
            cy = ((y[:-1] + y[1:]) * cruz).sum() / (6 * a)
            melhor, maior = (cy, cx), abs(a)
    if melhor is None:  # polígono degenerado: média dos vértices
        anel = np.asarray(polys[0][0], dtype=float)
        return float(anel[:, 1].mean()), float(anel[:, 0].mean())
    return float(melhor[0]), float(melhor[1])


def dentro(px: np.ndarray, py: np.ndarray, geom: dict) -> np.ndarray:
    """Máscara booleana: pontos (px, py) dentro do polígono (par-ímpar, conta furos e multipartes)."""
    res = np.zeros(px.shape, dtype=bool)
    for anel in _aneis(geom):
        a = np.asarray(anel, dtype=float)
        x1, y1 = a[:-1, 0], a[:-1, 1]
        x2, y2 = a[1:, 0], a[1:, 1]
        for i in range(len(x1)):
            cruza = (y1[i] > py) != (y2[i] > py)
            if not cruza.any():
                continue
            xi = (x2[i] - x1[i]) * (py - y1[i]) / ((y2[i] - y1[i]) or 1e-12) + x1[i]
            res ^= cruza & (px < xi)
    return res


# ── MapBiomas: % de lavoura no polígono ─────────────────────────────────────

# Legenda MapBiomas (coleções 8–10): 18/19 agricultura e lavoura temporária, 39 soja, 20 cana,
# 40 arroz, 62 algodão, 41 outras temporárias, 36/46/47/35/48 perenes. Pastagem (15) e mosaico
# de usos (21) não contam como lavoura.
CLASSES_LAVOURA = (18, 19, 20, 35, 36, 39, 40, 41, 46, 47, 48, 62)


def pasta_mapas() -> Path:
    return Path(getattr(settings, 'MEDIA_ROOT', '.')) / 'comercialAgro' / 'mapbiomas'


class MapaLavoura:
    """Bitmap de lavoura (1 bit/pixel, linhas empacotadas) + georreferência, lido por janela."""

    def __init__(self, pasta: Path):
        meta = json.loads((pasta / 'lavoura.json').read_text())
        self.ano = int(meta['ano'])
        self.x0, self.dx, self.y0, self.dy = meta['x0'], meta['dx'], meta['y0'], meta['dy']  # dy < 0
        self.largura, self.altura = int(meta['largura']), int(meta['altura'])
        self.bits = np.load(pasta / 'lavoura.npy', mmap_mode='r')

    def lavoura(self, geom: dict) -> tuple[float, float] | None:
        """(fração de lavoura 0–1, % do polígono) pelos centros de pixel; None se fora do mapa."""
        xs = [c[0] for anel in _aneis(geom) for c in anel]
        ys = [c[1] for anel in _aneis(geom) for c in anel]
        if not xs:
            return None
        c0 = max(0, int(math.floor((min(xs) - self.x0) / self.dx)))
        c1 = min(self.largura, int(math.ceil((max(xs) - self.x0) / self.dx)) + 1)
        l0 = max(0, int(math.floor((max(ys) - self.y0) / self.dy)))
        l1 = min(self.altura, int(math.ceil((min(ys) - self.y0) / self.dy)) + 1)
        if c0 >= c1 or l0 >= l1:
            return None
        janela = np.unpackbits(np.asarray(self.bits[l0:l1, c0 // 8: (c1 + 7) // 8]), axis=1)
        janela = janela[:, c0 - (c0 // 8) * 8: c0 - (c0 // 8) * 8 + (c1 - c0)].astype(bool)
        cx = self.x0 + (np.arange(c0, c1) + 0.5) * self.dx
        cy = self.y0 + (np.arange(l0, l1) + 0.5) * self.dy
        px, py = np.meshgrid(cx, cy)
        mascara = dentro(px, py, geom)
        n = int(mascara.sum())
        if not n:
            return None
        frac = float(janela[mascara].mean())
        return frac, round(100 * frac, 1)


def mapa_lavoura() -> MapaLavoura | None:
    pasta = pasta_mapas()
    if not (pasta / 'lavoura.npy').exists():
        return None
    try:
        return MapaLavoura(pasta)
    except Exception as exc:  # arquivo corrompido não derruba a tela
        logger.warning('Comercial Agro: mapa do MapBiomas ilegível: %s', exc)
        return None


def com_lavoura(im: dict, mapa: MapaLavoura | None) -> dict:
    """Acrescenta lavoura_ha / lavoura_pct / lavoura_ano ao imóvel (área do CAR × fração do mapa)."""
    im = dict(im)
    # O recorte do MapBiomas é só do RS: imóvel de outra UF na divisa sairia com a lavoura cortada.
    fora = int(im.get('municipio_ibge') or 0) // 100000 not in (0, UF_IBGE)
    r = mapa.lavoura(im['geometria']) if mapa and not fora else None
    if r:
        frac, pct = r
        im.update(lavoura_ha=round(float(im['area_ha']) * frac, 1), lavoura_pct=pct, lavoura_ano=mapa.ano)
    return im
