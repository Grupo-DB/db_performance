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
from django.db.models import Q as models_Q
from django.utils import timezone

from . import almoxarifado as ax
from . import pecas_catalogo as pc
from . import pecas_ia, pecas_ocr
from .models import (CatalogoPecas, ConjuntoPecas, DeParaPeca, EquipamentoPecas, ItemErpCatalogo, ItemKitPecas,
                     FotoEquipamentoPecas, ItemSolicitacaoPecas, KitPecas, NotificacaoPecas, PecaCatalogo, PreferenciaPecas,
                     SolicitacaoPecas)

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
             catalogo: CatalogoPecas | None = None, desenhos: bool = True, usar_ia: bool = True,
             progresso=None) -> CatalogoPecas:
    """Lê o PDF e grava (ou REGRAVA, se `catalogo` vier) conjuntos, peças e desenhos.

    Regravar apaga os conjuntos/peças antigos (os pedidos já feitos guardam código e descrição, só perdem o
    vínculo com a linha do catálogo) e mantém os equipamentos ligados ao catálogo.
    """
    paginas = pc.ler_pdf(caminho_pdf)
    lido = pc.montar_catalogo(paginas)
    origem = 'leitor'
    if not lido['conjuntos']:
        # Layout que o leitor não conhece (outro fabricante) ou PDF escaneado: a IA lê as páginas como imagem
        # e o catálogo entra "Em revisão" até alguém conferir.
        if not (usar_ia and pecas_ia.configurada()):
            raise ValueError('Nenhuma página de peças encontrada no PDF (cabeçalho "Fig. Código Qtd Descrição"). '
                             'Layout desconhecido ou PDF escaneado' +
                             (' — e a IA não está configurada no servidor.' if usar_ia else '.'))
        if progresso:
            progresso('Layout desconhecido: lendo com a IA')
        try:
            lido = pecas_ia.ler_catalogo(
                caminho_pdf, paginas,
                progresso=(lambda feitas, total: progresso(f'Lendo com a IA: página {feitas} de {total}')) if progresso else None)
        except pecas_ia.FalhaIA as exc:
            raise ValueError(f'O leitor não reconheceu o layout e a leitura pela IA falhou: {exc}')
        if not lido['conjuntos']:
            raise ValueError('Nem o leitor nem a IA acharam páginas de peças neste PDF.')
        origem = 'ia'
    if progresso:
        progresso(f'Gravando {len(lido["conjuntos"])} conjuntos e gerando os desenhos')
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
        catalogo.status, catalogo.erro = ('revisao' if origem == 'ia' else 'pronto'), ''
        catalogo.origem = origem
        catalogo.save()
        pecas = []
        for ordem, (codigo, cj) in enumerate(lido['conjuntos'].items()):

            desenho, marcas = '', []
            if desenhos and cj['y_tabela'] > 0:
                arq = pasta / _nome_arquivo(codigo)
                try:
                    pc.renderizar_desenho(destino_pdf, cj['pagina'], cj['largura'], cj['y_tabela'], arq)
                    desenho = str(arq.relative_to(PASTA))
                    marcas = pecas_ocr.marcadores(arq, [p['fig'] for p in cj['pecas']])
                except Exception:
                    logger.exception('catálogo de peças: falha no desenho de %s', codigo)
            conj = ConjuntoPecas.objects.create(catalogo=catalogo, codigo=codigo, nome=cj['nome'][:200],
                                                pagina=cj['pagina'], desenho=desenho, marcadores=marcas, ordem=ordem)
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
SELECT E.EQPCOD, E.EQPNOME, E.EQPAUTOMTAG, E.EQPDADOS, T.TEQPNOME, E.EQPPLACA, E.EQPCC, C.CCNOME, E.EQPANOFAB,
       E.EQPPROPTERC, E.EQPKMSN, E.EQPHRSN,
       CASE WHEN DATALENGTH(E.EQPDESENHO) > 100 THEN 1 ELSE 0 END AS FOTO_SGA
FROM EQUIPAMENTO E
LEFT JOIN TIPOEQUIPAMENTO T ON T.TEQPCOD = E.EQPTEQP
LEFT JOIN CENTROCUSTO C ON C.CCCOD = E.EQPCC
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
            ano = getattr(r, 'EQPANOFAB', None)
            ano = ano.year if hasattr(ano, 'year') and ano.year > 1950 else None  # 1899-12-30 é o "vazio" do SGA
            out.append({
                'codigo': int(r.EQPCOD), 'nome': nome, 'tag': str(r.EQPAUTOMTAG or '').strip(),
                'tipo': str(r.TEQPNOME or '').strip(), 'dados': dados[:1500], 'serie_sugerida': sugerir_serie(dados),
                'placa': str(getattr(r, 'EQPPLACA', '') or '').strip(),
                'centro_custo': str(getattr(r, 'CCNOME', '') or '').strip(),
                'ano_fabricacao': ano,
                'terceiro': str(getattr(r, 'EQPPROPTERC', '') or '').strip().upper() == 'T',
                'medidor': 'horimetro' if str(getattr(r, 'EQPHRSN', '') or '').upper() == 'S'
                           else 'km' if str(getattr(r, 'EQPKMSN', '') or '').upper() == 'S' else '',
                'foto_sga': bool(getattr(r, 'FOTO_SGA', 0)),
            })
        out.sort(key=lambda e: e['nome'])
        return out
    return ax._cacheado('pecas:equipamentos', CACHE_EQUIPAMENTOS, ler)


def equipamento_sga(codigo: int) -> dict | None:
    return next((e for e in equipamentos_sga() if e['codigo'] == codigo), None)


