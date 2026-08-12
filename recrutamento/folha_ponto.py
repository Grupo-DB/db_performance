"""
Leitura do espelho de ponto (folha ponto) em PDF — fonte do absenteísmo.

O escritório contábil manda, por competência, um ZIP com um PDF por setor
gerado pelo **iPonto 6.10.01**. Cada página é o cartão de ponto de uma pessoa
no mês (conferido: páginas == cartões, 1:1).

Por que ler por COORDENADA e não por texto corrido
--------------------------------------------------
O conjunto de colunas de hora **muda de cartão para cartão**: quem não fez hora
extra não tem a coluna ``H. Extra``, quem nunca faltou não tem ``H. Falt.``.
Já apareceram 15 combinações diferentes nos 3 meses. Ler por posição de texto
atribui valor à coluna errada, então cada valor ``HH:MM`` é casado com o rótulo
de cabeçalho mais próximo em x.

Duas armadilhas do relatório, ambas descobertas em cima dos dados reais:

1. **O quadro de horários do colaborador fica na mesma faixa vertical da ficha**
   (à direita, x >= ``X_FICHA``). Sem cortar por x, o setor sai como
   ``'MANUTENÇÃO INDUSTRIAL Sexta 07:10 12:00 13:00 15:30'``.
2. **Cargo comprido transborda por cima do rótulo "Setor:"**: em
   ``MECÂNICO DE MANUT MÁQUINAS PESADAS III`` o "III" é impresso dentro da caixa
   do rótulo e, na ordem de x, vem depois dele — virava ``'III MÁQUINAS
   PESADAS'``. Por isso o valor de um campo começa depois da BORDA DIREITA do
   rótulo, não depois dele na ordem de leitura.

Semântica do fechamento (o que sustenta os índices)
---------------------------------------------------
A linha ``D. Trab.: 25  D. Falt.: 1  DSR:4  DDSR: 1  Folgas: 4`` sai em 100%
dos cartões, e o dia marcado ``Falta`` na grade **não é** necessariamente falta
contada:

- ``Falta`` + horas em ``H. Abonada`` → falta **justificada**, não entra em
  ``D. Falt.`` (nos 90 dias apurados: 553 dias, 75% do total)
- ``Falta`` + horas em ``H. Falt.`` → falta **descontada** (180 dias), mas
  ``D. Falt.`` só conta o dia INTEIRO (106) — saída antecipada vira hora
- dias de férias, atestado e afastamento INSS **não entram em ``D. Trab.``**,
  ou seja, o denominador do fechamento já exclui ausência justificada

Conferência feita na importação inicial (1.175 cartões, 26/04 a 25/07/2026):
dias da grade == dias do período em 1.175/1.175; soma dos valores diários ==
linha de totais em 4.151/4.152 colunas-cartão (a única divergência é 1 minuto
de arredondamento do próprio iPonto).
"""

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from datetime import date

# ---------------------------------------------------------------------------
# Extração de palavras com caixa delimitadora
# ---------------------------------------------------------------------------
# Devolve uma lista de páginas, cada página uma lista de {x, x2, y, cx, t}, com
# y crescendo PARA BAIXO.
#
# ⚠️ DEPENDÊNCIA DE SISTEMA: `pdftotext` (pacote `poppler-utils`).
#
# Foi tentado o `pdfminer.six`, que entraria por requirements.txt e dispensaria
# o pacote do sistema. Reprovou: ele não emite glifo de espaço neste PDF (saído
# do "Microsoft: Print To PDF"), então a separação de palavras depende só de
# distância e sai errada nos dois sentidos — funde "Domingo Domingo Domingo" da
# grade numa palavra só (o dia deixa de ser folga) e corta "MANUTENÇÃO
# INDUSTRIAL" no meio. Numa amostra de 12 PDFs, 0 de 169 cartões saíram iguais
# ao poppler, com dias de atestado e de folga a menos.
#
# O risco de índice silenciosamente errado é pior do que uma dependência nova,
# então aqui é o poppler ou nada: sem ele a importação PARA com recado.


class PopplerAusente(RuntimeError):
    """`pdftotext` não está instalado — a importação não pode continuar."""

_WORD_XML = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>'
)
_PAGE_XML = re.compile(r'<page width="[\d.]+" height="[\d.]+">(.*?)</page>', re.S)


def tem_pdftotext():
    return shutil.which('pdftotext') is not None


def _palavras_pdftotext(caminho):
    xml = subprocess.run(
        ['pdftotext', '-bbox', '-enc', 'UTF-8', str(caminho), '-'],
        capture_output=True, text=True, encoding='utf-8', check=True,
    ).stdout
    paginas = []
    for corpo in _PAGE_XML.findall(xml):
        ws = []
        for xmin, ymin, xmax, _ymax, txt in _WORD_XML.findall(corpo):
            txt = txt.strip()
            if txt:
                x, x2 = float(xmin), float(xmax)
                ws.append({'x': x, 'x2': x2, 'y': float(ymin), 'cx': (x + x2) / 2, 't': txt})
        paginas.append(ws)
    return paginas


