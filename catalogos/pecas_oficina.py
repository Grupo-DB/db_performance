"""
Peças da oficina (26/11/2026) — o chefe da oficina pede peças a partir do catálogo oficial do fabricante.

Fluxo:
1. O catálogo em PDF sobe pela própria tela (gestor ou chefe da oficina) e é lido em segundo plano no Celery
   (`enviar_catalogo` → tasks.importar_catalogo_pecas → `executar_importacao`); o comando
   `manage.py importar_catalogo_pecas` faz o mesmo pelo terminal. Leitura em pecas_catalogo.py.
2. O chefe escolhe o equipamento do SGA (EQUIPAMENTO, ativos) e liga a um catálogo + número de série
   (EquipamentoPecas). O SGA não tem campo de modelo/série: está no texto livre "Dados Técnicos"
   (EQUIPAMENTO.EQPDADOS), que a tela mostra para ele conferir.
3. Navega pelos conjuntos (desenho + tabela, só as linhas da série dele), monta o carrinho e envia:
   SolicitacaoPecas. Fica SÓ no Manager (decisão do usuário): o comprador vê a fila e lança no SGA.

Item do SGA de cada peça (estoque, compra em andamento): procura o código do fabricante
- no mapeamento manual antigo `ItemErpCatalogo` (cod_catalogo → cod_erp), e
- no cadastro do SGA: ESTOQUE.ESTQREF (referência do fabricante, quase nunca preenchida — 129 de 31.900)
  ou o código escrito no NOME do item ("COXIM DIANTEIRO 208000418"; 76 casos do RK 430M em 26/11).
Isso é sugestão: o pedido guarda o código e a descrição do fabricante, e o item do SGA só como dica.
"""
import logging
import re
import shutil
import threading
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone

from . import almoxarifado as ax
from . import pecas_catalogo as pc
from .models import (CatalogoPecas, ConjuntoPecas, EquipamentoPecas, ItemErpCatalogo, ItemSolicitacaoPecas,
                     PecaCatalogo, SolicitacaoPecas)

logger = logging.getLogger(__name__)

PASTA = Path(getattr(settings, 'CATALOGOS_PECAS_PRIVADO', Path(settings.BASE_DIR) / 'privado' / 'catalogos_pecas'))
GRUPO_OFICINA = 'comprasOficina'
CACHE_EQUIPAMENTOS = 600
CACHE_INDICE_SGA = 3600
CODIGO_MIN = 6  # código de fabricante mais curto que isso casa com qualquer coisa ("ARRUELASSB", "SG/4561")


# ---------------------------------------------------------------------------------------------------------
# Importação do PDF
# ---------------------------------------------------------------------------------------------------------

def _nome_arquivo(codigo: str) -> str:
    return re.sub(r'[^A-Za-z0-9.]+', '_', codigo).strip('_') + '.jpg'