def lista_equipamentos() -> list[dict]:
    """Ativos do SGA + o que o Manager sabe (catálogo/série). Ligados primeiro."""
    ligados = {e.equipamento: e for e in EquipamentoPecas.objects.select_related('catalogo')}
    fotos = set(FotoEquipamentoPecas.objects.values_list('equipamento', flat=True))
    out = []
    for e in equipamentos_sga():
        lig = ligados.get(e['codigo'])
        out.append({**e, **_ligacao(lig), 'tem_foto': e['codigo'] in fotos or bool(e.get('foto_sga'))})
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
        if not catalogo.conjuntos.exists():
            raise ValueError('Este catálogo ainda não tem peças (está importando ou a importação falhou).')
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

def _marcar_progresso(catalogo_id: int, texto: str) -> None:
    """Grava no banco (não no cache): o cache do Django aqui é por processo e o gunicorn não veria o do Celery.
    Dentro da transação dos desenhos a gravação só aparece no fim — por isso a última fase é avisada antes."""
    CatalogoPecas.objects.filter(pk=catalogo_id).update(progresso=texto[:120], progresso_em=timezone.now())


def _status(c: CatalogoPecas) -> tuple[str, str]:
    """Importação parada (worker caiu, servidor reiniciou) aparece como erro, para dar para reenviar.

    "Parada" = enviada há mais de IMPORTACAO_TRAVADA e sem progresso nesse tempo (a leitura pela IA de um
    catálogo grande leva bem mais de meia hora, mas avança a cada lote).
    """
    if c.status == 'importando' and c.enviado_em and timezone.now() - c.enviado_em > IMPORTACAO_TRAVADA:
        ultimo = c.progresso_em
        if ultimo is None or timezone.now() - ultimo > IMPORTACAO_TRAVADA:
            antes = 'revisao' if c.origem == 'ia' else 'pronto'
            return (antes if c.n_conjuntos else 'erro'), 'A importação não terminou (o servidor pode ter reiniciado). Envie o PDF de novo.'
    return c.status, c.erro


def catalogo_dict(c: CatalogoPecas) -> dict:
    if not hasattr(c, 'n_conjuntos'):
        c.n_conjuntos = c.conjuntos.count()
    st, erro = _status(c)
    return {'id': c.id, 'nome': c.nome or 'Catálogo novo', 'fabricante': c.fabricante, 'edicao': c.edicao,
            'conjuntos': c.n_conjuntos, 'paginas': c.paginas, 'status': st, 'erro': erro, 'origem': c.origem,
            'progresso': c.progresso if st == 'importando' else '',
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
    catalogo.progresso, catalogo.progresso_em = 'Na fila para leitura', timezone.now()
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
        _marcar_progresso(cat.pk, 'Lendo as páginas do PDF')
        importar(pdf, catalogo=cat, usuario=cat.importado_por, progresso=lambda t: _marcar_progresso(cat.pk, t))
    except Exception as exc:  # noqa: BLE001 — qualquer falha precisa sair do "importando"
        logger.exception('catálogo de peças %s: falha na importação', catalogo_id)
        msg = str(exc) if isinstance(exc, (ValueError, pc.PopplerAusente)) else 'Não foi possível ler este PDF.'
        # Nova edição que falhou: a anterior continua valendo (importar é atômico), na situação em que estava.
        tem = cat.conjuntos.exists()
        anterior = 'revisao' if cat.origem == 'ia' else 'pronto'
        CatalogoPecas.objects.filter(pk=cat.pk).update(status=anterior if tem else 'erro', erro=msg)
    finally:
        pdf.unlink(missing_ok=True)
        CatalogoPecas.objects.filter(pk=cat.pk).update(progresso='')


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


def _cadastro_sga() -> list[tuple[int, str, str]]:
    """(ESTQCOD, nome, referência) de todos os itens do SGA, em cache — base do índice e da busca por nome."""
    def ler():
        df = ax._ler(_SQL_INDICE)
        return [(int(r.ESTQCOD), str(r.ESTQNOME or '').strip(), str(r.ESTQREF or '').strip())
                for r in df.itertuples(index=False)]
    return ax._cacheado('pecas:cadastro_sga', CACHE_INDICE_SGA, ler)


def _indice_sga() -> dict[str, list[int]]:
    """Token (número de 6+ dígitos ou referência) → itens do SGA que o têm no nome ou na referência."""
    def ler():
        idx: dict[str, list[int]] = {}
        for cod, nome, ref in _cadastro_sga():
            nome = nome.upper()
            ref = ref.upper()
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
    # 1º o que o comprador já confirmou (DeParaPeca); guardado como digitado, procurado com e sem o "V".
    for cod_fab, item in DeParaPeca.objects.filter(
            codigo__in=list(todas | {'V' + t for t in todas if t.isdigit()})).values_list('codigo', 'item_sga'):
        for k in _chaves_codigo(cod_fab):
            manual.setdefault(k, []).append(int(item))
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


def _aprendidos(codigos: list[str]) -> set[tuple[str, int]]:
    """(chave do código, item) já confirmados — a tela mostra "vinculado" e deixa desfazer."""
    chaves = set().union(*(_chaves_codigo(c) for c in codigos)) if codigos else set()
    out = set()
    for cod_fab, item in DeParaPeca.objects.filter(
            codigo__in=list(chaves | {'V' + t for t in chaves if t.isdigit()})).values_list('codigo', 'item_sga'):
        for k in _chaves_codigo(cod_fab):
            out.add((k, int(item)))
    return out


def sugestoes_sga(codigos: list[str]) -> dict[str, list[dict]]:
    aprendidos = _aprendidos([c for c in codigos if c])
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
        chaves = _chaves_codigo(codigo)
        for it in itens:
            it['vinculado'] = any((k, it['codigo']) in aprendidos for k in chaves)
        # O que foi confirmado primeiro, depois o que tem saldo
        itens.sort(key=lambda i: (not i['vinculado'], -(i.get('saldo') or 0)))
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
            'tem_desenho': bool(cj.desenho), 'marcadores': cj.marcadores or [], 'serie': serie, 'pecas': linhas}


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
        notificar_nova(sol, len(linhas))
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
    status_antes, resposta_antes = s.status, s.resposta
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
    notificar_mudanca(s, usuario, status_antes, resposta_antes)
    return s



