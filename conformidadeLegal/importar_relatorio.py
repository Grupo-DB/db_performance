"""
Importa um Relatório Anual de Acompanhamento já entregue (PDF gerado no Word) para
dentro da licença: a resposta de cada condicionante vira uma Verificação, com as
fotos e as legendas ("Figura N: …") como anexos.

Como o PDF é lido (sem IA, para não gastar e não inventar):
  - o modelo do relatório escreve a condicionante em NEGRITO e a resposta em fonte
    normal — é a fonte de cada caractere que separa uma da outra (pdfminer.six);
  - "5.13.2- texto" em negrito abre uma condicionante; "5. Quanto à …" abre capítulo;
  - "Figura N: legenda" casa com a imagem desenhada logo ACIMA dela na página (a
    legenda que cai no topo da página seguinte pega a última imagem da anterior);
  - cabeçalho (número da página) e rodapé (linha da licença) ficam de fora pela
    posição na folha.

A condicionante do PDF casa com o requisito pelo NÚMERO ("Item 1.4", "Condicionante
1.4" e "1.4-" são o mesmo 1.4). O que não existe no sistema pode ser criado; o que o
sistema tem e o relatório não traz pode sair do relatório (lista `fora`).
"""
import calendar
import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from django.core.files.base import ContentFile
from django.db import transaction

from .models import EvidenciaAnexo, Requisito, Verificacao

logger = logging.getLogger(__name__)