def palavras_por_pagina(caminho):
    if not tem_pdftotext():
        raise PopplerAusente(
            'A leitura da folha ponto precisa do utilitário pdftotext, do pacote '
            '"poppler-utils", que não está instalado neste servidor. '
            'Instale com: sudo apt-get install -y poppler-utils'
        )
    return _palavras_pdftotext(caminho)


# ---------------------------------------------------------------------------
# Vocabulário do relatório
# ---------------------------------------------------------------------------
HORA = re.compile(r'^\d{1,4}:\d{2}$')
DIA = re.compile(r'^(\d{2})/(\d{2})$')
TABELA = re.compile(r'^\d{3}$')

# Marcações escritas no lugar da batida quando o dia não é de trabalho.
FOLGA = {'Domingo', 'Sábado', 'Sabado', 'Feriado', 'Folga', 'DSR', 'Compensado', 'Compens'}

# O relatório TRUNCA o motivo em 7 caracteres ('Atestad', 'Dispens', 'Esquece').
MOTIVO_DIA = {
    'Falta': 'falta',
    'Atestad': 'atestado', 'Atestado': 'atestado',
    'Af_INSS': 'af_inss',
    'Ferias': 'ferias', 'Férias': 'ferias',
    'Dispens': 'dispensa',
    'Curso': 'curso',
    'Treinam': 'treinamento',
    'Integra': 'integracao',
    'Ob_Fami': 'obito_familiar',
    'L_Mater': 'lic_maternidade',
    'Homeofi': 'home_office',
    'Feira': 'feira',
    'Esquece': 'esqueceu_marcar',
    'CC': 'cc',
    'R_Dupli': 'reg_duplicado',
    'Suspens': 'suspensao',
}

# ⚠️ Marcações de DUAS palavras, que precisam ser casadas ANTES das de uma só.
#
# ``A Falta`` é o código de ABONO de falta (aparece no Resumo de Abonos como
# ``A Falta: 04:48``) e não pode ser lido como o ``Falta`` cru: são coisas
# diferentes. O caso que revelou isso é o médico do trabalho, contratado para 3h
# por dia, cujos dias sem comparecimento saem como ``A Falta`` + ``03:00`` em
# ``H. Abonada`` -- 47 dias em 90, que entrariam no índice como se ele tivesse
# faltado, quando é a estrutura do contrato dele.
MOTIVO_COMPOSTO = (
    ('A Falta', 'abono_falta'),
)

# Um dia pode ter mais de uma marcação (entrou, saiu com atestado). Vence o
# motivo mais forte: afastamento e férias descrevem o dia melhor que 'falta'.
PRIORIDADE = (
    'af_inss', 'ferias', 'atestado', 'lic_maternidade', 'obito_familiar', 'suspensao',
    'curso', 'treinamento', 'integracao', 'feira', 'cc', 'home_office', 'dispensa',
    'esqueceu_marcar', 'reg_duplicado', 'abono_falta', 'falta',
)

# Ausência NÃO programada: é o que o absenteísmo mede.
#
# ``abono_falta`` ('A Falta') ENTRA: a pessoa não compareceu, a empresa só não
# descontou. São 199 pessoas com mediana de 2 dias cada -- falta abonada comum,
# espalhada, e não um artefato. As exceções são poucas e ficam sinalizadas em
# ``alertas_codificacao`` (ver ``_alertas_codificacao``), para o RH corrigir o
# código no iPonto em vez de o índice esconder o problema num filtro mágico.
NAO_PROGRAMADA = {
    'falta', 'abono_falta', 'atestado', 'af_inss',
    'obito_familiar', 'lic_maternidade', 'suspensao',
}

# Rótulos que o relatório quebra em duas ou três linhas.
_REMENDO_ROTULO = (
    ('Abona da', 'Abonada'), ('Adi- cional', 'Adicional'), ('Feriad o', 'Feriado'),
    ('Atras o', 'Atraso'), ('Prorro g', 'Prorrog'), ('Exced .', 'Exced'),
)

# Fronteira em x entre a ficha (esquerda) e o quadro de horários (direita).
X_FICHA = 440


def para_min(texto):
    """'184:02' → 11042. As horas do relatório passam de 24, então não é hora do dia."""
    h, m = texto.split(':')
    return int(h) * 60 + int(m)