# ---------------------------------------------------------------------------------------------------------
# De-para aprendido: código do fabricante → item do SGA (26/11/2026)
# ---------------------------------------------------------------------------------------------------------

_PALAVRAS_VAZIAS = {'DE', 'DO', 'DA', 'DOS', 'DAS', 'COM', 'SEM', 'PARA', 'P/', 'C/', 'S/', 'E', 'EM', 'NO', 'NA',
                    'TIPO', 'CONJ', 'CONJUNTO', 'COMPLETO', 'COMPLETA', 'PECA', 'PEÇA'}


def normalizar_codigo(codigo: str) -> str:
    return re.sub(r'\s+', '', (codigo or '').upper())[:40]


def vincular_sga(codigo: str, item_sga, usuario: User | None, origem: str = 'manual') -> DeParaPeca:
    cod = normalizar_codigo(codigo)
    if len(cod) < 3:
        raise ValueError('Peça sem código do fabricante não pode ser vinculada (o vínculo é pelo código).')
    try:
        item = int(item_sga)
    except (TypeError, ValueError):
        raise ValueError('Item do SGA inválido.')
    nome = _nomes_sga({item}).get(item)
    if not nome:
        raise ValueError(f'Item {item} não encontrado no SGA.')
    obj, criado = DeParaPeca.objects.get_or_create(
        codigo=cod, item_sga=item,
        defaults={'nome_sga': nome[:200], 'origem': origem if origem in dict(DeParaPeca.ORIGEM) else 'manual',
                  'criado_por': usuario})
    return obj


def desvincular_sga(codigo: str, item_sga) -> int:
    chaves = _chaves_codigo(normalizar_codigo(codigo)) | {normalizar_codigo(codigo)}
    chaves |= {'V' + c for c in chaves if c.isdigit()}
    return DeParaPeca.objects.filter(codigo__in=chaves, item_sga=int(item_sga)).delete()[0]


def buscar_itens_sga(termo: str, limite: int = 30) -> list[dict]:
    """Itens do SGA por código (ESTQCOD), referência ou palavras do nome — para o comprador escolher à mão."""
    termo = (termo or '').strip()
    if len(termo) < 2:
        return []
    palavras = _sem_acento(termo).upper().split()
    achados = []
    for cod, nome, ref in _cadastro_sga():
        if termo.isdigit() and (str(cod) == termo or termo in ref.replace(' ', '')):
            achados.insert(0, cod)
            continue
        alvo = _sem_acento(f'{nome} {ref}').upper()
        if all(w in alvo for w in palavras):
            achados.append(cod)
        if len(achados) >= limite * 2:
            break
    achados = list(dict.fromkeys(achados))[:limite]
    sit = _situacao_itens(set(achados))
    nomes = {c: n for c, n, _r in _cadastro_sga() if c in set(achados) - sit.keys()} if set(achados) - sit.keys() else {}
    return [sit.get(c) or {'codigo': c, 'nome': nomes.get(c, ''), 'unidade': '', 'saldo': None, 'situacao': None,
                           'em_compra': False} for c in achados]


def candidatos_sga(descricao: str, codigo: str = '', limite: int = 25) -> list[dict]:
    """Itens do SGA que dividem palavras com a descrição do fabricante. A 1ª palavra (o que a peça É) é obrigatória."""
    toks = [w for w in re.findall(r'[A-Z0-9/]{3,}', _sem_acento(descricao or '').upper()) if w not in _PALAVRAS_VAZIAS]
    if not toks:
        return []
    principal, resto = toks[0], set(toks[1:])
    cod = normalizar_codigo(codigo)
    pontos = []
    for c, nome, ref in _cadastro_sga():
        alvo = _sem_acento(nome).upper()
        if principal not in alvo:
            continue
        p = 2 + sum(1 for w in resto if w in alvo)
        if cod and len(cod) >= 5 and (cod.lstrip('V') in alvo.replace(' ', '') or cod in ref.upper()):
            p += 10
        pontos.append((p, c, nome))
    pontos.sort(key=lambda t: (-t[0], t[2]))
    return [{'codigo': c, 'nome': n, 'pontos': p} for p, c, n in pontos[:limite]]


def sugerir_sga(peca: dict) -> dict:
    """Sugestão de item do SGA para uma peça sem vínculo: IA sobre os candidatos por palavra, ou só as palavras."""
    cands = candidatos_sga(peca.get('descricao') or '', peca.get('codigo') or '')
    fonte, sug = 'palavras', []
    if cands and pecas_ia.configurada():
        try:
            sug = pecas_ia.sugerir_itens_sga(peca, cands)
            fonte = 'ia'
        except Exception:  # noqa: BLE001 — sem IA, a sugestão por palavras ainda ajuda
            logger.exception('peças: sugestão da IA falhou')
    if fonte != 'ia':
        sug = [{'item_sga': c['codigo'], 'confianca': None, 'motivo': 'Palavras da descrição em comum'}
               for c in cands[:5]]
    sit = _situacao_itens({x['item_sga'] for x in sug})
    nomes = {c['codigo']: c['nome'] for c in cands}
    for x in sug:
        x['sga'] = sit.get(x['item_sga']) or {'codigo': x['item_sga'], 'nome': nomes.get(x['item_sga'], ''),
                                              'saldo': None, 'situacao': None, 'em_compra': False}
    return {'fonte': fonte, 'ia_configurada': pecas_ia.configurada(), 'sugestoes': sug}