MESES = {'janeiro': 1, 'fevereiro': 2, 'marco': 3, 'abril': 4, 'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8,
         'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12}
MARGEM_CABECALHO = 60   # pt a partir do topo: número da página
MARGEM_RODAPE = 50      # pt a partir do pé: linha da licença
# "5.13.2- texto", "19.2. texto" ou o subitem "4.5-1. texto" (o hífen ali é parte do número).
RE_ITEM = re.compile(r'^(\d+(?:\.\d+)+-\d+)\.\s*(.*)$|^(\d+(?:\.\d+)+)\s*[-–.]\s*(.*)$')
RE_SECAO = re.compile(r'^(\d+)\s*[.\-–]\s*([A-Za-zÀ-ú].*)$')
RE_FIGURA = re.compile(r'^Figura\s*(\d+)\s*[:.\-–]?\s*(.*)$', re.IGNORECASE)


class PdfIlegivel(Exception):
    pass


def numeros(ref: str) -> tuple:
    """'Item 4.5-1' → (4, 5, 1): a chave que casa o PDF com o requisito."""
    return tuple(int(n) for n in re.findall(r'\d+', ref or ''))


def _sem_acento(s: str) -> str:
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode().lower()


def _espacos(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()


# ── Leitura do PDF ───────────────────────────────────────────────────────────

@dataclass
class Figura:
    numero: int
    legenda: str
    pagina: int
    y: float
    imagem: bytes | None = None
    extensao: str = 'jpg'


@dataclass
class ItemPdf:
    referencia: str
    secao: str
    condicao: list = field(default_factory=list)
    resposta: list = field(default_factory=list)   # parágrafos
    figuras: list = field(default_factory=list)
    pagina: int = 0

    @property
    def chave(self) -> tuple:
        return numeros(self.referencia)

    @property
    def texto_condicao(self) -> str:
        return _espacos(' '.join(self.condicao))

    @property
    def texto_resposta(self) -> str:
        return '\n'.join(p for p in (_espacos(x) for x in self.resposta) if p)


@dataclass
class Linha:
    pagina: int
    y0: float
    y1: float
    x0: float
    partes: list  # [(negrito, texto)]

    @property
    def texto(self) -> str:
        return _espacos(''.join(t for _, t in self.partes))

    @property
    def comeca_negrito(self) -> bool:
        for negrito, t in self.partes:
            if t.strip():
                return negrito
        return False


def _negrito(fonte: str) -> bool:
    f = fonte.lower()
    return 'bold' in f or 'black' in f or 'negrito' in f


def _linhas_e_imagens(conteudo: bytes):
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTAnno, LTChar, LTFigure, LTImage, LTTextContainer, LTTextLine

    paginas = []
    try:
        for n, pagina in enumerate(extract_pages(io.BytesIO(conteudo), laparams=LAParams()), 1):
            brutas, imagens = [], []

            def visitar(obj):
                for x in obj:
                    if isinstance(x, LTTextLine):
                        brutas.append(x)
                    elif isinstance(x, LTTextContainer):
                        visitar(x)
                    elif isinstance(x, LTImage):
                        imagens.append(x)
                    elif isinstance(x, LTFigure):
                        visitar(x)

            visitar(pagina)
            topo, pe = pagina.height - MARGEM_CABECALHO, MARGEM_RODAPE
            # Pedaços na mesma altura ("1." e "Quanto ao Empreendimento:") viram uma linha só.
            grupos: list[list] = []
            for ln in sorted(brutas, key=lambda l: (-round((l.y0 + l.y1) / 2), l.x0)):
                if ln.y0 > topo or ln.y1 < pe or not ln.get_text().strip():
                    continue
                meio = (ln.y0 + ln.y1) / 2
                if grupos and abs(grupos[-1][0] - meio) < 3:
                    grupos[-1][1].append(ln)
                else:
                    grupos.append([meio, [ln]])
            linhas = []
            for _, lns in grupos:
                lns.sort(key=lambda l: l.x0)
                partes, negrito = [], False
                for k, ln in enumerate(lns):
                    if k:
                        partes.append((negrito, ' '))
                    for c in ln:
                        if isinstance(c, LTChar):
                            negrito = _negrito(c.fontname)
                            partes.append((negrito, c.get_text()))
                        elif isinstance(c, LTAnno):
                            partes.append((negrito, c.get_text()))
                linhas.append(Linha(n, min(l.y0 for l in lns), max(l.y1 for l in lns), lns[0].x0, partes))
            # Imagem pequena (ícone, assinatura) não é foto de evidência.
            fotos = [i for i in imagens if i.width > 120 and i.height > 80 and topo > i.y0 and i.y1 > pe]
            paginas.append((n, linhas, fotos))
    except Exception as e:  # noqa: BLE001 — pdfminer levanta de tudo com PDF estranho
        logger.warning('Importar relatório: PDF ilegível', exc_info=True)
        raise PdfIlegivel('Não foi possível ler o PDF. Ele precisa ter texto (não pode ser digitalizado como imagem).') from e
    return paginas


def _bytes_da_imagem(img) -> tuple[bytes | None, str]:
    """JPEG sai como está; o resto passa pelo Pillow (via pdfminer não há decodificação boa de Flate+cor)."""
    try:
        filtros = img.stream.get_filters()
        nomes = [str(f[0]).strip('/') for f in filtros] if filtros else []
        # get_data() desfaz ASCII85/Flate e para no DCT: sobra o JPEG como foi gravado.
        if any('DCT' in n for n in nomes):
            return img.stream.get_data(), 'jpg'
        if any('JPX' in n for n in nomes):
            return img.stream.get_data(), 'jp2'
        from pdfminer.image import ImageWriter
        import tempfile, os
        with tempfile.TemporaryDirectory() as pasta:
            nome = ImageWriter(pasta).export_image(img)
            caminho = os.path.join(pasta, nome)
            with open(caminho, 'rb') as f:
                dados = f.read()
            return dados, nome.rsplit('.', 1)[-1].lower()
    except Exception:  # noqa: BLE001
        logger.warning('Importar relatório: imagem %s não extraída', getattr(img, 'name', '?'), exc_info=True)
        return None, 'jpg'


def ler(conteudo: bytes) -> dict:
    """
    {'itens': [ItemPdf], 'capa': {...}, 'data': date|None, 'avisos': [str]} — sem tocar no banco.
    """
    if not conteudo.startswith(b'%PDF'):
        raise PdfIlegivel('O arquivo não é um PDF.')
    paginas = _linhas_e_imagens(conteudo)
    itens: list[ItemPdf] = []
    avisos: list[str] = []
    secao = ''
    atual: ItemPdf | None = None
    figura_aberta: tuple[Figura, Linha] | None = None
    legendas: list[tuple[Figura, Linha]] = []
    corpo_iniciado = False
    textos_iniciais: list[str] = []

    for n, linhas, _ in paginas:
        for ln in linhas:
            texto = ln.texto
            if not corpo_iniciado:
                textos_iniciais.append(texto)
                if _sem_acento(texto).startswith('atendimento das condic'):
                    corpo_iniciado = True
                continue
            # Continuação da legenda: linha colada à de cima (espaçamento simples da legenda).
            if figura_aberta and not ln.comeca_negrito and figura_aberta[1].pagina == n \
                    and figura_aberta[1].y0 - ln.y1 < 5 and not RE_FIGURA.match(texto):
                figura_aberta[0].legenda = _espacos(f'{figura_aberta[0].legenda} {texto}')
                figura_aberta = (figura_aberta[0], ln)
                continue
            figura_aberta = None
            m = RE_FIGURA.match(texto)
            if m:
                fig = Figura(numero=int(m.group(1)), legenda=m.group(2).strip(), pagina=n, y=ln.y1)
                legendas.append((fig, ln))
                figura_aberta = (fig, ln)
                if atual:
                    atual.figuras.append(fig)
                else:
                    avisos.append(f'Figura {fig.numero} aparece antes da primeira condicionante e foi ignorada.')
                continue
            if ln.comeca_negrito:
                mi = RE_ITEM.match(texto)
                if mi:
                    atual = ItemPdf(referencia=mi.group(1) or mi.group(3), secao=secao, pagina=n)
                    itens.append(atual)
                    _distribuir(atual, ln, abre_item=True)
                    continue
                ms = RE_SECAO.match(texto)
                if ms and not numeros(texto[len(ms.group(1)):ms.start(2)]):
                    secao = ms.group(2).strip().rstrip(':').strip()
                    atual = None
                    continue
            if atual:
                _distribuir(atual, ln)

    # Imagem de cada legenda: a desenhada logo acima dela na mesma página; sem nenhuma,
    # a última que sobrou da página anterior (legenda que caiu no topo da folha seguinte).
    por_pagina = {n: sorted(fotos, key=lambda i: -i.y0) for n, _, fotos in paginas}
    usadas = set()
    for fig, ln in legendas:
        candidatas = [i for i in por_pagina.get(fig.pagina, []) if id(i) not in usadas and i.y0 >= ln.y0 - 2]
        img = min(candidatas, key=lambda i: i.y0 - ln.y1) if candidatas else None
        if img is None:
            anteriores = [i for i in por_pagina.get(fig.pagina - 1, []) if id(i) not in usadas]
            img = min(anteriores, key=lambda i: i.y0) if anteriores else None
        if img is None:
            avisos.append(f'Figura {fig.numero}: não achei a imagem correspondente no PDF.')
            continue
        usadas.add(id(img))
        fig.imagem, fig.extensao = _bytes_da_imagem(img)
        if fig.imagem is None:
            avisos.append(f'Figura {fig.numero}: a imagem não pôde ser extraída.')

    for it in itens:
        for par in it.resposta:
            toks = par.split()
            # Muitas "palavras" de uma letra (N D J F M A…) = tabela que virou texto corrido.
            if sum(1 for t in toks if len(t) == 1 and t.isalpha() and t.isupper()) >= 8:
                avisos.append(f'{it.referencia}: a resposta tem uma tabela, que entrou como texto corrido — '
                              'revise depois de importar.')
                break
    capa = _capa(textos_iniciais)
    if not itens:
        raise PdfIlegivel('Não encontrei condicionantes no PDF (linhas em negrito começando por "1.1-").')
    return {'itens': itens, 'capa': capa, 'data': capa.pop('data', None), 'avisos': avisos}


RE_PREFIXO = re.compile(r'^\s*(?:\d+(?:\.\d+)+-\d+\.|\d+(?:\.\d+)+\s*[-–.])\s*')


def _distribuir(item: ItemPdf, ln: Linha, abre_item: bool = False):
    """Negrito vai para a condicionante (enquanto a resposta não começou); normal, para a resposta."""
    pedacos: list[list] = []
    for negrito, t in ln.partes:
        if pedacos and pedacos[-1][0] == negrito:
            pedacos[-1][1] += t
        else:
            pedacos.append([negrito, t])
    if abre_item and pedacos:
        pedacos[0][1] = RE_PREFIXO.sub('', pedacos[0][1], count=1)
    for negrito, t in pedacos:
        if not t.strip():
            continue
        if negrito and not item.resposta:
            item.condicao.append(t)
        elif negrito:
            # Subtítulo em negrito dentro da resposta ("Mina Corticeira"): parágrafo próprio.
            item.resposta.append(t)
            item.resposta.append('')
        elif item.resposta and item.resposta[-1] == '':
            item.resposta[-1] = t
        elif item.resposta and not item.resposta[-1].rstrip().endswith(('.', ':', ';')):
            item.resposta[-1] += ' ' + t
        else:
            item.resposta.append(t)


def _capa(textos: list[str]) -> dict:
    """Atividade, processos, licença e item da apresentação, quando o modelo é o de sempre."""
    capa: dict = {}
    junto = ' '.join(textos)
    for t in textos:
        tl = _sem_acento(t)
        if tl.startswith('processo'):
            capa.setdefault('processos', t.strip())
        elif tl.startswith(('extracao', 'fabricacao', 'lavra', 'industria', 'beneficiamento')):
            capa.setdefault('atividade', t.strip().title().replace(' De ', ' de ').replace(' Da ', ' da '))
        m = re.match(r'^(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)'
                     r'\s*(?:de\s*)?(\d{4})$', tl)
        if m:
            mes, ano = MESES[m.group(1)], int(m.group(2))
            capa['data'] = date(ano, mes, calendar.monthrange(ano, mes)[1])
            capa['data_capa'] = t.strip().upper()
    m = re.search(r'atendimento do item\s*(\d+)', _espacos(junto), re.IGNORECASE)
    if m:
        capa['item'] = m.group(1)
    m = re.search(r'restri[çc][õo]es da\s+(.+?)\.(?:\s|$)', _espacos(junto), re.IGNORECASE)
    if m:
        capa['licenca'] = m.group(1).strip()
    return capa


# ── Casamento com a licença e gravação ───────────────────────────────────────

def planejar(norma, lido: dict) -> dict:
    """O que a importação faria — a prévia da tela e a base de `aplicar`."""
    requisitos = list(Requisito.objects.filter(norma=norma, ativo=True).order_by('id'))
    por_chave: dict[tuple, Requisito] = {}
    for r in requisitos:
        chave = numeros(r.referencia)
        if chave and chave not in por_chave:
            por_chave[chave] = r
    vistos = set()
    plano = []
    for item in lido['itens']:
        req = por_chave.get(item.chave)
        if req:
            vistos.add(req.id)
        plano.append({'item': item, 'requisito': req})
    ausentes = [r for r in requisitos if r.id not in vistos]
    return {'plano': plano, 'ausentes': ausentes}


def resumo_json(norma, lido: dict, planejado: dict) -> dict:
    itens = []
    for p in planejado['plano']:
        item, req = p['item'], p['requisito']
        itens.append({
            'referencia': item.referencia, 'secao': item.secao, 'condicao': item.texto_condicao,
            'resposta': item.texto_resposta, 'pagina': item.pagina,
            'figuras': [{'numero': f.numero, 'legenda': f.legenda, 'ok': f.imagem is not None} for f in item.figuras],
            'requisito': req.id if req else None,
            'requisito_referencia': req.referencia if req else None,
            'requisito_aplicabilidade': req.aplicabilidade if req else None,
        })
    return {
        'itens': itens,
        'ausentes': [{'requisito': r.id, 'referencia': r.referencia, 'descricao': r.descricao} for r in planejado['ausentes']],
        'capa': lido['capa'],
        'data': lido['data'].isoformat() if lido['data'] else None,
        'avisos': lido['avisos'],
        'totais': {
            'condicionantes': len(itens),
            'casadas': sum(1 for i in itens if i['requisito']),
            'novas': sum(1 for i in itens if not i['requisito']),
            'com_resposta': sum(1 for i in itens if i['resposta']),
            'figuras': sum(len(i['figuras']) for i in itens),
            'ausentes': len(planejado['ausentes']),
            'viram_aplicavel': sum(1 for i in itens if i['requisito'] and i['resposta']
                                   and i['requisito_aplicabilidade'] != 'APLICAVEL'),
        },
    }


def aplicar(norma, lido: dict, usuario, data_vcl: date, criar_faltantes=True, tirar_ausentes=True,
            completar_capa=True, nome_pdf='') -> dict:
    """
    Grava. Idempotente: rodar de novo com o mesmo PDF e a mesma data não duplica
    verificação (a mesma resposta na mesma data é reconhecida).
    """
    planejado = planejar(norma, lido)
    criados = respondidos = repetidos = fotos = 0
    sem_resposta = set((norma.relatorio_anual or {}).get('sem_resposta') or [])
    fora = set((norma.relatorio_anual or {}).get('fora') or [])
    origem = f'Importada do relatório anual entregue{f" ({nome_pdf})" if nome_pdf else ""}.'

    with transaction.atomic():
        for p in planejado['plano']:
            item, req = p['item'], p['requisito']
            if req is None:
                if not criar_faltantes:
                    continue
                req = Requisito.objects.create(
                    norma=norma, referencia=item.referencia, secao=item.secao[:200],
                    descricao=item.texto_condicao or f'Condicionante {item.referencia}',
                    trecho_fonte=item.texto_condicao, tema=norma.tema, aplicabilidade='APLICAVEL',
                    periodicidade_meses=12, origem='RELATORIO', criado_por=usuario,
                )
                criados += 1
            else:
                mudou = []
                if item.secao and not req.secao:
                    req.secao = item.secao[:200]
                    mudou.append('secao')
                # Texto vazio ou encurtado pela IA ("aprovado... deverão"): vale o integral do relatório.
                cortado = '...' in (req.trecho_fonte or '') or '…' in (req.trecho_fonte or '')
                if item.texto_condicao and (not req.trecho_fonte or cortado):
                    req.trecho_fonte = item.texto_condicao
                    mudou.append('trecho_fonte')
                if item.texto_resposta and req.aplicabilidade != 'APLICAVEL':
                    # Respondida no relatório entregue ao órgão: é aplicável.
                    req.aplicabilidade = 'APLICAVEL'
                    mudou.append('aplicabilidade')
                if mudou:
                    req.save(update_fields=mudou + ['atualizado_em'])
            fora.discard(req.id)

            resposta = item.texto_resposta
            if not resposta:
                if not item.figuras:
                    sem_resposta.add(req.id)  # subitem respondido junto no item seguinte
                continue
            sem_resposta.discard(req.id)
            if req.verificacoes.filter(data=data_vcl, evidencia=resposta).exists():
                repetidos += 1
                continue
            vcl = Verificacao.objects.create(requisito=req, data=data_vcl, resultado='ATENDIDO', evidencia=resposta,
                                             observacao=origem, verificado_por=usuario)
            for f in item.figuras:
                if f.imagem is None:
                    continue
                nome = f'figura_{f.numero:02d}.{f.extensao}'
                a = EvidenciaAnexo(verificacao=vcl, nome=nome, legenda=f.legenda[:300])
                a.arquivo.save(nome, ContentFile(f.imagem), save=False)
                a.save()
                fotos += 1
            req.recalcular_situacao()
            respondidos += 1

        if tirar_ausentes:
            fora |= {r.id for r in planejado['ausentes']}
        cfg = dict(norma.relatorio_anual or {})
        cfg['sem_resposta'] = sorted(sem_resposta)
        cfg['fora'] = sorted(fora)
        if completar_capa:
            for campo in ('atividade', 'processos', 'licenca', 'item'):
                valor = lido['capa'].get(campo)
                if valor and not (cfg.get(campo) or '').strip():
                    cfg[campo] = valor
            # O padrão de licença ("Licença de Operação nº …") é trocado pelo texto do relatório.
            if lido['capa'].get('licenca') and (cfg.get('licenca') or '').startswith('Licença de Operação nº'):
                cfg['licenca'] = lido['capa']['licenca']
        norma.relatorio_anual = cfg
        norma.save(update_fields=['relatorio_anual', 'atualizado_em'])

    return {'criados': criados, 'respondidos': respondidos, 'repetidos': repetidos, 'fotos': fotos,
            'fora': len(planejado['ausentes']) if tirar_ausentes else 0}