def _linhas(ws, tol=3.0):
    linhas = []
    for w in sorted(ws, key=lambda w: (w['y'], w['x'])):
        if linhas and abs(w['y'] - linhas[-1][0]['y']) <= tol:
            linhas[-1].append(w)
        else:
            linhas.append([w])
    for ln in linhas:
        ln.sort(key=lambda w: w['x'])
    return linhas


def _texto(ln):
    return ' '.join(w['t'] for w in ln)


def _valor_campo(ln, rotulo):
    """Valor de 'rotulo:' — começa depois da borda direita do rótulo.

    Não basta pegar as palavras seguintes na ordem de x: cargo comprido
    transborda e cai por cima da caixa do rótulo vizinho (ver docstring do
    módulo).
    """
    alvo = next((w for w in ln if w['t'] == rotulo + ':'), None)
    if alvo is None:
        return ''
    out = []
    for w in ln:
        if w['x'] < alvo['x2'] or w['x'] >= X_FICHA:
            continue
        if w['t'].endswith(':'):
            break
        out.append(w['t'])
    return ' '.join(out).strip()


def _colunas_hora(linhas, x_min, y_ini, y_fim):
    """Colunas de hora, descobertas pelos rótulos do cabeçalho.

    A faixa vertical é obrigatória: sem ela entram o quadro de horários e o
    aviso "Neste mês ocorreram trocas de tabelas", que ficam na mesma região
    horizontal e viram rótulo fantasma.
    """
    frag = [
        w for ln in linhas for w in ln
        if y_ini <= w['y'] <= y_fim and w['x'] >= x_min and not HORA.match(w['t'])
    ]
    grupos = []
    for w in sorted(frag, key=lambda w: w['cx']):
        if grupos and abs(w['cx'] - grupos[-1][-1]['cx']) <= 12:
            grupos[-1].append(w)
        else:
            grupos.append([w])
    cols = []
    for g in grupos:
        rotulo = ' '.join(w['t'] for w in sorted(g, key=lambda w: (w['y'], w['x'])))
        for de, para in _REMENDO_ROTULO:
            rotulo = rotulo.replace(de, para)
        cols.append({
            'rotulo': re.sub(r'\s+', ' ', rotulo).strip(),
            'cx': sum(w['cx'] for w in g) / len(g),
        })
    return cols


def _rotular(valores, cols, tol=25):
    out = {}
    for w in valores:
        if not cols:
            continue
        c = min(cols, key=lambda c: abs(c['cx'] - w['cx']))
        if abs(c['cx'] - w['cx']) <= tol:
            out.setdefault(c['rotulo'], []).append(w['t'])
    return out


def _data_br(txt):
    d, m, a = txt.split('/')
    return date(int(a), int(m), int(d))


def classificar_dia(marcas, batidas):
    """Categoria do dia: trabalhado, folga, ou o motivo da ausência."""
    marcas = [m for m in marcas if not TABELA.match(m)]
    achadas = set()
    # Compostas primeiro: 'A Falta' precisa vencer o 'Falta' que está dentro dela.
    juntas = ' '.join(marcas)
    for texto, motivo in MOTIVO_COMPOSTO:
        if texto in juntas:
            achadas.add(motivo)
            juntas = juntas.replace(texto, '')
    achadas |= {MOTIVO_DIA[m] for m in juntas.split() if m in MOTIVO_DIA}
    if achadas:
        for p in PRIORIDADE:
            if p in achadas:
                return p
        return sorted(achadas)[0]
    if batidas:
        return 'trabalhado'
    if any(m in FOLGA for m in marcas):
        return 'folga'
    # Sem batida, sem marcação e sem folga: é quem não tem controle de horário
    # (tabela 000 — caseiro, por exemplo). Fica fora do índice.
    return 'sem_marca'