def definir_item_sga(item: ItemSolicitacaoPecas, item_sga, usuario: User) -> ItemSolicitacaoPecas:
    """O comprador diz qual item do SGA atende a linha da solicitação; com código do fabricante, vira de-para."""
    if item_sga in (None, ''):
        item.item_sga = None
    else:
        item.item_sga = int(item_sga)
        if item.codigo and len(normalizar_codigo(item.codigo)) >= 3:
            vincular_sga(item.codigo, item.item_sga, usuario, origem='solicitacao')
        elif not _nomes_sga({item.item_sga}):
            raise ValueError(f'Item {item.item_sga} não encontrado no SGA.')
    item.save(update_fields=['item_sga'])
    return item


# ---------------------------------------------------------------------------------------------------------
# Kits de peças
# ---------------------------------------------------------------------------------------------------------

def _linhas_de_itens(itens: list) -> list[dict]:
    """Mesmo formato do carrinho: peça do catálogo ({peca}) ou avulsa ({descricao, codigo})."""
    if not itens:
        raise ValueError('Inclua pelo menos uma peça.')
    pecas = {p.id: p for p in PecaCatalogo.objects.filter(
        id__in=[i.get('peca') for i in itens if isinstance(i.get('peca'), int)]).select_related('conjunto')}
    out = []
    for i in itens:
        q = _quantidade(i.get('quantidade') or 1)
        p = pecas.get(i.get('peca')) if isinstance(i.get('peca'), int) else None
        if p is not None:
            out.append({'peca': p, 'codigo': p.codigo, 'descricao': p.descricao[:300],
                        'conjunto': f'{p.conjunto.codigo} {p.conjunto.nome} · fig. {p.fig}'[:250], 'quantidade': q,
                        'item_sga': _int_ou_none(i.get('item_sga'))})
        else:
            desc = str(i.get('descricao') or '').strip()
            if not desc:
                raise ValueError('Peça avulsa precisa de descrição.')
            out.append({'peca': None, 'codigo': str(i.get('codigo') or '').strip()[:30], 'descricao': desc[:300],
                        'conjunto': str(i.get('conjunto') or '')[:250], 'quantidade': q,
                        'item_sga': _int_ou_none(i.get('item_sga'))})
    return out


def kit_dict(k: KitPecas, sga: bool = False) -> dict:
    itens = list(k.itens.all())
    sug = sugestoes_sga([i.codigo for i in itens if i.codigo]) if sga else {}
    return {
        'id': k.id, 'nome': k.nome, 'descricao': k.descricao, 'catalogo': k.catalogo_id,
        'criado_por': nome_usuario(k.criado_por), 'atualizado_em': k.atualizado_em.isoformat(), 'n_itens': len(itens),
        'itens': [{'id': i.id, 'peca': i.peca_id, 'codigo': i.codigo, 'descricao': i.descricao, 'conjunto': i.conjunto,
                   'quantidade': float(i.quantidade), 'item_sga': i.item_sga, 'sga': sug.get(i.codigo, [])}
                  for i in itens],
    }


def listar_kits(catalogo_id: int | None = None) -> list[dict]:
    qs = KitPecas.objects.select_related('criado_por').prefetch_related('itens')
    if catalogo_id:
        qs = qs.filter(models_Q(catalogo_id=catalogo_id) | models_Q(catalogo__isnull=True))
    return [kit_dict(k) for k in qs]


def salvar_kit(dados: dict, usuario: User, kit: KitPecas | None = None) -> KitPecas:
    nome = str(dados.get('nome') or '').strip()[:120]
    if not nome:
        raise ValueError('Dê um nome ao kit (ex.: "Revisão 500 h").')
    linhas = _linhas_de_itens(dados.get('itens') or [])
    cat = None
    if dados.get('catalogo'):
        cat = CatalogoPecas.objects.filter(pk=dados.get('catalogo')).first()
    with transaction.atomic():
        if kit is None:
            kit = KitPecas(criado_por=usuario)
        kit.nome, kit.descricao, kit.catalogo = nome, str(dados.get('descricao') or '')[:2000], cat
        kit.save()
        kit.itens.all().delete()
        ItemKitPecas.objects.bulk_create([ItemKitPecas(kit=kit, ordem=n, **l) for n, l in enumerate(linhas)])
    return kit


# ---------------------------------------------------------------------------------------------------------
# Histórico por equipamento
# ---------------------------------------------------------------------------------------------------------

