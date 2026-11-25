"""
Comparativo guardado entre a licença anterior e a nova (25/11/2026).

Na renovação (renovacao.py) o cruzamento das condicionantes só existia na tela, enquanto a pessoa
revisava. Ao aplicar, o sistema agora grava um retrato (`ComparativoRenovacao`) e gera o PDF:

- igual     → condicionante herdada com o mesmo texto;
- alterada  → herdada com o texto mudado (o PDF mostra o que saiu riscado e o que entrou);
- nova      → só existe na licença nova;
- removida  → existia na anterior e nenhuma da nova herdou dela.

O retrato sai do BANCO depois da aplicação (requisitos da nova + `herdado_de`), não da leitura da IA:
assim vale também para renovação aplicada antes desta função (botão "Gerar comparativo") e mostra o
que de fato ficou cadastrado, com os pares que a pessoa trocou na tela.
"""
from __future__ import annotations

import io
import logging
import re
from difflib import SequenceMatcher

from django.core.files.base import ContentFile
from django.utils import timezone

from .renovacao import IGUAL_MIN, normalizar, numero, similaridade, texto_requisito

logger = logging.getLogger(__name__)

ORDEM = ('alterada', 'nova', 'removida', 'igual')
ROTULOS = {'igual': 'Igual', 'alterada': 'Alterada', 'nova': 'Nova', 'removida': 'Removida'}
ROTULOS_PLURAL = {'igual': 'Iguais', 'alterada': 'Alteradas', 'nova': 'Novas', 'removida': 'Removidas'}
RESULTADOS = {'ATENDIDO': 'Atendido', 'PARCIAL': 'Atendido parcialmente', 'NAO_ATENDIDO': 'Não atendido'}


def _chave_ref(ref: str):
    """Ordena '2.10' depois de '2.9' (ordem da licença)."""
    n = numero(ref)
    return [int(p) for p in n.split('.')] if n else [10 ** 6], ref or ''


def _ultima(req):
    vs = sorted(req.verificacoes.all(), key=lambda v: (v.data, v.id), reverse=True)
    v = vs[0] if vs else None
    return None if v is None else {'data': v.data.isoformat(), 'resultado': v.resultado,
                                   'herdada': v.herdada_de_id is not None}


def montar(norma) -> dict:
    """Retrato atual da renovação: condicionantes ativas da nova cruzadas com as da anterior pelo `herdado_de`."""
    anterior = norma.substitui
    if anterior is None:
        raise ValueError('Esta licença não está ligada a uma versão anterior.')
    novos = list(norma.requisitos.filter(ativo=True).select_related('herdado_de').prefetch_related('verificacoes'))
    antigos = list(anterior.requisitos.filter(ativo=True).prefetch_related('verificacoes'))
    ids_antigos = {r.id for r in antigos}

    itens, usados, capitulos = [], set(), {}
    for r in novos:
        velho = r.herdado_de if r.herdado_de_id in ids_antigos else None
        texto_novo = texto_requisito(r)
        item = {
            'requisito': r.id, 'referencia': r.referencia, 'secao': r.secao, 'descricao': r.descricao,
            'texto': texto_novo, 'situacao': 'nova', 'similaridade': None, 'anterior': None,
            'resposta_herdada': any(v.herdada_de_id for v in r.verificacoes.all()),
        }
        if velho is not None:
            usados.add(velho.id)
            texto_velho = texto_requisito(velho)
            s = similaridade(normalizar(texto_velho), normalizar(texto_novo))
            item['similaridade'] = round(s, 3)
            item['situacao'] = 'igual' if s >= IGUAL_MIN else 'alterada'
            item['anterior'] = {'requisito': velho.id, 'referencia': velho.referencia, 'secao': velho.secao,
                                'descricao': velho.descricao, 'texto': texto_velho, 'ultima': _ultima(velho)}
            a, n = numero(velho.referencia), numero(r.referencia)
            if a and n and a.split('.')[0] != n.split('.')[0]:
                capitulos.setdefault(a.split('.')[0], n.split('.')[0])
        itens.append(item)
    itens.sort(key=lambda i: _chave_ref(i['referencia']))

    removidas = [{'requisito': r.id, 'referencia': r.referencia, 'secao': r.secao, 'descricao': r.descricao,
                  'texto': texto_requisito(r), 'ultima': _ultima(r)}
                 for r in sorted(antigos, key=lambda r: _chave_ref(r.referencia)) if r.id not in usados]
    contagem = {s: sum(1 for i in itens if i['situacao'] == s) for s in ('igual', 'alterada', 'nova')}
    contagem['removida'] = len(removidas)
    return {'norma': norma, 'anterior': anterior, 'contagem': contagem, 'capitulos': capitulos,
            'itens': itens, 'removidas': removidas}