def ler_pagina(ws):
    """Um cartão. Devolve None se a página não for um cartão de ponto."""
    if not ws:
        return None
    linhas = _linhas(ws)
    todo = '\n'.join(_texto(ln) for ln in linhas)

    m = re.search(r'referência:\s*de\s*(\d{2}/\d{2}/\d{4})\s*à\s*(\d{2}/\d{2}/\d{4})', todo)
    if not m:
        return None
    card = {'periodo_inicio': _data_br(m.group(1)), 'periodo_fim': _data_br(m.group(2))}

    for ln in linhas:
        esq = [w for w in ln if w['x'] < X_FICHA]
        s = _texto(esq)
        if 'Nome:' in s and not card.get('nome'):
            card['nome'] = _valor_campo(esq, 'Nome')
            card['admissao'] = _valor_campo(esq, 'Admissão')
        if 'Crachá:' in s and not card.get('cracha'):
            card['cracha'] = _valor_campo(esq, 'Crachá')
            card['cpf'] = _valor_campo(esq, 'CPF')
        if 'Setor:' in s and not card.get('setor'):
            card['cargo'] = _valor_campo(esq, 'Cargo')
            card['setor'] = _valor_campo(esq, 'Setor')

    ent_sai = [w for ln in linhas for w in ln
               if w['t'] in ('Ent', 'Sai') and w['x'] < X_FICHA]
    x_min = (max(w['x2'] for w in ent_sai) + 5) if ent_sai else 350
    y_grade = min((w['y'] for w in ent_sai), default=150)
    y_dia1 = min(
        (ln[0]['y'] for ln in linhas if DIA.match(ln[0]['t']) and len(ln) > 1),
        default=y_grade + 20,
    )
    cols = _colunas_hora(linhas, x_min, y_grade - 22, y_dia1 - 2)

    cats = Counter()
    minutos_motivo = Counter()
    dias = 0
    totais = {}
    tabelas = set()
    for ln in linhas:
        prim = ln[0]['t']
        if DIA.match(prim) and len(ln) > 1:
            dias += 1
            tabelas.add(next((w['t'] for w in ln[1:4] if TABELA.match(w['t'])), ''))
            marcas = [w['t'] for w in ln[1:] if not HORA.match(w['t']) and w['x'] < x_min]
            batidas = [w['t'] for w in ln if HORA.match(w['t']) and w['x'] < x_min]
            horas = _rotular([w for w in ln if HORA.match(w['t']) and w['x'] >= x_min], cols)
            cat = classificar_dia(marcas, batidas)
            cats[cat] += 1
            abonadas = sum(para_min(v) for v in horas.get('H. Abonada', []))
            if abonadas and cat not in ('trabalhado', 'folga', 'sem_marca'):
                minutos_motivo[cat] += abonadas
            perdidas = sum(para_min(v) for v in horas.get('H. Falt.', []))
            if perdidas:
                minutos_motivo['falta'] += perdidas
        elif dias and all(HORA.match(w['t']) for w in ln) and ln[0]['x'] >= x_min:
            totais = _rotular(ln, cols)

    card['dias_grade'] = dias
    card['dias_por_categoria'] = dict(cats)
    card['minutos_por_motivo'] = dict(minutos_motivo)
    for chave, rotulo in (
        ('minutos_trabalhados', 'H. Trab.'),
        ('minutos_falta', 'H. Falt.'),
        ('minutos_abonados', 'H. Abonada'),
    ):
        card[chave] = sum(para_min(v) for v in totais.get(rotulo, []))

    m = re.search(
        r'D\.\s*Trab\.?:\s*(\d+)\s+D\.\s*Falt\.?:\s*(\d+)\s+DSR:\s*(\d+)\s+'
        r'DDSR:\s*(\d+)\s+Folgas:\s*(\d+)',
        todo,
    )
    if not m:
        return None
    (card['dias_trabalhados'], card['dias_falta'], card['dsr'],
     card['ddsr'], card['folgas']) = (int(g) for g in m.groups())

    # Quem não bate ponto: tabela 000 na grade inteira e nenhum dia trabalhado.
    # O critério é a TABELA, não a falta de marcação: quem não tem horário mas
    # tirou férias no mês tem marcação e escaparia do filtro.
    card['sem_controle'] = tabelas <= {'000', ''} and card['dias_trabalhados'] == 0
    return card


def ler_pdf(caminho):
    """Todos os cartões de um PDF de setor."""
    out = []
    for ws in palavras_por_pagina(caminho):
        card = ler_pagina(ws)
        if card:
            out.append(card)
    return out


def ler_zip(caminho_zip, destino_tmp):
    """Cartões de todos os PDFs de um ZIP de competência.

    O nome do arquivo NÃO é fonte de setor: a mesma fábrica vem como
    'FÁBRICA DE ARGAMASSA.pdf' em junho e 'ARGAMASSA.pdf' em julho. O setor sai
    do campo ``Setor:`` de dentro do cartão.
    """
    cartoes = []
    with zipfile.ZipFile(caminho_zip) as z:
        nomes = [n for n in z.namelist()
                 if n.lower().endswith('.pdf') and not n.startswith('__MACOSX')]
        for i, nome in enumerate(sorted(nomes)):
            alvo = os.path.join(destino_tmp, f'{i:03d}.pdf')
            with z.open(nome) as origem, open(alvo, 'wb') as fh:
                shutil.copyfileobj(origem, fh)
            try:
                cartoes.extend(ler_pdf(alvo))
            finally:
                os.unlink(alvo)
    return cartoes