def historico_equipamento(codigo: int) -> dict:
    sols = list(SolicitacaoPecas.objects.filter(equipamento=codigo).exclude(status='cancelada')
                .select_related('solicitante').prefetch_related('itens'))
    pecas: dict[str, dict] = {}
    for s in sols:
        for i in s.itens.all():
            chave = normalizar_codigo(i.codigo) or _sem_acento(i.descricao).upper()
            p = pecas.get(chave)
            if p is None:
                p = pecas[chave] = {'codigo': i.codigo, 'descricao': i.descricao, 'conjunto': i.conjunto,
                                    'peca': i.peca_id, 'vezes': 0, 'quantidade': 0.0, 'ultima': None, '_sols': set()}
            if s.id not in p['_sols']:
                p['_sols'].add(s.id)
                p['vezes'] += 1
            p['quantidade'] += float(i.quantidade)
            quando = s.criado_em.isoformat()
            if p['ultima'] is None or quando > p['ultima']:
                p['ultima'] = quando
    lista = list(pecas.values())
    lista.sort(key=lambda p: (-p['vezes'], -(datetime.fromisoformat(p['ultima']).timestamp() if p['ultima'] else 0)))
    for p in lista:
        p.pop('_sols')
    return {
        'equipamento': codigo,
        'total_solicitacoes': len(sols),
        'total_itens': sum(len(s.itens.all()) for s in sols),
        'desde': sols[-1].criado_em.isoformat() if sols else None,
        'pecas': lista[:60],
        'solicitacoes': [{'id': s.id, 'numero': s.numero, 'status': s.status, 'status_nome': s.get_status_display(),
                          'urgente': s.urgente, 'criado_em': s.criado_em.isoformat(), 'n_itens': len(s.itens.all()),
                          'solicitante': nome_usuario(s.solicitante)} for s in sols[:20]],
    }


# ---------------------------------------------------------------------------------------------------------
# Avisos: sino (NotificacaoPecas) e, se configurado, WhatsApp
# ---------------------------------------------------------------------------------------------------------

# Quem recebe solicitação nova. Admin/Master ficam de fora para não encher o sino de quem não compra.
GRUPOS_AVISO_COMPRAS = ('comprasComprador', 'comprasGestor')


def _num(s: SolicitacaoPecas) -> str:
    return f'Nº {s.numero or s.id}'


def _notificar(usuarios, sol: SolicitacaoPecas, tipo: str, mensagem: str) -> None:
    alvos = {u.id: u for u in usuarios if u is not None}
    if not alvos:
        return
    criadas = NotificacaoPecas.objects.bulk_create(
        [NotificacaoPecas(usuario_id=uid, solicitacao=sol, tipo=tipo, mensagem=mensagem[:300]) for uid in alvos])
    if getattr(settings, 'PECAS_WHATSAPP_TEMPLATE', ''):
        ids = [n.id for n in criadas if n.id]
        if not ids:  # bulk_create sem id (alguns bancos): busca as recém-criadas
            ids = list(NotificacaoPecas.objects.filter(solicitacao=sol, tipo=tipo, usuario_id__in=alvos)
                       .order_by('-id').values_list('id', flat=True)[:len(alvos)])
        transaction.on_commit(lambda: _disparar_whatsapp(ids))


def _disparar_whatsapp(ids: list[int]) -> None:
    from .tasks import whatsapp_notificacao_pecas
    for nid in ids:
        try:
            whatsapp_notificacao_pecas.delay(nid)
        except Exception:  # noqa: BLE001 — Redis fora: o sino já avisou
            logger.exception('peças: não foi possível enfileirar o WhatsApp da notificação %s', nid)


def enviar_whatsapp(notificacao_id: int) -> bool:
    """Template aprovado na Meta com 1 variável no corpo ({{1}} = a mensagem do aviso)."""
    template = getattr(settings, 'PECAS_WHATSAPP_TEMPLATE', '')
    n = NotificacaoPecas.objects.select_related('usuario').filter(pk=notificacao_id).first()
    if not template or n is None:
        return False
    pref = PreferenciaPecas.objects.filter(usuario=n.usuario).first()
    if pref is None or not pref.avisar_whatsapp or not pref.whatsapp:
        return False
    from whatsapp import graph_api
    graph_api.enviar_template(
        pref.whatsapp, template, getattr(settings, 'PECAS_WHATSAPP_IDIOMA', 'pt_BR'),
        componentes=[{'type': 'body', 'parameters': [{'type': 'text', 'text': n.mensagem[:900]}]}])
    return True


def notificar_nova(sol: SolicitacaoPecas, n_itens: int) -> None:
    usuarios = User.objects.filter(is_active=True, groups__name__in=GRUPOS_AVISO_COMPRAS).exclude(
        pk=sol.solicitante_id).distinct()
    tipo = 'URGENTE' if sol.urgente else 'NOVA'
    msg = (f'{"URGENTE · " if sol.urgente else ""}{_num(sol)} · {sol.equipamento_nome or "sem equipamento"} · '
           f'{n_itens} peça(s) · pedido por {nome_usuario(sol.solicitante)}')
    _notificar(usuarios, sol, tipo, msg)


def notificar_mudanca(sol: SolicitacaoPecas, usuario: User, status_antes: str, resposta_antes: str) -> None:
    mudou_status = sol.status != status_antes
    mudou_resposta = (sol.resposta or '') != (resposta_antes or '') and bool(sol.resposta)
    if not mudou_status and not mudou_resposta:
        return
    if usuario.id == sol.solicitante_id:
        if mudou_status and sol.status == 'cancelada' and sol.tratado_por_id and sol.tratado_por_id != usuario.id:
            _notificar([sol.tratado_por], sol, 'CANCELADA',
                       f'{_num(sol)} · {sol.equipamento_nome} · cancelada por {nome_usuario(usuario)}')
        return
    recado = f' — {sol.resposta}' if sol.resposta and (mudou_resposta or mudou_status) else ''
    if mudou_status:
        _notificar([sol.solicitante], sol, 'STATUS',
                   f'{_num(sol)} · {sol.equipamento_nome}: {sol.get_status_display()}{recado}')
    else:
        _notificar([sol.solicitante], sol, 'RESPOSTA', f'{_num(sol)} · {sol.equipamento_nome}: recado do comprador{recado}')


def notificacao_dict(n: NotificacaoPecas) -> dict:
    s = n.solicitacao
    return {'id': n.id, 'tipo': n.tipo, 'mensagem': n.mensagem, 'lido': n.lido, 'criado_em': n.criado_em.isoformat(),
            'solicitacao': s.id, 'solicitacao_numero': s.numero, 'solicitacao_status': s.status,
            'equipamento_nome': s.equipamento_nome, 'urgente': s.urgente}