def importar(caminho_pdf, nome: str = '', fabricante: str = '', edicao: str = '', usuario: User | None = None,
             catalogo: CatalogoPecas | None = None, desenhos: bool = True) -> CatalogoPecas:
    """Lê o PDF e grava (ou REGRAVA, se `catalogo` vier) conjuntos, peças e desenhos.

    Regravar apaga os conjuntos/peças antigos (os pedidos já feitos guardam código e descrição, só perdem o
    vínculo com a linha do catálogo) e mantém os equipamentos ligados ao catálogo.
    """
    paginas = pc.ler_pdf(caminho_pdf)
    lido = pc.montar_catalogo(paginas)
    if not lido['conjuntos']:
        raise ValueError('Nenhuma página de peças encontrada no PDF (cabeçalho "Fig. Código Qtd Descrição").')
    with transaction.atomic():
        if catalogo is None:
            catalogo = CatalogoPecas.objects.create(nome=nome or lido['modelo'] or 'Catálogo', fabricante=fabricante,
                                                    edicao=edicao, importado_por=usuario)
        else:
            catalogo.conjuntos.all().delete()
            if nome:
                catalogo.nome = nome
            elif not catalogo.nome:  # enviado pela tela sem nome: usa o modelo escrito nas páginas
                catalogo.nome = (lido['modelo'] or 'Catálogo')[:120]
            if fabricante:
                catalogo.fabricante = fabricante
            if edicao:
                catalogo.edicao = edicao
            catalogo.importado_por = usuario or catalogo.importado_por
        pasta = PASTA / str(catalogo.pk)
        pasta.mkdir(parents=True, exist_ok=True)
        destino_pdf = pasta / 'catalogo.pdf'
        if Path(caminho_pdf).resolve() != destino_pdf.resolve():
            shutil.copyfile(caminho_pdf, destino_pdf)
        catalogo.arquivo = str(destino_pdf.relative_to(PASTA))
        catalogo.paginas = len(paginas)
        catalogo.status, catalogo.erro = 'pronto', ''
        catalogo.save()
        pecas = []
        for ordem, (codigo, cj) in enumerate(lido['conjuntos'].items()):
            desenho = ''
            if desenhos:
                arq = pasta / _nome_arquivo(codigo)
                try:
                    pc.renderizar_desenho(destino_pdf, cj['pagina'], cj['largura'], cj['y_tabela'], arq)
                    desenho = str(arq.relative_to(PASTA))
                except Exception:
                    logger.exception('catálogo de peças: falha no desenho de %s', codigo)
            conj = ConjuntoPecas.objects.create(catalogo=catalogo, codigo=codigo, nome=cj['nome'][:200],
                                                pagina=cj['pagina'], desenho=desenho, ordem=ordem)
            for i, p in enumerate(cj['pecas']):
                pecas.append(PecaCatalogo(conjunto=conj, fig=p['fig'][:10], codigo=p['codigo'][:30],
                                          quantidade=p['qtd'][:10], descricao=p['descricao'][:300] or '-',
                                          nota=p['nota'][:200], ver=p['ver'][:30], faixas=p['faixas'], ordem=i))
        PecaCatalogo.objects.bulk_create(pecas, batch_size=500)
    return catalogo


def caminho_desenho(conjunto: ConjuntoPecas) -> Path | None:
    if not conjunto.desenho:
        return None
    p = (PASTA / conjunto.desenho).resolve()
    if PASTA.resolve() not in p.parents or not p.exists():
        return None
    return p


# ---------------------------------------------------------------------------------------------------------
# Equipamentos do SGA
# ---------------------------------------------------------------------------------------------------------

_SQL_EQUIPAMENTOS = """
SELECT E.EQPCOD, E.EQPNOME, E.EQPAUTOMTAG, E.EQPDADOS, T.TEQPNOME
FROM EQUIPAMENTO E
LEFT JOIN TIPOEQUIPAMENTO T ON T.TEQPCOD = E.EQPTEQP
WHERE ISNULL(E.EQPINATIVO, 'N') <> 'S'
"""


def texto_dados(raw) -> str:
    """EQPDADOS (varbinary com texto, às vezes RTF) → texto legível."""
    if raw is None:
        return ''
    if isinstance(raw, (bytes, bytearray, memoryview)):
        b = bytes(raw)
        try:
            s = b.decode('utf-8')
        except UnicodeDecodeError:
            s = b.decode('cp1252', errors='replace')
    else:
        s = str(raw)
    if s.lstrip().startswith('{\\rtf'):
        s = re.sub(r'\\par[d]?\b', '\n', s)
        s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode('cp1252'), s)
        s = re.sub(r'\\[a-zA-Z]+-?\d* ?|[{}]', '', s)
    s = s.replace('\r\n', '\n').replace('\n\r', '\n').replace('\r', '\n')
    linhas = [re.sub(r'[ \t]+', ' ', l).strip() for l in s.split('\n')]
    return '\n'.join(l for l in linhas if l).strip()


_SERIE = re.compile(r'(?:N[RºO°]*\.?\s*(?:DE\s+)?S[EÉ]RIE|S[EÉ]RIE|CHASSI)\s*[:.]?\s*([A-Z0-9\-]{4,25})', re.I)


def sugerir_serie(dados: str) -> int | None:
    """Os números finais da série do "Dados Técnicos" (5A430BSZCB0406 → 406). Só sugestão: o chefe confirma."""
    for m in _SERIE.finditer(dados or ''):
        fim = re.search(r'(\d{2,4})$', m.group(1))
        if fim:
            return int(fim.group(1))
    return None