def competencia_de(cartoes):
    """Competência (AAAA-MM) pelo mês do FIM do período de referência.

    O período vai de 26 a 25, então quem manda no rótulo é o fim: 26/06 a
    25/07 é a competência de julho.
    """
    if not cartoes:
        return None, None, None
    fim = Counter(c['periodo_fim'] for c in cartoes).most_common(1)[0][0]
    ini = Counter(c['periodo_inicio'] for c in cartoes).most_common(1)[0][0]
    return f'{fim.year:04d}-{fim.month:02d}', ini, fim


# ---------------------------------------------------------------------------
# Apuração do absenteísmo
# ---------------------------------------------------------------------------
# Os quatro índices usam O MESMO denominador -- dias escalados, isto é, os dias
# em que se esperava a pessoa no trabalho (total de dias-cartão menos folga e
# menos férias). Assim eles formam uma progressão comparável, cada um
# acrescentando um motivo ao anterior, em vez de quatro frações com bases
# diferentes.
#
# Por que o principal é FALTA + ATESTADO, sem afastamento INSS:
#
#   descontado      0,38%  só o dia inteiro que o DP descontou. Mede política de
#                          desconto, não ausência: 75% das faltas são abonadas.
#   falta           2,64%  todo não comparecimento, abonado ou não.
#   falta_atestado  4,30%  << PRINCIPAL >> soma o atestado médico. É o que a
#                          maioria dos RHs chama de absenteísmo e o único
#                          comparável com benchmark de indústria (2 a 4%).
#   com_afastamento 10,45% soma o afastamento INSS. Serve para custo e escala,
#                          mas é dominado por poucos afastamentos longos e
#                          distorce setor pequeno (uma pessoa afastada num setor
#                          de 3 leva o índice a 50%).

INDICES = (
    ('descontado', 'Falta descontada (dia inteiro)', ('__descontado__',)),
    ('falta', 'Falta (abonada ou não)', ('falta', 'abono_falta')),
    ('falta_atestado', 'Falta + atestado', ('falta', 'abono_falta', 'atestado')),
    ('com_afastamento', 'Falta + atestado + afastamento', tuple(sorted(NAO_PROGRAMADA))),
)
INDICE_PRINCIPAL = 'falta_atestado'

MOTIVO_ROTULO = {
    'falta': 'Falta', 'abono_falta': 'Falta abonada (código "A Falta")',
    'atestado': 'Atestado médico', 'af_inss': 'Afastamento INSS',
    'ferias': 'Férias', 'dispensa': 'Dispensa abonada', 'curso': 'Curso',
    'treinamento': 'Treinamento', 'integracao': 'Integração', 'cc': 'Centro de custo',
    'obito_familiar': 'Óbito familiar', 'lic_maternidade': 'Licença-maternidade',
    'suspensao': 'Suspensão', 'feira': 'Feira', 'home_office': 'Home office',
    'esqueceu_marcar': 'Esqueceu de marcar', 'reg_duplicado': 'Registro duplicado',
    'trabalhado': 'Trabalhado', 'folga': 'Folga/DSR/feriado',
    'sem_marca': 'Sem marcação',
}


def _pct(num, den):
    return round(num / den * 100, 2) if den else 0.0


def _br(valor, casas=2):
    """Número em pt-BR — vírgula decimal e ponto no milhar.

    As ressalvas são texto pronto que a tela e o PDF só imprimem, então a
    formatação tem de sair daqui já correta: `f'{0.38:.2f}%'` imprimiria
    "0.38%" no meio de um relatório em português.
    """
    texto = f'{valor:,.{casas}f}'
    return texto.replace(',', '\x00').replace('.', ',').replace('\x00', '.')


def _bloco(cartoes):
    """Contagens e os quatro índices de um conjunto de cartões."""
    cats = Counter()
    minutos = Counter()
    d_falt = d_trab = m_trab = m_falt = m_abon = 0
    for c in cartoes:
        cats.update(c['dias_por_categoria'])
        minutos.update(c['minutos_por_motivo'])
        d_falt += c['dias_falta']
        d_trab += c['dias_trabalhados']
        m_trab += c['minutos_trabalhados']
        m_falt += c['minutos_falta']
        m_abon += c['minutos_abonados']

    escalados = sum(cats.values()) - cats.get('folga', 0) - cats.get('ferias', 0)
    indices = {}
    for chave, rotulo, motivos in INDICES:
        if motivos == ('__descontado__',):
            num = d_falt
        else:
            num = sum(cats.get(m, 0) for m in motivos)
        indices[chave] = {
            'rotulo': rotulo, 'dias': num, 'indice': _pct(num, escalados),
        }

    return {
        'cartoes': len(cartoes),
        'pessoas': len({c['cracha'] or c['nome'] for c in cartoes}),
        'dias_escalados': escalados,
        'dias_trabalhados': d_trab,
        'dias_falta_descontada': d_falt,
        'dias_por_categoria': dict(cats),
        'minutos_por_motivo': dict(minutos),
        'horas_trabalhadas': round(m_trab / 60, 1),
        'horas_falta': round(m_falt / 60, 1),
        'horas_abonadas': round(m_abon / 60, 1),
        'indices': indices,
        'indice': indices[INDICE_PRINCIPAL]['indice'],
    }