def notificacoes_do_usuario(usuario: User, limite: int = 60) -> list[dict]:
    qs = NotificacaoPecas.objects.filter(usuario=usuario).select_related('solicitacao')
    return [notificacao_dict(n) for n in qs[:limite]]


def marcar_notificacoes_lidas(usuario: User, ids) -> int:
    qs = NotificacaoPecas.objects.filter(usuario=usuario, lido=False)
    if ids != 'todas':
        qs = qs.filter(pk__in=[int(i) for i in (ids or []) if str(i).isdigit()])
    return qs.update(lido=True)


def preferencia_dict(usuario: User) -> dict:
    p = PreferenciaPecas.objects.filter(usuario=usuario).first()
    return {'whatsapp': p.whatsapp if p else '', 'avisar_whatsapp': bool(p and p.avisar_whatsapp),
            'whatsapp_disponivel': bool(getattr(settings, 'PECAS_WHATSAPP_TEMPLATE', ''))}


def salvar_preferencia(usuario: User, dados: dict) -> dict:
    fone = re.sub(r'\D', '', str(dados.get('whatsapp') or ''))
    avisar = bool(dados.get('avisar_whatsapp'))
    if fone and not 10 <= len(fone) <= 13:
        raise ValueError('Celular inválido. Use DDD + número, ex.: 51 99999-0000.')
    if avisar and not fone:
        raise ValueError('Informe o celular para receber os avisos no WhatsApp.')
    PreferenciaPecas.objects.update_or_create(usuario=usuario, defaults={'whatsapp': fone, 'avisar_whatsapp': avisar})
    return preferencia_dict(usuario)


# ---------------------------------------------------------------------------------------------------------
# Revisão/edição do catálogo (o lido pela IA entra "Em revisão"; o do leitor também pode ser corrigido)
# ---------------------------------------------------------------------------------------------------------

def faixas_de_texto(v) -> list[list[int]]:
    """'233, 269-301' (ou [[233,233],[269,301]]) → [[233, 233], [269, 301]]."""
    if isinstance(v, list):
        out = []
        for f in v:
            if isinstance(f, (list, tuple)) and len(f) == 2 and all(isinstance(x, int) for x in f):
                out.append([min(f), max(f)])
        return out
    out = []
    for parte in re.split(r'[;,]', str(v or '')):
        nums = [int(x) for x in re.findall(r'\d+', parte)]
        if len(nums) == 1:
            out.append([nums[0], nums[0]])
        elif len(nums) >= 2:
            out.append([min(nums[:2]), max(nums[:2])])
    return out


def salvar_pecas_conjunto(cj: ConjuntoPecas, linhas: list) -> ConjuntoPecas:
    """Grava a tabela do conjunto como veio da tela: linha com id atualiza, sem id cria, ausente sai."""
    if not isinstance(linhas, list):
        raise ValueError('Lista de peças inválida.')
    atuais = {p.id: p for p in cj.pecas.all()}
    manter = set()
    with transaction.atomic():
        for ordem, l in enumerate(linhas):
            desc = str(l.get('descricao') or '').strip()
            cod = str(l.get('codigo') or '').strip()
            if not desc and not cod:
                continue
            campos = {'fig': str(l.get('fig') or '').strip()[:10], 'codigo': cod[:30],
                      'quantidade': str(l.get('quantidade') or '').strip()[:10], 'descricao': (desc or '-')[:300],
                      'nota': str(l.get('nota') or '').strip()[:200], 'faixas': faixas_de_texto(l.get('faixas')),
                      'ordem': ordem}
            ver = pc._VER.search(campos['nota'].upper())
            campos['ver'] = f'{ver.group(1)} {ver.group(2)}' if ver else ''
            p = atuais.get(l.get('id')) if isinstance(l.get('id'), int) else None
            if p is None:
                p = PecaCatalogo.objects.create(conjunto=cj, **campos)
            else:
                for k, v in campos.items():
                    setattr(p, k, v)
                p.save()
            manter.add(p.id)
        cj.pecas.exclude(pk__in=manter).delete()
    return cj


def editar_conjunto(cj: ConjuntoPecas, dados: dict) -> ConjuntoPecas:
    if 'nome' in dados:
        nome = str(dados.get('nome') or '').strip()
        if not nome:
            raise ValueError('O conjunto precisa de um nome.')
        cj.nome = nome[:200]
    if 'codigo' in dados:
        cod = pc.normalizar_codigo_conjunto(str(dados.get('codigo') or '').strip())[:30]
        if not cod:
            raise ValueError('O conjunto precisa de um código.')
        if ConjuntoPecas.objects.filter(catalogo_id=cj.catalogo_id, codigo=cod).exclude(pk=cj.pk).exists():
            raise ValueError(f'Já existe o conjunto {cod} neste catálogo.')
        cj.codigo = cod
    cj.save()
    return cj


def excluir_conjunto(cj: ConjuntoPecas) -> None:
    caminho = caminho_desenho(cj)
    cj.delete()
    if caminho:
        caminho.unlink(missing_ok=True)


def revisao_catalogo(cat: CatalogoPecas) -> dict:
    """Conjuntos com as peças, para a tela de conferência (sem consultar o SGA: é revisão de transcrição)."""
    conjuntos = cat.conjuntos.prefetch_related('pecas')
    return {**catalogo_dict(cat), 'conjuntos_revisao': [{
        'id': c.id, 'codigo': c.codigo, 'nome': c.nome, 'pagina': c.pagina, 'tem_desenho': bool(c.desenho),
        'pecas': [{'id': p.id, 'fig': p.fig, 'codigo': p.codigo, 'quantidade': p.quantidade, 'descricao': p.descricao,
                   'nota': p.nota, 'faixas': p.faixas} for p in c.pecas.all()],
    } for c in conjuntos]}