def gerar(norma, usuario):
    """Grava o comparativo (retrato + PDF). O PDF que falhar não impede o registro: é refeito ao baixar."""
    from .models import ComparativoRenovacao
    d = montar(norma)
    c = ComparativoRenovacao.objects.create(
        norma=norma, anterior=d['anterior'], identificacao_nova=norma.identificacao[:300],
        identificacao_anterior=d['anterior'].identificacao[:300], contagem=d['contagem'],
        capitulos=d['capitulos'], itens=d['itens'], removidas=d['removidas'], criado_por=usuario)
    try:
        salvar_pdf(c)
    except Exception:  # noqa: BLE001
        logger.exception('Comparativo %s: PDF não gerado (fica para o download)', c.id)
    return c


def salvar_pdf(c) -> bytes:
    conteudo = gerar_pdf(c)
    nome = re.sub(r'[^A-Za-z0-9]+', '_', f'Comparativo_{c.identificacao_nova}').strip('_')[:120]
    c.arquivo.save(f'{nome}_{c.id}.pdf', ContentFile(conteudo), save=True)
    return conteudo


def nome_arquivo(c) -> str:
    base = re.sub(r'[^\w\-]+', '_', f'Comparativo {c.identificacao_anterior} x {c.identificacao_nova}').strip('_')
    return f'{base[:150]}.pdf'


# ── PDF ─────────────────────────────────────────────────────────────────────────────────────────

def _diff_xml(antes: str, depois: str, xml) -> tuple[str, str]:
    """Antes com o que saiu riscado em vermelho; depois com o que entrou sublinhado em verde."""
    a, b = re.split(r'(\s+)', antes or ''), re.split(r'(\s+)', depois or '')
    if len(a) * len(b) > 400_000:
        return xml(antes), xml(depois)
    sa, sb = [], []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        ta, tb = xml(''.join(a[i1:i2])), xml(''.join(b[j1:j2]))
        if op == 'equal':
            sa.append(ta)
            sb.append(tb)
            continue
        if ta.strip():
            sa.append(f'<font color="#B42318"><strike>{ta}</strike></font>')
        if tb.strip():
            sb.append(f'<font color="#067647"><u>{tb}</u></font>')
    return ''.join(sa), ''.join(sb)