def apurar_absenteismo(cartoes_por_competencia):
    """
    Payload do absenteísmo.

    ``cartoes_por_competencia``: lista de ``(competencia, rotulo, periodo_inicio,
    periodo_fim, [cartao_dict, ...])``. Recebe dicionários, e não objetos do
    ORM, para poder ser conferida com os PDFs direto, sem banco.

    Cartões ``sem_controle`` (tabela 000, quem não bate ponto) saem de tudo.
    """
    comps = []
    todos = []
    for comp, rotulo, ini, fim, cartoes in cartoes_por_competencia:
        validos = [c for c in cartoes if not c.get('sem_controle')]
        todos.extend(validos)
        comps.append({
            'competencia': comp,
            'rotulo': rotulo,
            'periodo': f'{ini.strftime("%d/%m")} a {fim.strftime("%d/%m/%Y")}' if ini and fim else '',
            'cartoes_sem_controle': len(cartoes) - len(validos),
            **_bloco(validos),
        })

    if not todos:
        return {
            'disponivel': False,
            'motivo': (
                'Nenhuma folha ponto importada. O absenteísmo depende do espelho '
                'de ponto em PDF que o escritório contábil envia por competência: '
                'o ponto eletrônico do ERP parou em 26/04/2023.'
            ),
            'competencias': [],
        }

    consolidado = _bloco(todos)

    # Por motivo, em dias, sobre o denominador do consolidado.
    motivos_por_indice = {chave: motivos for chave, _rotulo, motivos in INDICES}
    conta_no_principal = set(motivos_por_indice[INDICE_PRINCIPAL])
    por_motivo = []
    for motivo, dias in Counter(consolidado['dias_por_categoria']).most_common():
        if motivo in ('trabalhado', 'folga', 'sem_marca'):
            continue
        por_motivo.append({
            'motivo': motivo,
            'rotulo': MOTIVO_ROTULO.get(motivo, motivo),
            'dias': dias,
            'indice': _pct(dias, consolidado['dias_escalados']),
            'horas': round(consolidado['minutos_por_motivo'].get(motivo, 0) / 60, 1),
            'conta_no_principal': motivo in conta_no_principal,
            'nao_programada': motivo in NAO_PROGRAMADA,
        })

    # Por setor, com o drill de pessoas.
    setores = []
    nomes_setor = {c['setor'] for c in todos}
    for setor in nomes_setor:
        do_setor = [c for c in todos if c['setor'] == setor]
        bloco = _bloco(do_setor)
        pessoas = []
        chaves = {c['cracha'] or c['nome'] for c in do_setor}
        for chave in chaves:
            da_pessoa = [c for c in do_setor if (c['cracha'] or c['nome']) == chave]
            b = _bloco(da_pessoa)
            cats = b['dias_por_categoria']
            # Entra quem tem QUALQUER ausência não programada — inclusive só
            # 'A Falta', senão o setor mostra índice com o drill vazio.
            if any(cats.get(m, 0) for m in NAO_PROGRAMADA) or b['dias_falta_descontada']:
                pessoas.append({
                    'nome': da_pessoa[0]['nome'],
                    'cargo': da_pessoa[0]['cargo'],
                    'dias_escalados': b['dias_escalados'],
                    'dias_falta': cats.get('falta', 0),
                    'dias_falta_abonada': cats.get('abono_falta', 0),
                    'dias_falta_descontada': b['dias_falta_descontada'],
                    'dias_atestado': cats.get('atestado', 0),
                    'dias_afastamento': cats.get('af_inss', 0),
                    'indice': b['indice'],
                })
        setores.append({
            'setor': setor,
            'pessoas_com_ausencia': sorted(pessoas, key=lambda p: -p['indice']),
            **bloco,
        })
    setores.sort(key=lambda s: -s['indice'])

    alertas = _alertas_codificacao(todos, consolidado)
    ressalvas = _ressalvas(consolidado, comps, alertas)

    return {
        'disponivel': True,
        'alertas_codificacao': alertas,
        'indice': consolidado['indice'],
        'indice_principal': INDICE_PRINCIPAL,
        'indice_principal_rotulo': consolidado['indices'][INDICE_PRINCIPAL]['rotulo'],
        'periodo': _periodo_texto(comps),
        'consolidado': consolidado,
        'competencias': comps,
        'por_motivo': por_motivo,
        'setores': setores,
        'ressalvas': ressalvas,
    }