def publicar_catalogo(cat: CatalogoPecas) -> CatalogoPecas:
    if cat.status != 'revisao':
        raise ValueError('Só catálogo "Em revisão" precisa ser publicado.')
    if not cat.conjuntos.filter(pecas__isnull=False).exists():
        raise ValueError('O catálogo ficou sem peças.')
    cat.status, cat.erro = 'pronto', ''
    cat.save(update_fields=['status', 'erro'])
    return cat


def pagina_pdf(cat: CatalogoPecas, pagina: int) -> bytes:
    """A página inteira do PDF original em JPEG — a revisão compara a transcrição com o papel."""
    pdf = PASTA / cat.arquivo if cat.arquivo else None
    if not pdf or not pdf.exists() or not 1 <= pagina <= (cat.paginas or 0):
        raise ValueError('Página não encontrada.')
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['pdftoppm', '-f', str(pagina), '-l', str(pagina), '-r', '110', '-jpeg', '-singlefile',
                        str(pdf), str(Path(tmp) / 'p')], check=True, capture_output=True, timeout=120)
        return (Path(tmp) / 'p.jpg').read_bytes()


# ---------------------------------------------------------------------------------------------------------
# Identificar peça por foto e/ou descrição
# ---------------------------------------------------------------------------------------------------------

FOTO_TIPOS = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
FOTO_MAX_MB = 8


def identificar(cat: CatalogoPecas, foto, texto: str, serie: int | None, equipamento: str = '') -> dict:
    texto = (texto or '').strip()[:500]
    dados_foto, mime = None, ''
    if foto is not None:
        mime = (getattr(foto, 'content_type', '') or '').lower()
        if mime not in FOTO_TIPOS:
            raise ValueError('Envie a foto em JPG, PNG ou WEBP.')
        if foto.size > FOTO_MAX_MB * 1024 * 1024:
            raise ValueError(f'A foto passa de {FOTO_MAX_MB} MB.')
        dados_foto = foto.read()
    if not dados_foto and not texto:
        raise ValueError('Tire uma foto da peça ou descreva o que procura.')
    ia, aviso = None, ''
    if pecas_ia.configurada():
        try:
            ia = pecas_ia.identificar(dados_foto, mime, texto, list(cat.conjuntos.values_list('codigo', 'nome')),
                                      equipamento)
        except Exception:  # noqa: BLE001 — cai na busca por texto
            logger.exception('peças: identificação pela IA falhou')
            aviso = 'A IA não respondeu agora; mostrando só a busca pelo texto.'
    elif dados_foto:
        aviso = 'A IA não está configurada no servidor: a foto não pôde ser lida. Descreva a peça em texto.'
    codigos = list(dict.fromkeys(re.findall(r'\bV?\d{6,13}[A-Z]?\b', texto.upper()) + (ia['codigos_lidos'] if ia else [])))
    contagem: dict[int, int] = {}
    pecas: dict[int, dict] = {}
    for c in codigos:
        for p in buscar(cat, c, serie, limite=10):
            pecas[p['id']] = p
            contagem[p['id']] = contagem.get(p['id'], 0) + 10
    palavras = ia['palavras_chave'] if ia else []
    if not palavras and texto and not codigos:
        palavras = [w for w in _sem_acento(texto).upper().split() if len(w) >= 3 and w not in _PALAVRAS_VAZIAS][:4]
    for w in palavras:
        for p in buscar(cat, w, serie, limite=25):
            pecas.setdefault(p['id'], p)
            contagem[p['id']] = contagem.get(p['id'], 0) + 1
    ordem = sorted(pecas, key=lambda i: -contagem[i])[:30]
    por_codigo = {c.codigo: c for c in cat.conjuntos.all()} if ia else {}
    return {
        'ia': ia is not None, 'aviso': aviso,
        'descricao': ia['descricao'] if ia else '',
        'codigos_lidos': codigos, 'palavras_chave': palavras,
        'conjuntos': [{'id': por_codigo[c['codigo']].id, 'codigo': c['codigo'], 'nome': por_codigo[c['codigo']].nome,
                       'motivo': c['motivo']} for c in (ia['conjuntos'] if ia else []) if c['codigo'] in por_codigo],
        'pecas': [pecas[i] for i in ordem],
    }



# ---------------------------------------------------------------------------------------------------------
# Ficha do equipamento: foto, horímetro, preventivas, pedidos (26/11/2026)
# ---------------------------------------------------------------------------------------------------------

PASTA_FOTOS = PASTA / 'equipamentos'
TAMANHOS_FOTO = {'p': 480, 'g': 1400}
FOTO_EQP_MAX_MB = 15


def _arquivo_foto(codigo: int, tam: str) -> Path:
    return PASTA_FOTOS / f'{int(codigo)}_{tam}.jpg'


def _limpar_cache_foto(codigo: int) -> None:
    for tam in TAMANHOS_FOTO:
        _arquivo_foto(codigo, tam).unlink(missing_ok=True)


def _para_jpeg(bruto: bytes, lado: int) -> bytes:
    """Qualquer formato que o Pillow abre (o SGA guarda BMP de até 4 MB) → JPEG com o lado maior em `lado`."""
    import io
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(bruto))
    img = ImageOps.exif_transpose(img)  # foto de celular deitada
    img.thumbnail((lado, lado))
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=82, optimize=True)
    return out.getvalue()


