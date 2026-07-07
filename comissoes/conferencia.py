import re
import unicodedata
import difflib
from collections import defaultdict

import openpyxl
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from sqlalchemy import text

from .views import engine
from .models import MapeamentoMunicipio

VENDEDORES_AGRO = {
    'ILDOMAR': 'ILDOMAR DA FONTE CARVALHO',
    'ILDOMAR DA FONTE CARVALHO': 'ILDOMAR DA FONTE CARVALHO',
    'EVERTON': 'EVERTON MARQUES DORNELES',
    'EVERTON MARQUES DORNELES': 'EVERTON MARQUES DORNELES',
}


def _norm(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^A-Za-z0-9 ]', ' ', s)
    return ' '.join(s.upper().split())


def _partial_ratio(a, b):
    """Similaridade de a contra o melhor trecho alinhado de b (ou o inverso, se a for maior)."""
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    sm = difflib.SequenceMatcher(None, a, b)
    best = 0.0
    for block in sm.get_matching_blocks():
        if block.size == 0:
            continue
        start = max(0, block.b - block.a)
        sub = b[start:start + len(a)]
        best = max(best, difflib.SequenceMatcher(None, a, sub).ratio())
    return best


def _parse_planilha(arquivo):
    """Lê uma planilha 'Relação de Pedidos Faturados e Movimentados' (PEDI/CODIGO, CLIENTE,
    MUNICIPIO, QUANTIDADE, VALOR R$, SITUAÇÃO, VALOR R$) e retorna as linhas de pedido."""
    wb = openpyxl.load_workbook(arquivo, data_only=True)
    ws = wb.worksheets[0]
    linhas = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        primeiro = row[0] if len(row) > 0 else None
        if not primeiro or not isinstance(primeiro, str) or '/' not in primeiro:
            continue
        valor = row[4] if len(row) > 4 else None
        if not isinstance(valor, (int, float)):
            continue
        ped = primeiro.split('/')[0].strip()
        if not ped.isdigit():
            continue
        linhas.append({
            'ped': ped,
            'cliente': str(row[1] or '').strip(),
            'municipio': str(row[2] or '').strip(),
            'valor': round(float(valor), 2),
            'situacao': str(row[5] or '').strip() if len(row) > 5 else '',
        })
    return linhas