def equipamentos_sga() -> list[dict]:
    def ler():
        df = ax._ler(_SQL_EQUIPAMENTOS)
        out = []
        for r in df.itertuples(index=False):
            nome = str(r.EQPNOME or '').strip()
            if not nome:
                continue
            dados = texto_dados(r.EQPDADOS)
            out.append({
                'codigo': int(r.EQPCOD), 'nome': nome, 'tag': str(r.EQPAUTOMTAG or '').strip(),
                'tipo': str(r.TEQPNOME or '').strip(), 'dados': dados[:1500], 'serie_sugerida': sugerir_serie(dados),
            })
        out.sort(key=lambda e: e['nome'])
        return out
    return ax._cacheado('pecas:equipamentos', CACHE_EQUIPAMENTOS, ler)


def equipamento_sga(codigo: int) -> dict | None:
    return next((e for e in equipamentos_sga() if e['codigo'] == codigo), None)


def lista_equipamentos() -> list[dict]:
    """Ativos do SGA + o que o Manager sabe (catálogo/série). Ligados primeiro."""
    ligados = {e.equipamento: e for e in EquipamentoPecas.objects.select_related('catalogo')}
    out = []
    for e in equipamentos_sga():
        lig = ligados.get(e['codigo'])
        out.append({**e, **_ligacao(lig)})
    out.sort(key=lambda e: (e['catalogo'] is None, e['nome']))
    return out


def _ligacao(lig: EquipamentoPecas | None) -> dict:
    if lig is None or lig.catalogo_id is None:
        return {'catalogo': None, 'catalogo_nome': '', 'serie': lig.serie if lig else None}
    return {'catalogo': lig.catalogo_id, 'catalogo_nome': lig.catalogo.nome, 'serie': lig.serie}


def ligar_equipamento(codigo: int, catalogo_id: int | None, serie, usuario: User) -> dict:
    eqp = equipamento_sga(codigo)
    if eqp is None:
        raise ValueError('Equipamento não encontrado (ou inativo) no SGA.')
    catalogo = None
    if catalogo_id:
        catalogo = CatalogoPecas.objects.filter(pk=catalogo_id).first()
        if catalogo is None:
            raise ValueError('Catálogo não encontrado.')
    if serie in ('', None):
        serie = None
    else:
        try:
            serie = int(serie)
        except (TypeError, ValueError):
            raise ValueError('Número de série deve ser um número inteiro (o das colunas Início/Fim do catálogo).')
        if serie < 0:
            raise ValueError('Número de série inválido.')
    lig, _ = EquipamentoPecas.objects.update_or_create(
        equipamento=codigo, defaults={'nome': eqp['nome'][:200], 'catalogo': catalogo, 'serie': serie,
                                      'alterado_por': usuario})
    return {**eqp, **_ligacao(lig)}


# ---------------------------------------------------------------------------------------------------------
# Catálogo para a tela
# ---------------------------------------------------------------------------------------------------------

def _status(c: CatalogoPecas) -> tuple[str, str]:
    """Importação que passou do prazo (worker caiu, servidor reiniciou) aparece como erro, para dar para reenviar."""
    if c.status == 'importando' and c.enviado_em and timezone.now() - c.enviado_em > IMPORTACAO_TRAVADA:
        return ('pronto' if c.n_conjuntos else 'erro'), 'A importação não terminou (o servidor pode ter reiniciado). Envie o PDF de novo.'
    return c.status, c.erro


def catalogo_dict(c: CatalogoPecas) -> dict:
    if not hasattr(c, 'n_conjuntos'):
        c.n_conjuntos = c.conjuntos.count()
    st, erro = _status(c)
    return {'id': c.id, 'nome': c.nome or 'Catálogo novo', 'fabricante': c.fabricante, 'edicao': c.edicao,
            'conjuntos': c.n_conjuntos, 'paginas': c.paginas, 'status': st, 'erro': erro,
            'importado_em': c.importado_em.isoformat(),
            'enviado_em': c.enviado_em.isoformat() if c.enviado_em else None,
            'importado_por': nome_usuario(c.importado_por)}