def _periodo_texto(comps):
    if not comps:
        return ''
    prim, ult = comps[0], comps[-1]
    ini = prim['periodo'].split(' a ')[0] if prim['periodo'] else ''
    fim = ult['periodo'].split(' a ')[-1] if ult['periodo'] else ''
    return f'{ini} a {fim}' if ini and fim else ''


def _alertas_codificacao(cartoes, consolidado):
    """
    Pessoas cujo ``A Falta`` é estrutura de contrato, não ausência.

    O código ``A Falta`` foi feito para falta abonada, mas o DP também o usa
    para quem não é esperado todos os dias -- o médico do trabalho, contratado
    para 3h/dia, sai com 47 dias de ``A Falta`` em 90. Para essas pessoas o
    índice individual não quer dizer nada.

    Em vez de filtrar por conta própria (o que esconderia o problema), a lista
    vai para a tela e para o PDF: o certo é o RH trocar o código no iPonto por
    folga ou por um código de jornada parcial. O ``impacto_pp`` diz quanto o
    índice geral cairia sem essas pessoas, para a decisão ser informada.
    """
    LIMITE = 0.5          # metade dos dias escalados
    MINIMO_DIAS = 10      # abaixo disso é falta abonada comum, não padrão

    por_pessoa = {}
    for c in cartoes:
        chave = c['cracha'] or c['nome']
        d = por_pessoa.setdefault(chave, {
            'nome': c['nome'], 'cargo': c['cargo'], 'setor': c['setor'],
            'abono_falta': 0, 'trabalhado': 0, 'escalados': 0,
        })
        cats = c['dias_por_categoria']
        d['abono_falta'] += cats.get('abono_falta', 0)
        d['trabalhado'] += cats.get('trabalhado', 0)
        d['escalados'] += sum(cats.values()) - cats.get('folga', 0) - cats.get('ferias', 0)

    fora = []
    for d in por_pessoa.values():
        if d['abono_falta'] >= MINIMO_DIAS and d['escalados'] and \
                d['abono_falta'] / d['escalados'] >= LIMITE:
            d['proporcao'] = round(d['abono_falta'] / d['escalados'] * 100, 1)
            fora.append(d)
    fora.sort(key=lambda d: -d['proporcao'])

    dias_fora = sum(d['abono_falta'] for d in fora)
    principal = consolidado['indices'][INDICE_PRINCIPAL]
    den = consolidado['dias_escalados']
    return {
        'pessoas': fora,
        'dias': dias_fora,
        'indice_sem_elas': _pct(principal['dias'] - dias_fora, den - dias_fora),
        'impacto_pp': round(
            principal['indice'] - _pct(principal['dias'] - dias_fora, den - dias_fora), 2
        ),
    }


def _ressalvas(consolidado, comps, alertas=None):
    """Avisos que a tela e o PDF mostram junto do número, para ele não ser lido
    fora de contexto."""
    out = []
    cats = consolidado['dias_por_categoria']
    desc = consolidado['indices']['descontado']['indice']
    principal = consolidado['indices'][INDICE_PRINCIPAL]['indice']
    if principal and desc:
        out.append(
            f'A empresa abona a maior parte das faltas: o índice cai para '
            f'{_br(desc)}% se só o dia descontado em folha for contado. '
            f'O indicador usa toda ausência não programada, abonada ou não.'
        )
    if cats.get('af_inss'):
        afast = consolidado['indices']['com_afastamento']['indice']
        out.append(
            f'Afastamento INSS ({_br(cats["af_inss"], 0)} dias) fica FORA do indicador '
            f'principal; incluí-lo levaria o índice a {_br(afast)}%. Afastamento '
            f'longo distorce setor pequeno e não é gerenciável como falta.'
        )
    if cats.get('abono_falta'):
        out.append(
            f'Dos dias de falta, {_br(cats["abono_falta"], 0)} vêm com o código '
            f'"A Falta" (abonada) e {_br(cats.get("falta", 0), 0)} sem abono. Os dois '
            f'entram: a pessoa não compareceu, a empresa apenas não descontou.'
        )
    if alertas and alertas['pessoas']:
        nomes = ', '.join(p['nome'].title() for p in alertas['pessoas'])
        out.append(
            f'{len(alertas["pessoas"])} pessoa(s) usam "A Falta" em mais da metade '
            f'dos dias, o que é jornada parcial e não ausência ({nomes}). '
            f'Sem elas o índice seria {_br(alertas["indice_sem_elas"])}% '
            f'({_br(alertas["impacto_pp"])} p.p. menor). O certo é corrigir o código '
            f'no iPonto.'
        )
    sem_ctrl = sum(c.get('cartoes_sem_controle', 0) for c in comps)
    if sem_ctrl:
        out.append(
            f'{sem_ctrl} cartão(ões) de quem não bate ponto (tabela 000) ficaram '
            f'fora do cálculo.'
        )
    return out