def gerar_pdf(c) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .relatorio_anual import _fontes, _xml

    normal, negrito, italico = _fontes()

    def br(t: str) -> str:
        return _xml(t or '').replace('\n', '<br/>')

    base = ParagraphStyle('cb', fontName=normal, fontSize=9.5, leading=12.5, alignment=TA_LEFT)
    pequeno = ParagraphStyle('cp', parent=base, fontSize=8, leading=10, textColor='#555555')
    titulo = ParagraphStyle('ct', parent=base, fontName=negrito, fontSize=15, leading=19, spaceAfter=4)
    secao = ParagraphStyle('cs', parent=base, fontName=negrito, fontSize=11.5, leading=15, spaceBefore=12, spaceAfter=6)
    cab = ParagraphStyle('cc', parent=base, fontName=negrito, fontSize=9, textColor='#333333')
    ref = ParagraphStyle('cr', parent=base, fontName=negrito)
    cores = {'igual': '#667085', 'alterada': '#B54708', 'nova': '#175CD3', 'removida': '#B42318'}

    largura = A4[0] - 3 * cm
    quando = timezone.localtime(c.criado_em) if c.criado_em else timezone.localtime()
    quem = ''
    if c.criado_por_id:
        from .serializers import nome_usuario
        quem = nome_usuario(c.criado_por) or ''

    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont(italico, 7.5)
        canvas.setFillColor('#666666')
        canvas.drawString(1.5 * cm, 1 * cm, _xml(f'Comparativo {c.identificacao_anterior} → {c.identificacao_nova}')[:150])
        canvas.drawRightString(A4[0] - 1.5 * cm, 1 * cm, f'Página {doc.page}')
        canvas.restoreState()

    saida = io.BytesIO()
    doc = SimpleDocTemplate(saida, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                            bottomMargin=1.6 * cm, title=f'Comparativo – {c.identificacao_nova}')
    h = [Paragraph('Comparativo de condicionantes — renovação de licença', titulo),
         Paragraph(f'<b>Anterior:</b> {_xml(c.identificacao_anterior)} &nbsp;&nbsp;→&nbsp;&nbsp; '
                   f'<b>Nova:</b> {_xml(c.identificacao_nova)}', base),
         Paragraph(_xml(f'Gerado em {quando:%d/%m/%Y %H:%M}' + (f' por {quem}' if quem else '') +
                        ' · retrato da renovação aplicada no Manager'), pequeno),
         Spacer(1, 8)]

    k = c.contagem or {}
    centro = ParagraphStyle('cn', parent=base, alignment=1, leading=18)
    resumo = Table([[Paragraph(f'<font size="15" color="{cores[s]}"><b>{k.get(s, 0)}</b></font><br/>{ROTULOS_PLURAL[s]}', centro)
                     for s in ('igual', 'alterada', 'nova', 'removida')]], colWidths=[largura / 4] * 4)
    resumo.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#D0D5DD')),
                                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D0D5DD')),
                                ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('TOPPADDING', (0, 0), (-1, -1), 6),
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    h.append(resumo)
    if c.capitulos:
        txt = ' · '.join(f'{a} → {n}' for a, n in sorted(c.capitulos.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0))
        h.append(Paragraph(_xml(f'Capítulos renumerados na licença nova: {txt}. O cruzamento é pelo texto, não pelo número.'), pequeno))
    h.append(Paragraph('Legenda: <font color="#B42318"><strike>texto que saiu</strike></font> · '
                       '<font color="#067647"><u>texto que entrou</u></font>', pequeno))

    meia = (largura - 2.2 * cm) / 2
    estilo_tab = TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#D0D5DD')),
                             ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F2F4F7')),
                             ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4)])

    def resposta(u) -> str:
        if not u:
            return ''
        d = u['data']
        return f'<br/><font size="7.5" color="#555555">Última resposta: {RESULTADOS.get(u["resultado"], u["resultado"])} em {d[8:10]}/{d[5:7]}/{d[:4]}</font>'

    por = {s: [] for s in ORDEM}
    for i in c.itens or []:
        por.setdefault(i['situacao'], []).append(i)
    for s in ORDEM:
        lista = c.removidas if s == 'removida' else por.get(s, [])
        if not lista:
            continue
        h.append(Paragraph(f'<font color="{cores[s]}">{ROTULOS_PLURAL[s]} ({len(lista)})</font>', secao))
        if s == 'removida':
            linhas = [[Paragraph('Nº', cab), Paragraph('Texto na licença anterior (não está na nova)', cab)]]
            for r in lista:
                linhas.append([Paragraph(_xml(r['referencia'] or '—'), ref),
                               Paragraph(br(r['texto'] or r['descricao']) + resposta(r.get('ultima')), base)])
            t = Table(linhas, colWidths=[2.2 * cm, largura - 2.2 * cm], repeatRows=1)
        elif s == 'nova':
            linhas = [[Paragraph('Nº', cab), Paragraph('Texto na licença nova (não existia na anterior)', cab)]]
            for i in lista:
                linhas.append([Paragraph(_xml(i['referencia'] or '—'), ref), Paragraph(br(i['texto'] or i['descricao']), base)])
            t = Table(linhas, colWidths=[2.2 * cm, largura - 2.2 * cm], repeatRows=1)
        else:
            linhas = [[Paragraph('Nº', cab), Paragraph('Licença anterior', cab), Paragraph('Licença nova', cab)]]
            for i in lista:
                an = i.get('anterior') or {}
                if s == 'alterada':
                    antes, depois = _diff_xml(an.get('texto') or an.get('descricao', ''), i['texto'] or i['descricao'], _xml)
                    antes, depois = antes.replace('\n', '<br/>'), depois.replace('\n', '<br/>')
                else:
                    antes, depois = br(an.get('texto') or an.get('descricao', '')), br(i['texto'] or i['descricao'])
                num = _xml(i['referencia'] or '—')
                if an.get('referencia') and an['referencia'] != i['referencia']:
                    num += f'<br/><font size="7.5" color="#555555">era {_xml(an["referencia"])}</font>'
                extra = '<br/><font size="7.5" color="#555555">Resposta anterior herdada</font>' if i.get('resposta_herdada') else ''
                linhas.append([Paragraph(num, ref), Paragraph(antes + resposta(an.get('ultima')), base),
                               Paragraph(depois + extra, base)])
            t = Table(linhas, colWidths=[2.2 * cm, meia, meia], repeatRows=1)
        t.setStyle(estilo_tab)
        h.append(t)
    if not (c.itens or c.removidas):
        h.append(KeepTogether([Spacer(1, 12), Paragraph('A licença nova ainda não tem condicionantes cadastradas.', base)]))

    doc.build(h, onFirstPage=rodape, onLaterPages=rodape)
    return saida.getvalue()