def catalogos() -> list[dict]:
    return [catalogo_dict(c) for c in
            CatalogoPecas.objects.select_related('importado_por').annotate(n_conjuntos=Count('conjuntos'))]


# ---------------------------------------------------------------------------------------------------------
# Envio pela tela (26/11/2026): o PDF sobe, a leitura roda no Celery e a tela acompanha pela situação
# ---------------------------------------------------------------------------------------------------------

PDF_MAX_MB = 200
IMPORTACAO_TRAVADA = timedelta(minutes=30)
_ENVIADO = 'enviado.pdf'


def _texto(dados, campo: str, limite: int) -> str | None:
    v = dados.get(campo)
    return None if v is None else str(v).strip()[:limite]


def enviar_catalogo(arquivo, dados, usuario: User, catalogo: CatalogoPecas | None = None) -> CatalogoPecas:
    """Grava o PDF enviado e dispara a leitura. `catalogo` = nova edição de um catálogo já existente."""
    if arquivo is None:
        raise ValueError('Escolha o PDF do catálogo.')
    if arquivo.size > PDF_MAX_MB * 1024 * 1024:
        raise ValueError(f'O PDF passa de {PDF_MAX_MB} MB.')
    cabeca = arquivo.read(5)
    arquivo.seek(0)
    if cabeca != b'%PDF-':
        raise ValueError('O arquivo não é um PDF.')
    if not pc.tem_poppler():
        raise ValueError('O servidor não tem o poppler-utils (pdftotext/pdftoppm) para ler o PDF.')
    if catalogo is not None and _status(_com_conjuntos(catalogo))[0] == 'importando':
        raise ValueError('Este catálogo ainda está sendo importado. Espere terminar.')
    if catalogo is None:
        catalogo = CatalogoPecas(nome='', status='importando')
    for campo, limite in (('nome', 120), ('fabricante', 80), ('edicao', 60)):
        v = _texto(dados, campo, limite)
        if v is not None and (v or campo != 'nome'):
            setattr(catalogo, campo, v)
    catalogo.status, catalogo.erro, catalogo.enviado_em = 'importando', '', timezone.now()
    catalogo.importado_por = usuario
    catalogo.save()
    pasta = PASTA / str(catalogo.pk)
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / _ENVIADO, 'wb') as f:
        for pedaco in arquivo.chunks():
            f.write(pedaco)
    pk = catalogo.pk
    transaction.on_commit(lambda: _disparar(pk))
    return catalogo


def _com_conjuntos(c: CatalogoPecas) -> CatalogoPecas:
    c.n_conjuntos = c.conjuntos.count()
    return c


def _disparar(catalogo_id: int) -> None:
    """Celery; se o broker não responder, lê numa thread do próprio gunicorn para o envio não se perder."""
    from .tasks import importar_catalogo_pecas
    try:
        importar_catalogo_pecas.delay(catalogo_id)
    except Exception:  # noqa: BLE001 — Redis fora: não deixa o catálogo preso em "importando"
        logger.exception('catálogo de peças %s: Celery indisponível, importando numa thread', catalogo_id)
        threading.Thread(target=executar_importacao, args=(catalogo_id,), daemon=True).start()


def executar_importacao(catalogo_id: int) -> None:
    cat = CatalogoPecas.objects.filter(pk=catalogo_id).first()
    if cat is None:
        return
    pdf = PASTA / str(cat.pk) / _ENVIADO
    try:
        if not pdf.exists():
            raise ValueError('O PDF enviado não foi encontrado no servidor. Envie de novo.')
        importar(pdf, catalogo=cat, usuario=cat.importado_por)
    except Exception as exc:  # noqa: BLE001 — qualquer falha precisa sair do "importando"
        logger.exception('catálogo de peças %s: falha na importação', catalogo_id)
        msg = str(exc) if isinstance(exc, (ValueError, pc.PopplerAusente)) else 'Não foi possível ler este PDF.'
        tem = cat.conjuntos.exists()  # nova edição que falhou: a anterior continua valendo (importar é atômico)
        CatalogoPecas.objects.filter(pk=cat.pk).update(status='pronto' if tem else 'erro', erro=msg)
    else:
        CatalogoPecas.objects.filter(pk=cat.pk).update(status='pronto', erro='')
    finally:
        pdf.unlink(missing_ok=True)