def _foto_sga(codigo: int) -> bytes | None:
    df = ax._ler(f'SELECT EQPDESENHO FROM EQUIPAMENTO WHERE EQPCOD = {int(codigo)}')
    if df.empty or df.iloc[0, 0] is None:
        return None
    bruto = bytes(df.iloc[0, 0])
    return bruto if len(bruto) > 100 else None


def foto_equipamento(codigo: int, tam: str = 'p') -> bytes | None:
    """JPEG da foto: a enviada no Manager vale mais que a do SGA. Convertida uma vez e guardada em disco."""
    tam = tam if tam in TAMANHOS_FOTO else 'p'
    pronto = _arquivo_foto(codigo, tam)
    if pronto.exists():
        return pronto.read_bytes()
    bruto = None
    reg = FotoEquipamentoPecas.objects.filter(equipamento=codigo).first()
    if reg is not None:
        original = PASTA / reg.arquivo
        if original.exists():
            bruto = original.read_bytes()
    if bruto is None:
        e = equipamento_sga(codigo)
        if not e or not e.get('foto_sga'):
            return None
        bruto = _foto_sga(codigo)
        if bruto is None:
            return None
    jpg = _para_jpeg(bruto, TAMANHOS_FOTO[tam])
    PASTA_FOTOS.mkdir(parents=True, exist_ok=True)
    pronto.write_bytes(jpg)
    return jpg


def salvar_foto_equipamento(codigo: int, arquivo, usuario: User) -> None:
    if equipamento_sga(codigo) is None:
        raise ValueError('Equipamento não encontrado (ou inativo) no SGA.')
    if arquivo is None:
        raise ValueError('Escolha a foto.')
    if arquivo.size > FOTO_EQP_MAX_MB * 1024 * 1024:
        raise ValueError(f'A foto passa de {FOTO_EQP_MAX_MB} MB.')
    bruto = arquivo.read()
    try:
        jpg = _para_jpeg(bruto, 2000)  # o original guardado já reduzido: confere que é imagem e economiza disco
    except Exception:
        raise ValueError('O arquivo não é uma imagem (use JPG ou PNG).')
    PASTA_FOTOS.mkdir(parents=True, exist_ok=True)
    nome = f'{int(codigo)}_original.jpg'
    (PASTA_FOTOS / nome).write_bytes(jpg)
    FotoEquipamentoPecas.objects.update_or_create(
        equipamento=codigo, defaults={'arquivo': str((PASTA_FOTOS / nome).relative_to(PASTA)), 'enviado_por': usuario})
    _limpar_cache_foto(codigo)


def remover_foto_equipamento(codigo: int) -> None:
    reg = FotoEquipamentoPecas.objects.filter(equipamento=codigo).first()
    if reg is not None:
        (PASTA / reg.arquivo).unlink(missing_ok=True)
        reg.delete()
    _limpar_cache_foto(codigo)


def _horimetro_e_preventivas(codigo: int) -> tuple[dict | None, list[dict]]:
    """Reaproveita o Combustível: horímetro confirmado pelos abastecimentos e a próxima preventiva por plano."""
    from combustivel import erp as cerp
    from combustivel import lubrificacao
    from combustivel.views import _leituras_horimetro
    hoje = timezone.localdate()
    leituras = [l for l in _leituras_horimetro(hoje - timedelta(days=120), hoje) if l.get('equipamento') == codigo]
    atual = lubrificacao.horimetros(leituras).get(codigo)
    pend = lubrificacao.pendentes()
    pend = {**pend, 'planos': [p for p in pend['planos'] if p['equipamento'] == codigo]}
    planos = lubrificacao.preventivas(pend, {codigo: atual} if atual else {}, cerp.mapa_equipamentos(), hoje)
    return atual, [{k: p.get(k) for k in ('plano_nome', 'periodo', 'proxima_h', 'restante', 'previsao', 'situacao', 'data_ultima')}
                   for p in planos]


def ficha_equipamento(codigo: int) -> dict:
    e = equipamento_sga(codigo)
    if e is None:
        raise ValueError('Equipamento não encontrado (ou inativo) no SGA.')
    lig = EquipamentoPecas.objects.select_related('catalogo').filter(equipamento=codigo).first()
    reg_foto = FotoEquipamentoPecas.objects.select_related('enviado_por').filter(equipamento=codigo).first()
    horimetro, preventivas, aviso = None, [], ''
    try:
        horimetro, preventivas = _horimetro_e_preventivas(codigo)
    except Exception:  # noqa: BLE001 — SGA fora: a ficha abre sem esses números
        logger.exception('peças: horímetro/preventivas do equipamento %s', codigo)
        aviso = 'Horímetro e preventivas indisponíveis agora (SGA não respondeu).'
    sols = SolicitacaoPecas.objects.filter(equipamento=codigo)
    abertas = sols.filter(status__in=('aberta', 'em_compra'))
    ultima = sols.order_by('-criado_em').first()
    return {
        **e, **_ligacao(lig),
        'tem_foto': reg_foto is not None or bool(e.get('foto_sga')),
        'foto_origem': 'manager' if reg_foto else ('sga' if e.get('foto_sga') else ''),
        'foto_enviada_por': nome_usuario(reg_foto.enviado_por) if reg_foto else '',
        'horimetro': horimetro,
        'preventivas': preventivas,
        'solicitacoes_abertas': abertas.count(),
        'urgentes_abertas': abertas.filter(urgente=True).count(),
        'solicitacoes_12m': sols.filter(criado_em__gte=timezone.now() - timedelta(days=365)).exclude(status='cancelada').count(),
        'ultima_solicitacao': ultima.criado_em.isoformat() if ultima else None,
        'aviso': aviso,
    }