def apurar_do_banco():
    """Absenteísmo a partir das competências já importadas e concluídas."""
    from .models import CartaoPonto, FolhaPonto

    folhas = list(
        FolhaPonto.objects.filter(status=FolhaPonto.CONCLUIDA).order_by('competencia')
    )
    if not folhas:
        return apurar_absenteismo([])

    cartoes = CartaoPonto.objects.filter(folha__in=folhas)
    por_folha = {f.id: [] for f in folhas}
    for c in cartoes:
        por_folha[c.folha_id].append({
            'cracha': c.cracha,
            'nome': c.nome,
            'setor': c.setor,
            'cargo': c.cargo,
            'dias_trabalhados': c.dias_trabalhados,
            'dias_falta': c.dias_falta,
            'dias_por_categoria': c.dias_por_categoria or {},
            'minutos_por_motivo': c.minutos_por_motivo or {},
            'minutos_trabalhados': c.minutos_trabalhados,
            'minutos_falta': c.minutos_falta,
            'minutos_abonados': c.minutos_abonados,
            'sem_controle': c.sem_controle,
        })

    return apurar_absenteismo([
        (f.competencia, f.rotulo, f.periodo_inicio, f.periodo_fim, por_folha[f.id])
        for f in folhas
    ])


def importar_arquivo(folha):
    """
    Lê o arquivo de uma ``FolhaPonto`` e grava os cartões.

    Roda fora do ciclo do request (ver ``FolhaPontoViewSet.create``): 380
    páginas levam uns 3 segundos com o poppler, mas o ZIP de uma competência
    inteira já chegou com 34 PDFs e não vale arriscar o timeout do nginx.

    A competência só é conhecida DEPOIS da leitura (sai do período de referência
    impresso no cartão), então a linha nasce com uma chave provisória e é
    renomeada aqui. Reimportar a mesma competência substitui a anterior.
    """
    from django.db import connection
    from django.utils import timezone

    from .models import CartaoPonto, FolhaPonto

    try:
        caminho = folha.arquivo.path
        if zipfile.is_zipfile(caminho):
            with tempfile.TemporaryDirectory(prefix='folha-ponto-') as tmp:
                cartoes = ler_zip(caminho, tmp)
        else:
            cartoes = ler_pdf(caminho)

        if not cartoes:
            raise ValueError(
                'Nenhum cartão de ponto reconhecido no arquivo. Esperado o espelho '
                'de ponto do iPonto em PDF (ou um ZIP com esses PDFs).'
            )

        competencia, ini, fim = competencia_de(cartoes)

        # Reimportação substitui: erro de arquivo se corrige reenviando.
        FolhaPonto.objects.filter(competencia=competencia).exclude(pk=folha.pk).delete()

        folha.competencia = competencia
        folha.periodo_inicio = ini
        folha.periodo_fim = fim
        folha.cartoes_lidos = len(cartoes)
        folha.cartoes_sem_controle = sum(1 for c in cartoes if c['sem_controle'])
        folha.status = FolhaPonto.CONCLUIDA
        folha.processado_em = timezone.now()
        folha.mensagem = (
            f'{len(cartoes)} cartões lidos '
            f'({folha.cartoes_sem_controle} sem controle de horário).'
        )
        folha.save()

        CartaoPonto.objects.filter(folha=folha).delete()
        CartaoPonto.objects.bulk_create([
            CartaoPonto(
                folha=folha,
                cracha=c.get('cracha', ''),
                nome=c.get('nome', ''),
                setor=c.get('setor', ''),
                cargo=c.get('cargo', ''),
                admissao=c.get('admissao', ''),
                dias_trabalhados=c['dias_trabalhados'],
                dias_falta=c['dias_falta'],
                dsr=c['dsr'],
                ddsr=c['ddsr'],
                folgas=c['folgas'],
                dias_grade=c['dias_grade'],
                dias_por_categoria=c['dias_por_categoria'],
                minutos_por_motivo=c['minutos_por_motivo'],
                minutos_trabalhados=c['minutos_trabalhados'],
                minutos_falta=c['minutos_falta'],
                minutos_abonados=c['minutos_abonados'],
                sem_controle=c['sem_controle'],
            )
            for c in cartoes
        ], batch_size=200)
    except Exception as erro:  # noqa: BLE001 - o recado tem que chegar na tela
        folha.status = FolhaPonto.ERRO
        folha.mensagem = str(erro)[:2000]
        folha.save(update_fields=['status', 'mensagem'])
    finally:
        # A thread tem a própria conexão; sem fechar, ela fica pendurada no pool.
        connection.close()