def editar_catalogo(cat: CatalogoPecas, dados) -> CatalogoPecas:
    for campo, limite in (('nome', 120), ('fabricante', 80), ('edicao', 60)):
        v = _texto(dados, campo, limite)
        if v is not None:
            if campo == 'nome' and not v:
                raise ValueError('O catálogo precisa de um nome.')
            setattr(cat, campo, v)
    cat.save(update_fields=['nome', 'fabricante', 'edicao'])
    return cat


def excluir_catalogo(cat: CatalogoPecas) -> None:
    """Equipamentos ligados ficam sem catálogo; pedidos já feitos guardam código e descrição."""
    pasta = PASTA / str(cat.pk)
    cat.delete()
    shutil.rmtree(pasta, ignore_errors=True)


def faixas_catalogo(catalogo: CatalogoPecas) -> list[list[int]]:
    """Faixas de série distintas do catálogo (RK 430M: [[233, 233], [269, 301]]), para a tela avisar quando a
    série do equipamento não cai em nenhuma — aí filtrar esconderia tudo, e a tela mostra o catálogo inteiro."""
    vistas = set()
    for faixas in PecaCatalogo.objects.filter(conjunto__catalogo=catalogo).values_list('faixas', flat=True):
        for f in faixas or []:
            if isinstance(f, (list, tuple)) and len(f) == 2:
                vistas.add((int(f[0]), int(f[1])))
    return [list(f) for f in sorted(vistas)]


def serie_no_catalogo(catalogo: CatalogoPecas, serie: int | None) -> bool:
    return serie is None or any(a <= serie <= b for a, b in faixas_catalogo(catalogo))


def indice(catalogo: CatalogoPecas, serie: int | None = None) -> list[dict]:
    """Conjuntos do catálogo (só os que têm alguma linha valendo para a série) com nº de peças."""
    pecas_por_conj: dict[int, list] = {}
    for cj_id, faixas in PecaCatalogo.objects.filter(conjunto__catalogo=catalogo).values_list('conjunto_id', 'faixas'):
        pecas_por_conj.setdefault(cj_id, []).append(faixas)
    out = []
    for cj in catalogo.conjuntos.all():
        lista = pecas_por_conj.get(cj.id, [])
        validas = sum(1 for f in lista if pc.vale_para_serie(f, serie))
        if serie is not None and lista and not validas:
            continue
        out.append({'id': cj.id, 'codigo': cj.codigo, 'nome': cj.nome, 'pagina': cj.pagina,
                    'pecas': validas, 'tem_desenho': bool(cj.desenho)})
    return out


def _chaves_codigo(codigo: str) -> set[str]:
    """'V218004412' e '218004412' são o mesmo; '370200202K' também aparece sem o K."""
    c = (codigo or '').strip().upper()
    if len(c) < CODIGO_MIN:
        return set()
    chaves = {c}
    m = re.fullmatch(r'V?(\d{6,13})[A-Z]?', c)
    if m:
        chaves.add(m.group(1))
    return chaves


_SQL_INDICE = """
SELECT ESTQCOD, ESTQNOME, ESTQREF FROM ESTOQUE
"""


def _indice_sga() -> dict[str, list[int]]:
    """Token (número de 6+ dígitos ou referência) → itens do SGA que o têm no nome ou na referência."""
    def ler():
        idx: dict[str, list[int]] = {}
        df = ax._ler(_SQL_INDICE)
        for r in df.itertuples(index=False):
            cod = int(r.ESTQCOD)
            nome = str(r.ESTQNOME or '').upper()
            ref = str(r.ESTQREF or '').strip().upper()
            toks = set(re.findall(r'(?<![0-9])\d{6,13}(?![0-9])', nome))
            toks |= set(re.findall(r'\bV?\d{6,13}[A-Z]?\b', nome))
            if len(ref) >= CODIGO_MIN:
                toks.add(ref)
                toks |= set(re.findall(r'\d{6,13}', ref))
            for t in toks:
                idx.setdefault(t, []).append(cod)
        return idx
    return ax._cacheado('pecas:indice_sga', CACHE_INDICE_SGA, ler)