def _buscar_notas(peds):
    """Busca no ERP as notas fiscais (qualquer situação/data) dos pedidos informados, com
    cliente, cidade de faturamento, segmento do produto e natureza da operação."""
    if not peds:
        return {}
    ids_str = ','.join(str(int(p)) for p in peds)
    sql = f"""
        SELECT NF.NFPED, NF.NFCOD, NF.NFNUM, NF.NFSIT, NF.NFDATA, CLINOME,
        R.REPNOME AS REPRESENTANTE, M.REPNOME AS MASTER, NOP.NOPNOME AS NOP,
        CASE
            WHEN (SELECT PPDADOCHAR FROM PESPARAMETRO WHERE PPTPP = 579 AND PPREF = NF.NFPED) = 'S' AND NF.NFECLI > 0
                THEN (SELECT CIDNOME + '-' + ESTUF FROM ENDERECOCLIENTE
                        JOIN CIDADE ON CIDCOD = ECLICIDADE JOIN ESTADO ON ESTCOD = CIDEST
                        WHERE ECLICOD = NF.NFECLI AND ECLICLI = NF.NFCLI)
            ELSE (SELECT CIDNOME + '-' + ESTUF FROM CIDADE JOIN ESTADO ON ESTCOD = CIDEST WHERE CIDCOD = CLICIDADE)
        END AS CIDADE,
        CASE WHEN ESTQ.ESTQGALM IN (1974,1587,1828) THEN 'AGRONEGOCIO' ELSE 'CONSTRUCAO CIVIL' END AS SEGMENTO,
        SUM(INF.INFTOTAL) AS TOTAL,
        -- TOTAL_OFICIAL: mesma regra de filtro usada no cálculo real do "Total Vendedor"
        -- (GALMPRODVENDA='S', NOP financeiro/não-receita, exclui série de acerto). Itens que não
        -- passam nesse filtro contam em TOTAL (a nota "existe") mas não em TOTAL_OFICIAL.
        SUM(CASE
            WHEN GALM.GALMPRODVENDA = 'S'
             AND SUBSTRING(NOP.NOPFLAGNF, 1, 1) = 'S' AND SUBSTRING(NOP.NOPFLAGNF, 25, 1) = 'N'
             AND NF.NFSNF NOT IN (8)
            THEN INF.INFTOTAL ELSE 0 END) AS TOTAL_OFICIAL
        FROM NOTAFISCAL NF
        JOIN CLIENTE ON CLICOD = NF.NFCLI
        LEFT JOIN REPRESENTANTE R ON R.REPCOD = NF.NFREP
        LEFT JOIN REPRESENTANTE M ON M.REPCOD = R.REPREPREF
        JOIN ITEMNOTAFISCAL INF ON INF.INFNFCOD = NF.NFCOD
        JOIN NATUREZAOPERACAO NOP ON NOP.NOPCOD = INF.INFNOP
        JOIN ESTOQUE ESTQ ON ESTQ.ESTQCOD = INF.INFESTQ
        LEFT JOIN GRUPOALMOXARIFADO GALM ON GALM.GALMCOD = ESTQ.ESTQGALM
        WHERE NF.NFPED IN ({ids_str}) AND NF.NFSIT = 1
        GROUP BY NF.NFPED, NF.NFCOD, NF.NFNUM, NF.NFSIT, NF.NFDATA, CLINOME, R.REPNOME, M.REPNOME, NOP.NOPNOME,
                 NF.NFECLI, NF.NFCLI, CLICIDADE, ESTQ.ESTQGALM
        ORDER BY NF.NFPED, NF.NFDATA
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).mappings().all()
    pedmap = defaultdict(list)
    for r in rows:
        pedmap[str(r['NFPED'])].append(dict(r))
    return pedmap


def _is_cotrijal(nome):
    return 'COTRIJAL' in _norm(nome)


def _classificar_linha(linha, candidatos, vendedor_nome, mapa_municipio):
    if not candidatos:
        return {'status': 'PENDENTE', 'is_cotrijal': _is_cotrijal(linha['cliente']),
                'detalhe': 'Nenhuma nota fiscal encontrada para esse pedido (venda ainda não faturada).'}

    cn = _norm(linha['cliente'])
    scored = sorted(
        ((_partial_ratio(cn, _norm(c['CLINOME'])), c) for c in candidatos),
        key=lambda x: -x[0]
    )
    best_ratio, best = scored[0]

    match = None
    if best_ratio >= 0.55 and abs(best['TOTAL'] - linha['valor']) < 1:
        match = [best]
    else:
        similares = [c for ratio, c in scored if ratio >= 0.55]
        soma = sum(c['TOTAL'] for c in similares)
        if similares and abs(soma - linha['valor']) < 1:
            match = similares
        elif best_ratio >= 0.65:
            match = [best]

    if not match:
        return {'status': 'PENDENTE', 'is_cotrijal': _is_cotrijal(linha['cliente']),
                'detalhe': (f"Nenhuma nota bate com o cliente/valor anotado "
                            f"(melhor candidato: {best['CLINOME']}, R$ {best['TOTAL']:.2f}).")}

    is_cotrijal = any(_is_cotrijal(m['CLINOME']) for m in match)

    segmentos = set(m['SEGMENTO'] for m in match)
    if segmentos != {'AGRONEGOCIO'}:
        return {'status': 'FORA_ESCOPO', 'is_cotrijal': is_cotrijal,
                'detalhe': (f"Nota real de R$ {sum(m['TOTAL'] for m in match):.2f} é do segmento "
                            f"{'/'.join(segmentos)}, não Agronegócio.")}

    nops = set(m['NOP'].upper() for m in match)
    if all('REMESSA' in n for n in nops):
        return {'status': 'REMESSA', 'is_cotrijal': is_cotrijal,
                'detalhe': 'Encontrada só como remessa de entrega (a venda já foi faturada antes).'}

    cidades = set((m['CIDADE'] or '').strip().upper() for m in match)
    donos = set(mapa_municipio.get(c) for c in cidades)
    if vendedor_nome not in donos:
        outro = next((d for d in donos if d), None)
        return {'status': 'OUTRO_VENDEDOR', 'is_cotrijal': is_cotrijal,
                'detalhe': (f"Cidade ({', '.join(c.title() for c in cidades)}) mapeada para "
                            f"{(outro or 'nenhum vendedor').title()}, não para {vendedor_nome.title()}.")}

    nfs = ', '.join(str(m['NFNUM']) for m in match)
    total_bruto = sum(m['TOTAL'] for m in match)
    total_oficial = sum(m['TOTAL_OFICIAL'] or 0 for m in match)
    diverge_filtro_oficial = abs(total_bruto - total_oficial) > 1
    return {
        'status': 'OK', 'is_cotrijal': is_cotrijal, 'detalhe': f'Confirmado no sistema (NF {nfs}).',
        'diverge_filtro_oficial': diverge_filtro_oficial,
        'valor_fora_filtro_oficial': round(float(total_bruto - total_oficial), 2) if diverge_filtro_oficial else 0.0,
    }


@csrf_exempt
@api_view(['POST'])
def conferencia_vendedor(request):
    vendedor_key = (request.data.get('vendedor') or '').strip().upper()
    vendedor_nome = VENDEDORES_AGRO.get(vendedor_key)
    if not vendedor_nome:
        return Response({'erro': 'Informe o vendedor (Ildomar ou Everton).'}, status=400)

    data_inicio = request.data.get('dataInicio')
    data_fim = request.data.get('dataFim')

    arquivos = request.FILES.getlist('arquivos')
    if not arquivos:
        return Response({'erro': 'Envie ao menos uma planilha (.xlsx).'}, status=400)

    todas_linhas = []
    for arq in arquivos:
        try:
            linhas = _parse_planilha(arq)
        except Exception as e:
            return Response({'erro': f'Falha ao ler "{arq.name}": {e}'}, status=400)
        for l in linhas:
            l['arquivo'] = arq.name
        todas_linhas.extend(linhas)

    if not todas_linhas:
        return Response({'erro': 'Nenhuma linha de pedido reconhecida nas planilhas enviadas.'}, status=400)

    mapa_municipio = {
        m.cidade_estado.strip().upper(): m.representante.nome.strip().upper()
        for m in MapeamentoMunicipio.objects.filter(segmento='AGRONEGOCIO').select_related('representante')
    }

    peds = sorted(set(l['ped'] for l in todas_linhas))
    pedmap = _buscar_notas(peds)

    resultado = []
    for l in todas_linhas:
        candidatos = pedmap.get(l['ped'], [])
        if data_inicio and data_fim:
            candidatos = [c for c in candidatos if data_inicio <= str(c['NFDATA'])[:10] <= data_fim]
        classificacao = _classificar_linha(l, candidatos, vendedor_nome, mapa_municipio)
        resultado.append({**l, **classificacao})

    resumo = defaultdict(lambda: {'valor': 0.0, 'qtd': 0})
    for r in resultado:
        resumo[r['status']]['valor'] += r['valor']
        resumo[r['status']]['qtd'] += 1
    for k in resumo:
        resumo[k]['valor'] = round(resumo[k]['valor'], 2)

    linhas_divergentes = [r for r in resultado if r.get('diverge_filtro_oficial')]
    diagnostico_filtro_oficial = {
        'valor_total': round(sum(r['valor_fora_filtro_oficial'] for r in linhas_divergentes), 2),
        'qtd': len(linhas_divergentes),
        'linhas': [
            {'ped': r['ped'], 'cliente': r['cliente'], 'valor': r['valor'],
             'valor_fora_filtro_oficial': r['valor_fora_filtro_oficial'], 'arquivo': r['arquivo']}
            for r in linhas_divergentes
        ],
    }

    return Response({
        'vendedor': vendedor_nome,
        'diagnostico_filtro_oficial': diagnostico_filtro_oficial,
        'total_anotado': round(sum(l['valor'] for l in todas_linhas), 2),
        'linhas': resultado,
        'resumo': resumo,
    })