def itens_sga(codigos: list[str]) -> dict[str, list[int]]:
    """Código do fabricante → ESTQCODs do SGA (mapeamento manual primeiro, depois nome/referência)."""
    pedidos = {c: _chaves_codigo(c) for c in codigos if c}
    todas = set().union(*pedidos.values()) if pedidos else set()
    manual: dict[str, list[int]] = {}
    if todas:
        for cod_cat, cod_erp in ItemErpCatalogo.objects.filter(cod_catalogo__in=list(todas)).values_list(
                'cod_catalogo', 'cod_erp'):
            try:
                manual.setdefault(cod_cat.strip().upper(), []).append(int(cod_erp))
            except (TypeError, ValueError):
                pass
    try:
        idx = _indice_sga()
    except Exception:
        logger.exception('peças da oficina: falha ao ler o índice de itens do SGA')
        idx = {}
    out = {}
    for c, chaves in pedidos.items():
        achados: list[int] = []
        for k in chaves:
            for cod in manual.get(k, []) + idx.get(k, []):
                if cod not in achados:
                    achados.append(cod)
        if achados:
            out[c] = achados
    return out


def _situacao_itens(cods: set[int]) -> dict[int, dict]:
    """Saldo/compra dos itens do SGA na matriz, pelo mesmo cálculo da Visão Geral (em cache)."""
    if not cods:
        return {}
    try:
        df, _erp, _prazos = ax._preparado(0)
    except Exception:
        logger.exception('peças da oficina: falha ao ler o estoque')
        return {}
    sub = df[df.ESTQCOD.astype(int).isin(cods)]
    out = {}
    for r in sub.itertuples(index=False):
        it = ax._item(r)
        out[it['codigo']] = {k: it.get(k) for k in (
            'codigo', 'nome', 'unidade', 'saldo', 'saldo_fabrica', 'localizacao', 'situacao', 'em_compra',
            'compra_etapa', 'compra_texto', 'tem_foto')}
    return out


def _nomes_sga(cods: set[int]) -> dict[int, str]:
    if not cods:
        return {}
    lista = ','.join(str(int(c)) for c in cods)
    try:
        df = ax._ler(f'SELECT ESTQCOD, ESTQNOME FROM ESTOQUE WHERE ESTQCOD IN ({lista})')
    except Exception:
        return {}
    return {int(r.ESTQCOD): str(r.ESTQNOME or '').strip() for r in df.itertuples(index=False)}


def sugestoes_sga(codigos: list[str]) -> dict[str, list[dict]]:
    mapa = itens_sga(codigos)
    cods = {c for lst in mapa.values() for c in lst}
    sit = _situacao_itens(cods)
    faltam = cods - sit.keys()
    nomes = _nomes_sga(faltam)
    out = {}
    for codigo, lst in mapa.items():
        itens = []
        for c in lst:
            if c in sit:
                itens.append(sit[c])
            else:
                itens.append({'codigo': c, 'nome': nomes.get(c, ''), 'unidade': '', 'saldo': None,
                              'situacao': None, 'em_compra': False})
        # O que tem saldo primeiro
        itens.sort(key=lambda i: -(i.get('saldo') or 0))
        out[codigo] = itens
    return out


def _peca_dict(p: PecaCatalogo, sga: dict[str, list[dict]]) -> dict:
    return {'id': p.id, 'fig': p.fig, 'codigo': p.codigo, 'quantidade': p.quantidade, 'descricao': p.descricao,
            'nota': p.nota, 'ver': p.ver, 'faixas': p.faixas, 'sga': sga.get(p.codigo, [])}


def conjunto(cj: ConjuntoPecas, serie: int | None = None) -> dict:
    pecas = [p for p in cj.pecas.all() if pc.vale_para_serie(p.faixas, serie)]
    sga = sugestoes_sga([p.codigo for p in pecas])
    ver_ids = dict(ConjuntoPecas.objects.filter(catalogo_id=cj.catalogo_id, codigo__in={p.ver for p in pecas if p.ver})
                   .values_list('codigo', 'id'))
    linhas = []
    for p in pecas:
        d = _peca_dict(p, sga)
        d['ver_id'] = ver_ids.get(p.ver)
        linhas.append(d)
    return {'id': cj.id, 'codigo': cj.codigo, 'nome': cj.nome, 'pagina': cj.pagina, 'catalogo': cj.catalogo_id,
            'tem_desenho': bool(cj.desenho), 'serie': serie, 'pecas': linhas}


def _sem_acento(s: str) -> str:
    import unicodedata
    return ''.join(ch for ch in unicodedata.normalize('NFD', s or '') if unicodedata.category(ch) != 'Mn').upper()


def buscar(catalogo: CatalogoPecas, termo: str, serie: int | None = None, limite: int = 80) -> list[dict]:
    """Busca por código (com ou sem o V) ou por palavras da descrição, no catálogo todo."""
    termo = (termo or '').strip()
    if len(termo) < 2:
        return []
    qs = PecaCatalogo.objects.filter(conjunto__catalogo=catalogo).select_related('conjunto')
    palavras = _sem_acento(termo).split()
    cod = re.sub(r'\s+', '', termo.upper())
    if re.fullmatch(r'V?\d{4,13}[A-Z]?', cod):
        qs = qs.filter(codigo__icontains=cod.lstrip('V'))
    else:
        for w in palavras:
            qs = qs.filter(descricao__icontains=w) if w.isascii() else qs
    out = []
    for p in qs[: limite * 3]:
        if not pc.vale_para_serie(p.faixas, serie):
            continue
        if not re.fullmatch(r'V?\d{4,13}[A-Z]?', cod):
            desc = _sem_acento(p.descricao + ' ' + p.nota)
            if not all(w in desc for w in palavras):
                continue
        out.append(p)
        if len(out) >= limite:
            break
    sga = sugestoes_sga([p.codigo for p in out])
    return [{**_peca_dict(p, sga), 'conjunto_id': p.conjunto_id, 'conjunto_codigo': p.conjunto.codigo,
             'conjunto_nome': p.conjunto.nome} for p in out]


# ---------------------------------------------------------------------------------------------------------
# Solicitações
# ---------------------------------------------------------------------------------------------------------

def nome_usuario(u: User | None) -> str:
    if u is None:
        return ''
    try:
        col = getattr(u, 'colaborador', None)
        if col is not None and getattr(col, 'nome', ''):
            return col.nome
    except Exception:
        pass
    return u.get_full_name() or u.username


def _quantidade(v) -> Decimal:
    try:
        q = Decimal(str(v).replace(',', '.'))
    except (InvalidOperation, TypeError):
        raise ValueError('Quantidade inválida.')
    if q <= 0:
        raise ValueError('Quantidade tem de ser maior que zero.')
    return q.quantize(Decimal('0.01'))


def criar_solicitacao(dados: dict, usuario: User) -> SolicitacaoPecas:
    itens = dados.get('itens') or []
    if not itens:
        raise ValueError('Inclua pelo menos uma peça.')
    if len(itens) > 200:
        raise ValueError('Muitas peças numa solicitação só (máximo 200).')
    eqp_cod = dados.get('equipamento')
    eqp = None
    if eqp_cod not in (None, ''):
        try:
            eqp_cod = int(eqp_cod)
        except (TypeError, ValueError):
            raise ValueError('Equipamento inválido.')
        eqp = equipamento_sga(eqp_cod)
        if eqp is None:
            raise ValueError('Equipamento não encontrado (ou inativo) no SGA.')
    lig = EquipamentoPecas.objects.filter(equipamento=eqp_cod).first() if eqp else None
    pecas = {p.id: p for p in PecaCatalogo.objects.filter(
        id__in=[i.get('peca') for i in itens if isinstance(i.get('peca'), int)]).select_related('conjunto')}
    linhas = []
    for i in itens:
        q = _quantidade(i.get('quantidade'))
        p = pecas.get(i.get('peca')) if isinstance(i.get('peca'), int) else None
        if p is not None:
            linhas.append(ItemSolicitacaoPecas(
                peca=p, codigo=p.codigo, descricao=p.descricao[:300],
                conjunto=f'{p.conjunto.codigo} {p.conjunto.nome} · fig. {p.fig}'[:250], quantidade=q,
                item_sga=_int_ou_none(i.get('item_sga')), observacao=str(i.get('observacao') or '')[:300]))
        else:
            desc = str(i.get('descricao') or '').strip()
            if not desc:
                raise ValueError('Peça avulsa precisa de descrição.')
            linhas.append(ItemSolicitacaoPecas(
                codigo=str(i.get('codigo') or '').strip()[:30], descricao=desc[:300], quantidade=q,
                item_sga=_int_ou_none(i.get('item_sga')), observacao=str(i.get('observacao') or '')[:300]))
    with transaction.atomic():
        ultimo = SolicitacaoPecas.objects.select_for_update().aggregate(m=Max('numero'))['m'] or 0
        sol = SolicitacaoPecas.objects.create(
            numero=ultimo + 1, equipamento=eqp_cod if eqp else None, equipamento_nome=(eqp or {}).get('nome', '')[:200],
            catalogo=lig.catalogo if lig else None, serie=lig.serie if lig else None, solicitante=usuario,
            urgente=bool(dados.get('urgente')), observacao=str(dados.get('observacao') or '')[:2000])
        for l in linhas:
            l.solicitacao = sol
        ItemSolicitacaoPecas.objects.bulk_create(linhas)
    return sol


def _int_ou_none(v):
    try:
        return int(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


def solicitacao_dict(s: SolicitacaoPecas, com_itens: bool = True, sga: bool = False) -> dict:
    d = {
        'id': s.id, 'numero': s.numero, 'equipamento': s.equipamento, 'equipamento_nome': s.equipamento_nome,
        'catalogo': s.catalogo_id, 'serie': s.serie, 'status': s.status, 'status_nome': s.get_status_display(),
        'urgente': s.urgente, 'observacao': s.observacao, 'resposta': s.resposta,
        'solicitante': nome_usuario(s.solicitante), 'solicitante_id': s.solicitante_id,
        'tratado_por': nome_usuario(s.tratado_por), 'criado_em': s.criado_em.isoformat(),
        'atualizado_em': s.atualizado_em.isoformat(),
    }
    itens = list(s.itens.all())
    d['n_itens'] = len(itens)
    if com_itens:
        situ = _situacao_itens({i.item_sga for i in itens if i.item_sga}) if sga else {}
        d['itens'] = [{
            'id': i.id, 'peca': i.peca_id, 'codigo': i.codigo, 'descricao': i.descricao, 'conjunto': i.conjunto,
            'quantidade': float(i.quantidade), 'item_sga': i.item_sga, 'observacao': i.observacao,
            'sga': situ.get(i.item_sga) if i.item_sga else None,
        } for i in itens]
    return d


def listar_solicitacoes(status: str | None = None, so_do_usuario: User | None = None, limite: int = 300) -> list[dict]:
    qs = SolicitacaoPecas.objects.select_related('solicitante', 'tratado_por').prefetch_related('itens')
    if status == 'abertas':
        qs = qs.filter(status__in=('aberta', 'em_compra'))
    elif status in dict(SolicitacaoPecas.STATUS):
        qs = qs.filter(status=status)
    if so_do_usuario is not None:
        qs = qs.filter(solicitante=so_do_usuario)
    return [solicitacao_dict(s) for s in qs[:limite]]


def atualizar_solicitacao(s: SolicitacaoPecas, dados: dict, usuario: User, pode_tratar: bool) -> SolicitacaoPecas:
    novo = dados.get('status')
    if novo is not None:
        if novo not in dict(SolicitacaoPecas.STATUS):
            raise ValueError('Situação inválida.')
        if not pode_tratar:
            # Quem pediu só pode cancelar a própria enquanto está aberta.
            if not (novo == 'cancelada' and s.solicitante_id == usuario.id and s.status == 'aberta'):
                raise PermissionError('Só o comprador muda a situação da solicitação.')
        s.status = novo
        s.tratado_por = usuario if pode_tratar else s.tratado_por
    if 'resposta' in dados:
        if not pode_tratar:
            raise PermissionError('Só o comprador responde a solicitação.')
        s.resposta = str(dados.get('resposta') or '')[:2000]
        s.tratado_por = usuario
    s.save()
    return s
