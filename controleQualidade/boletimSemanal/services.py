"""
Cálculo do boletim: das análises lançadas até o número de cada semana.

Por que a extração do valor não chama `filtrar-e-calcular`: aquele endpoint resolve
UM período por requisição, e aqui o gráfico do ano precisa das 52 semanas de cada
indicador. Reaproveitá-lo daria ~600 consultas por abertura de tela. Então o
caminho é o oposto: uma passada por indicador sobre o ano inteiro, distribuindo os
valores nas semanas em memória.

A regra de leitura do valor é a MESMA do endpoint (mesmo formato de
`ensaios_utilizados`, mesma queda para `AnaliseCalculo`, mesmo casamento por trecho
de descrição). Se ela mudar lá, precisa mudar aqui — está anotado nos dois lados.
"""
import json
import logging
from datetime import date, timedelta

from django.db.models import Q

from controleQualidade.analise.models import Analise, AnaliseCalculo, AnaliseEnsaio
from controleQualidade.amostra.derivadas import sem_derivadas

logger = logging.getLogger(__name__)


# ── Semana ISO ───────────────────────────────────────────────────────────────
# A planilha numera "Semana 2", "Semana 3"... e é a semana ISO: segunda a domingo.
# `date.fromisocalendar` faz a conta certa na virada do ano, onde o dia 1º pode
# pertencer à última semana do ano anterior.

def intervalo_da_semana(ano: int, semana: int) -> tuple[date, date]:
    inicio = date.fromisocalendar(ano, semana, 1)
    return inicio, inicio + timedelta(days=6)


def total_de_semanas(ano: int) -> int:
    """52 ou 53, conforme o ano. 28/12 cai sempre na última semana ISO."""
    return date(ano, 12, 28).isocalendar()[1]


def semana_de(dia: date) -> tuple[int, int]:
    ano, semana, _ = dia.isocalendar()
    return ano, semana


def anos_do_intervalo(inicio: date, fim: date) -> list[int]:
    """
    Os anos que precisam ser lidos para cobrir um intervalo livre de datas.

    Entram o ano civil e o ano ISO das duas pontas: o cálculo é feito ano a ano
    (`valores_por_dia` descarta o dia cujo ano ISO não é o pedido), e 31/12 pode
    pertencer à semana 1 do ano seguinte. Sem isso, um período que cruza a virada
    perderia os últimos dias em silêncio.
    """
    anos = {inicio.year, fim.year, inicio.isocalendar()[0], fim.isocalendar()[0]}
    return sorted(anos)


# ── Valor de uma análise ─────────────────────────────────────────────────────

def _valor_no_json(ensaios_utilizados, ensaio_id, ensaio_nome):
    """
    Procura o valor do ensaio dentro do JSON gravado na análise.

    Percorre de trás para frente porque a lista é histórico: a última entrada é a
    medição que vale (mesma escolha do `filtrar-e-calcular`).
    """
    try:
        if isinstance(ensaios_utilizados, list):
            lista = ensaios_utilizados
        elif isinstance(ensaios_utilizados, str):
            lista = json.loads(ensaios_utilizados)
        else:
            return None
    except (json.JSONDecodeError, TypeError):
        return None

    for ensaio in reversed(lista or []):
        if not isinstance(ensaio, dict):
            continue
        casou = False
        if ensaio_id and ensaio.get('id') == ensaio_id:
            casou = True
        if ensaio_nome and ensaio_nome.lower() in (ensaio.get('descricao') or '').lower():
            casou = True
        if not casou:
            continue
        try:
            return float(ensaio.get('valor'))
        except (TypeError, ValueError):
            return None
    return None


def _data_de_referencia(analise, campo: str):
    """
    A data que decide em que semana a análise entra.

    Cai para a próxima opção quando a preferida está vazia — amostra antiga sem
    data de coleta continuaria fora de todas as semanas, e desaparecer é pior do
    que entrar na semana da entrada.
    """
    amostra = analise.amostra
    candidatas = []
    if campo == 'finalizada_at':
        candidatas = [analise.finalizada_at]
    elif campo == 'data_entrada':
        candidatas = [getattr(amostra, 'data_entrada', None), getattr(amostra, 'data_coleta', None)]
    else:
        candidatas = [getattr(amostra, 'data_coleta', None), getattr(amostra, 'data_entrada', None)]
    candidatas.append(analise.finalizada_at)
    candidatas.append(analise.data.date() if analise.data else None)
    for d in candidatas:
        if d:
            return d
    return None


def _filtro_ou(campo: str, texto: str) -> Q:
    """
    Vários termos separados por vírgula viram um OU.

    Necessário porque a mesma coisa é digitada de formas diferentes na amostra: a cal
    hidratada aparece como 'CH-II', 'HIDRATADA' e 'HIDRATADA EXTRA', e um único
    trecho não pega as três sem pegar também a 'HIDRÁULICA', que é outro produto.

    Termo começando com `=` exige o valor EXATO. Existe porque a comparação por
    trecho tem uma armadilha silenciosa: 'Fábrica I' está contido em 'Fábrica II' e
    em 'Fábrica III', então o PN da Fábrica I estava somando as três fábricas (e a
    'Fábrica I - Filler' junto). Com '=Fábrica I' só entra a Fábrica I.

    Termo começando com `!` EXCLUI. É o que permite escrever "processo" na cal: o
    produto final é o que está no saco, e processo é todo o resto — silo, hidratador,
    moinho. Listar os pontos de processo um a um envelheceria a cada silo novo;
    `!Saco` continua valendo.

    Os positivos entram como OU entre si e as exclusões como E — `Silo,!Saco` lê-se
    "que contenha Silo e não contenha Saco".
    """
    positivos = Q()
    negativos = Q()
    tem_positivo = False
    for termo in (texto or '').split(','):
        termo = termo.strip()
        if not termo:
            continue
        if termo.startswith('!'):
            resto = termo[1:].strip()
            if resto.startswith('='):
                negativos &= ~Q(**{f'{campo}__iexact': resto[1:].strip()})
            elif resto:
                negativos &= ~Q(**{f'{campo}__icontains': resto})
        elif termo.startswith('='):
            positivos |= Q(**{f'{campo}__iexact': termo[1:].strip()})
            tem_positivo = True
        else:
            positivos |= Q(**{f'{campo}__icontains': termo})
            tem_positivo = True
    return (positivos & negativos) if tem_positivo else negativos


def _queryset_do_indicador(indicador, ano: int):
    """Análises que alimentam este indicador no ano — um filtro só, para o ano todo."""
    qs = Analise.objects.select_related('amostra', 'amostra__produto_amostra')

    # Sem filtro de `finalizada`/`aprovada` de propósito: o boletim considera a
    # análise assim que ela tem resultado, aberta ou encerrada. A semana fecha antes
    # de a OS ser encerrada, e esperar o encerramento atrasaria o acompanhamento.
    for campo, texto in [
        ('amostra__material', indicador.material),
        ('amostra__tipo_amostra', indicador.tipo_amostra),
        ('amostra__local_coleta', indicador.local_coleta),
        ('amostra__finalidade', indicador.finalidade),
        ('amostra__tipo_amostragem', indicador.tipo_amostragem),
    ]:
        if texto:
            qs = qs.filter(_filtro_ou(campo, texto))

    produtos_ids = list(indicador.produtos.values_list('id', flat=True))
    if produtos_ids:
        qs = qs.filter(amostra__produto_amostra_id__in=produtos_ids)

    # Recorte de datas frouxo (um mês de folga em cada ponta): a semana é decidida
    # depois, em Python, pela data escolhida no indicador — que pode ser de um
    # campo diferente do usado aqui.
    inicio = date(ano, 1, 1) - timedelta(days=31)
    fim = date(ano, 12, 31) + timedelta(days=31)
    qs = qs.filter(
        Q(amostra__data_coleta__range=(inicio, fim))
        | Q(amostra__data_entrada__range=(inicio, fim))
        | Q(finalizada_at__range=(inicio, fim))
        | Q(data__range=(inicio, fim))
    )
    # Duplicata e reanálise são a MESMA amostra medida de novo: contadas aqui,
    # entrariam duas vezes na média da semana. Ver amostra/derivadas.py.
    return sem_derivadas(qs).distinct()


def valores_por_analise(indicador, ano: int, ignorar_exclusoes: bool = False):
    """
    Valor do indicador em cada análise do ano, com a análise ao lado.

    Devolve `({analise_id: valor}, {analise_id: Analise})`. Separado do agrupamento
    por semana porque a tela também precisa da lista nominal — "quais análises
    entraram nesta média" é a primeira pergunta de quem vê um número estranho.

    Três consultas por indicador: as análises, os ensaios delas e — só para as que
    não casaram — os cálculos compostos. É o suficiente para o ano inteiro.
    """
    analises = list(_queryset_do_indicador(indicador, ano))
    if not analises:
        return {}, {}

    por_id = {a.id: a for a in analises}
    ensaio_id = indicador.ensaio_id
    ensaio_nome = (indicador.ensaio_nome or '').strip()
    if not ensaio_id and not ensaio_nome and not indicador.campo_especial:
        return {}, por_id

    # Análises que o laboratório tirou desta linha: saem antes de qualquer leitura,
    # para não entrarem na média nem na contagem de amostras. `ignorar_exclusoes` é
    # usado só para montar a lista da tela, que mostra as excluídas riscadas.
    excluidas = set() if ignorar_exclusoes else set(indicador.exclusoes.values_list('analise_id', flat=True))
    if excluidas:
        for analise_id in list(por_id):
            if analise_id in excluidas:
                del por_id[analise_id]
        if not por_id:
            return {}, {}

    valores: dict[int, float] = {}

    def buscar_no_ensaio():
        if not (ensaio_id or ensaio_nome):
            return
        # order_by('-id'): a análise pode ter mais de um AnaliseEnsaio; o mais novo manda.
        for ae in AnaliseEnsaio.objects.filter(analise_id__in=por_id).order_by('analise_id', '-id'):
            if ae.analise_id in valores:
                continue
            valor = _valor_no_json(ae.ensaios_utilizados, ensaio_id, ensaio_nome)
            if valor is not None:
                valores[ae.analise_id] = valor

    def buscar_no_calculo():
        # Cálculo composto (CO₂, óxidos não hidratados): não está na tabela de
        # ensaios, só em AnaliseCalculo, e é achado pela descrição.
        if not ensaio_nome:
            return
        faltando = [i for i in por_id if i not in valores]
        if not faltando:
            return
        for ac in AnaliseCalculo.objects.filter(
            analise_id__in=faltando, calculos__icontains=ensaio_nome,
        ).order_by('analise_id', '-id'):
            if ac.analise_id in valores or ac.resultados is None:
                continue
            valores[ac.analise_id] = ac.resultados

    # A ordem importa: há ensaio que existe só como casca do cálculo e fica gravado
    # com valor 0 (o "(Composto) - CO₂"). Procurar o ensaio primeiro nesse caso daria
    # uma semana inteira de zeros — foi o que aconteceu ao conferir contra a base real.
    if indicador.preferir_calculo:
        buscar_no_calculo()
        buscar_no_ensaio()
    else:
        buscar_no_ensaio()
        buscar_no_calculo()

    if indicador.campo_especial:
        faltando = [i for i in por_id if i not in valores]
        if faltando:
            valores.update(_valores_de_campo_especial(indicador, [por_id[i] for i in faltando]))

    return valores, por_id


def _semana_da_analise(analise, indicador, ano: int):
    """Semana ISO da análise, ou None quando ela cai fora do ano pedido."""
    referencia = _data_de_referencia(analise, indicador.campo_data)
    if not referencia:
        return None
    ano_iso, semana = semana_de(referencia)
    # Virada de ano: 31/12 pode pertencer à semana 1 do ano seguinte.
    return semana if ano_iso == ano else None


def valores_por_dia(indicador, ano: int) -> dict:
    """
    Os valores do ano agrupados por DIA.

    É a base das duas leituras: a semana soma os dias dela, e o relatório do
    calcário mostra o dia a dia — lá sai uma amostra composta por dia, por fábrica,
    e a média da semana existe só como resumo.
    """
    valores, por_id = valores_por_analise(indicador, ano)
    por_dia: dict = {}
    for analise_id, valor in valores.items():
        analise = por_id[analise_id]
        if _semana_da_analise(analise, indicador, ano) is None:
            continue  # fora do ano ISO pedido
        referencia = _data_de_referencia(analise, indicador.campo_data)
        por_dia.setdefault(referencia, []).append(valor)
    return por_dia


def valores_por_semana(indicador, ano: int) -> dict[int, list[float]]:
    """Os valores do ano agrupados pela semana ISO."""
    por_semana: dict[int, list[float]] = {}
    for dia, valores in valores_por_dia(indicador, ano).items():
        por_semana.setdefault(semana_de(dia)[1], []).extend(valores)
    return por_semana


def analises_do_periodo(indicador, inicio: date, fim: date, incluir_excluidas=True) -> list[dict]:
    """
    O mesmo que `analises_da_semana`, para um intervalo livre de datas.

    Lê ano a ano (é assim que a consulta é montada) e junta: a mesma análise pode
    voltar nos dois anos por causa da folga de 31 dias do recorte, daí a deduplicação
    por id.
    """
    por_analise: dict[int, dict] = {}
    for ano in anos_do_intervalo(inicio, fim):
        for linha in _analises(indicador, ano, lambda d: bool(d) and inicio <= d <= fim, incluir_excluidas):
            por_analise[linha['analise_id']] = linha
    return sorted(por_analise.values(), key=lambda l: (l['data'] or date.min, l['analise_id']))


def analises_da_semana(indicador, ano: int, semana: int, incluir_excluidas=True) -> list[dict]:
    """
    As análises que entraram no número de uma semana, com o que a tela precisa para
    listá-las e abrir cada uma: número da amostra, valor, data e ponto de coleta.

    As que foram tiradas da conta vêm juntas, marcadas com `excluida`: é preciso vê-las
    para poder devolvê-las — uma análise excluída que sumisse da lista viraria uma
    decisão irreversível pela tela.
    """
    return _analises(indicador, ano, None, incluir_excluidas, semana=semana)


def _analises(indicador, ano: int, aceita_data=None, incluir_excluidas=True, semana: int | None = None):
    """Corpo comum: `aceita_data` filtra por data; `semana`, pela semana ISO."""
    valores, por_id = valores_por_analise(indicador, ano)
    if incluir_excluidas:
        fora, por_id_fora = _valores_das_excluidas(indicador, ano)
        valores = {**valores, **fora}
        por_id = {**por_id, **por_id_fora}
    excluidas = set(indicador.exclusoes.values_list('analise_id', flat=True))
    linhas = []
    for analise_id, valor in valores.items():
        analise = por_id[analise_id]
        if aceita_data is not None:
            if not aceita_data(_data_de_referencia(analise, indicador.campo_data)):
                continue
        elif _semana_da_analise(analise, indicador, ano) != semana:
            continue
        amostra = analise.amostra
        produto = getattr(amostra, 'produto_amostra', None) if amostra else None
        linhas.append({
            'analise_id': analise_id,
            'valor': valor,
            'data': _data_de_referencia(analise, indicador.campo_data),
            'amostra_numero': getattr(amostra, 'numero', '') if amostra else '',
            'material': getattr(amostra, 'material', '') if amostra else '',
            'tipo_amostra': getattr(amostra, 'tipo_amostra', '') if amostra else '',
            'local_coleta': getattr(amostra, 'local_coleta', '') if amostra else '',
            'produto': getattr(produto, 'nome', '') if produto else '',
            'finalizada': analise.finalizada,
            'excluida': analise_id in excluidas,
        })
    # Por data: é a ordem em que o laboratório lê o histórico da semana.
    linhas.sort(key=lambda l: (l['data'] or date.min, l['analise_id']))
    return linhas


def _valores_das_excluidas(indicador, ano: int):
    """Repete a leitura só para as excluídas, para a tela poder mostrá-las e devolvê-las."""
    ids = set(indicador.exclusoes.values_list('analise_id', flat=True))
    if not ids:
        return {}, {}
    valores, por_id = valores_por_analise(indicador, ano, ignorar_exclusoes=True)
    return (
        {i: v for i, v in valores.items() if i in ids},
        {i: a for i, a in por_id.items() if i in ids},
    )


def _valores_de_campo_especial(indicador, analises) -> dict[int, float]:
    """
    Valores que moram em campo JSON da análise: peneiras e o "cal completo".

    O cal completo (plano das análises completas de cal) é um dicionário com as
    contas da caracterização — `oxidos_total_nao_hidratados` é uma delas. Escreve-se
    `cal_completo:oxidos_total_nao_hidratados` no campo especial.

    Peneira reaproveita o extrator do `filtrar-e-calcular` em vez de reescrever a
    leitura da malha — é código sensível, cheio de variações de rótulo de peneira.
    """
    campo = indicador.campo_especial or ''

    if campo.startswith('cal_completo'):
        # Chave depois dos dois-pontos; sem ela não há o que ler.
        chave = campo.split(':', 1)[1].strip() if ':' in campo else ''
        if not chave:
            logger.warning('Indicador %s usa cal_completo sem informar a chave.', indicador.pk)
            return {}
        encontrados = {}
        for analise in analises:
            bruto = (analise.cal_completo or {}).get(chave)
            try:
                valor = float(bruto)
            except (TypeError, ValueError):
                continue
            # Zero aqui é campo não preenchido, não resultado: o cal completo nasce
            # com todas as contas zeradas e só as análises daquele plano o preenchem.
            # Contar os zeros derrubaria a média da semana para perto de nada.
            if valor:
                encontrados[analise.id] = valor
        return encontrados

    try:
        from controleQualidade.analise.views import _extrair_valor_peneira
    except ImportError:
        logger.warning('Extrator de peneira indisponível; campo_especial ignorado.')
        return {}

    if campo not in ('peneiras_secas', 'peneiras_umidas'):
        return {}

    encontrados = {}
    for analise in analises:
        valor = _extrair_valor_peneira(
            analise, indicador.campo_especial, indicador.peneira_malha, indicador.peneira_metrica,
        )
        try:
            if valor is not None:
                encontrados[analise.id] = float(valor)
        except (TypeError, ValueError):
            continue
    return encontrados


# ── Produção (ERP) ───────────────────────────────────────────────────────────

def producao_por_dia(codigos: list[int], locais: list[int], etapa, ano: int) -> dict:
    """
    Toneladas produzidas por DIA.

    Dois recortes, porque o ERP separa as coisas de formas diferentes:
      - `codigos` = ESTQCOD, o item de estoque → separa PRODUTO (CH-II, hidráulica);
      - `locais` = EQPLOC, a localização do equipamento → separa FÁBRICA
        (23 = FCM I, 24 = FCM II, 25 = FCM III), que é como o painel do calcário
        soma o volume de cada moinho.
    Podem ser usados juntos; sem nenhum dos dois não há o que consultar.

    Consulta o SQL Server do ERP — a mesma base dos painéis de produção. Os
    endpoints de lá só aceitam "atual/mensal/anual", então a consulta é própria,
    com intervalo de datas; o `engine` é importado de lá para não duplicar
    credencial de banco em mais um arquivo.

    Devolve {} em qualquer falha: sem produção o boletim ainda funciona (o ponderado
    cai para média simples), e o laboratório não pode ficar sem a tela porque a rede
    do ERP caiu.
    """
    if not codigos and not locais:
        return {}
    try:
        import pandas as pd
        from bisGerenciais.dashboardOperacoes.cal.views import engine
    except Exception:
        logger.exception('Não foi possível preparar a consulta de produção do ERP')
        return {}

    filtros = []
    if codigos:
        filtros.append(f"AND IBPROREF IN ({','.join(str(c) for c in codigos)})")
    if locais:
        filtros.append(f"AND EQPLOC IN ({','.join(str(l) for l in locais)})")
    if etapa:
        filtros.append(f'AND BPROEP = {int(etapa)}')
    # A janela do dia de produção começa 07:10 (mesma convenção dos painéis).
    inicio = f'{ano - 1}-12-25 07:10:00'
    fim = f'{ano + 1}-01-05 07:10:00'
    sql = f"""
        SELECT BPRODATA1 AS DIA, ((ESTQPESO * IBPROQUANT) / 1000) AS PESO
          FROM BAIXAPRODUCAO
          JOIN ITEMBAIXAPRODUCAO ON BPROCOD = IBPROBPRO
          JOIN ESTOQUE ON ESTQCOD = IBPROREF
          -- LEFT JOIN, e não INNER: baixa sem equipamento apontado continua contando
          -- quando o recorte é só por produto.
          LEFT OUTER JOIN EQUIPAMENTO ON EQPCOD = BPROEQP
         WHERE CAST(BPRODATA1 AS datetime2) BETWEEN '{inicio}' AND '{fim}'
           AND BPROEMP = 1 AND BPROFIL = 0 AND BPROSIT = 1 AND IBPROTIPO = 'D'
           {' '.join(filtros)}
    """
    try:
        df = pd.read_sql(sql, engine)
    except Exception:
        logger.exception(
            'Falha ao consultar produção do ERP (codigos=%s, locais=%s, etapa=%s)',
            codigos, locais, etapa,
        )
        return {}

    por_dia: dict = {}
    for _, linha in df.iterrows():
        dia = linha['DIA']
        if dia is None:
            continue
        dia = dia.date() if hasattr(dia, 'date') else dia
        if semana_de(dia)[0] != ano:
            continue  # cai na virada do ano ISO
        por_dia[dia] = por_dia.get(dia, 0.0) + float(linha['PESO'] or 0)
    return por_dia


def producao_por_semana(por_dia: dict) -> dict:
    """Soma o diário por semana ISO — sem consultar o ERP de novo."""
    por_semana: dict = {}
    for dia, peso in por_dia.items():
        semana = semana_de(dia)[1]
        por_semana[semana] = por_semana.get(semana, 0.0) + peso
    return por_semana


# ── Montagem do boletim ──────────────────────────────────────────────────────

def _media(valores):
    return sum(valores) / len(valores) if valores else None


def situacao(indicador, valor):
    """
    dentro | fora | referencia | sem_limite | sem_dado — é o que pinta a célula.

    Meta não reprova: ela é referência de gestão (a planilha trazia META e LIMITE
    MÁX. em colunas diferentes justamente porque só o limite é obrigação).
    """
    if valor is None:
        return 'sem_dado'
    if indicador.valor_limite is None:
        return 'sem_limite'
    if indicador.tipo_limite == 'MAX':
        return 'fora' if valor > indicador.valor_limite else 'dentro'
    if indicador.tipo_limite == 'MIN':
        return 'fora' if valor < indicador.valor_limite else 'dentro'
    if indicador.tipo_limite == 'META':
        return 'referencia'
    return 'sem_limite'


class SerieIndicador:
    """
    O ano inteiro de um indicador, já com calculado, manual e ponderação resolvidos.

    Existe como classe (e não dicionário solto) porque o mesmo objeto serve à tela
    da semana, ao gráfico do ano e ao PDF — e cada um pede um corte diferente.
    """

    def __init__(self, indicador, ano: int):
        self.indicador = indicador
        self.ano = ano
        self.semanas = total_de_semanas(ano)
        self.componentes: list['SerieIndicador'] = []
        self.calculado: dict[int, float] = {}
        self.medicoes: dict[int, int] = {}
        # Semanas em que o ponderado caiu para média simples por falta de produção.
        self.simples: set[int] = set()
        # O valor de cada DIA. No calcário é ele que interessa: sai uma amostra
        # composta por dia, por fábrica, e o relatório mostra o dia a dia da semana
        # (como as abas PN/PRNT/RE PONDERADO da planilha, que são diárias).
        self.por_dia: dict = {}
        # Os valores CRUS de cada dia, antes da média. O período livre precisa deles:
        # a média de um intervalo é a média de todas as medições, e não a média das
        # médias diárias — dia com 3 análises pesa mais do que dia com 1.
        self.valores_dia: dict = {}
        self.producao: dict[int, float] = {}
        self.producao_dia: dict = {}
        self.manual: dict[int, dict] = {}

    # -- carga ---------------------------------------------------------------

    def carregar(self, resultados_manuais):
        """`resultados_manuais`: lista de ResultadoBoletim já filtrada por ano."""
        self.manual = {
            r.semana: {'valor': r.valor, 'texto': r.texto, 'producao': r.producao, 'observacao': r.observacao}
            for r in resultados_manuais if r.indicador_id == self.indicador.id
        }

        if self.indicador.agregacao == 'PONDERADO':
            for filho in self.componentes:
                filho.carregar(resultados_manuais)
            self._calcular_ponderado()
        else:
            por_dia_bruto = valores_por_dia(self.indicador, self.ano)
            por_semana: dict = {}
            for dia, valores in por_dia_bruto.items():
                self.por_dia[dia] = _media(valores)
                self.valores_dia[dia] = list(valores)
                por_semana.setdefault(semana_de(dia)[1], []).extend(valores)
            for semana, valores in por_semana.items():
                self.calculado[semana] = _media(valores)
                self.medicoes[semana] = len(valores)

        if self.indicador.tem_producao_configurada():
            self.producao_dia = producao_por_dia(
                self.indicador.codigos_producao(),
                self.indicador.locais_producao(),
                self.indicador.producao_etapa,
                self.ano,
            )
            self.producao = producao_por_semana(self.producao_dia)
        # Produção digitada vence a do ERP: quem digitou sabia de algo que o ERP não sabe.
        for semana, dados in self.manual.items():
            if dados.get('producao') is not None:
                self.producao[semana] = dados['producao']

    def _calcular_ponderado(self):
        """
        Média ponderada pela produção de cada componente.

        Sem produção em nenhum componente, cai para média simples e a tela avisa —
        é melhor mostrar um número aproximado marcado do que uma célula vazia num
        indicador que a diretoria acompanha toda semana.
        """
        for semana in range(1, self.semanas + 1):
            pares = []
            analises = 0
            for filho in self.componentes:
                valor = filho.valor_final(semana)
                if valor is None:
                    continue
                pares.append((valor, filho.producao.get(semana)))
                # A coluna "Amostras" conta ANÁLISE, não componente: o PN ponderado
                # de uma semana vem de 21 amostras (7 dias × 3 fábricas), e mostrar
                # "3" ali fazia parecer que a semana teve três medições.
                analises += filho.medicoes.get(semana, 0)
            if not pares:
                continue
            self.medicoes[semana] = analises or len(pares)
            pesos = [p for _, p in pares if p]
            if len(pesos) == len(pares) and sum(pesos) > 0:
                total = sum(v * p for v, p in pares)
                self.calculado[semana] = total / sum(pesos)
                self.producao.setdefault(semana, sum(pesos))
            else:
                self.calculado[semana] = _media([v for v, _ in pares])
                # Conjunto próprio, e não o sinal do número: a contagem virou o total
                # de análises, então um "negativo" ali não teria mais como ser lido.
                self.simples.add(semana)

        self._calcular_ponderado_diario()

    def _calcular_ponderado_diario(self):
        """
        Mesmo cálculo, dia a dia — é o que o relatório do calcário mostra.

        A produção também é diária aqui (a consulta ao ERP já devolve por dia), então
        o ponderado do dia usa o volume DAQUELE dia. Somar a produção da semana para
        ponderar um dia daria peso errado a uma fábrica que parou no meio da semana.
        """
        dias = {d for filho in self.componentes for d in filho.por_dia}
        for dia in dias:
            pares = []
            for filho in self.componentes:
                valor = filho.por_dia.get(dia)
                if valor is None:
                    continue
                pares.append((valor, filho.producao_dia.get(dia)))
            if not pares:
                continue
            pesos = [p for _, p in pares if p]
            if len(pesos) == len(pares) and sum(pesos) > 0:
                self.por_dia[dia] = sum(v * p for v, p in pares) / sum(pesos)
                self.producao_dia.setdefault(dia, sum(pesos))
            else:
                self.por_dia[dia] = _media([v for v, _ in pares])

    # -- leitura -------------------------------------------------------------

    def valor_final(self, semana: int):
        """Manual vence calculado; texto sem número devolve None."""
        manual = self.manual.get(semana)
        if manual and manual.get('valor') is not None:
            return manual['valor']
        if manual and manual.get('texto'):
            return None
        return self.calculado.get(semana)

    def dias(self, semana: int) -> list:
        """
        Uma linha por dia da semana que tem valor — o corpo do relatório do calcário.

        Só os dias COM medição: linha vazia de domingo e de dia parado só ocuparia
        espaço na folha.
        """
        return self._linhas_dos_dias(d for d in self.por_dia if semana_de(d) == (self.ano, semana))

    def dias_periodo(self, inicio: date, fim: date) -> list:
        """O mesmo dia a dia, para um intervalo livre de datas."""
        return self._linhas_dos_dias(d for d in self.por_dia if inicio <= d <= fim)

    def _linhas_dos_dias(self, dias) -> list:
        return [
            {
                'data': dia,
                'valor': self.por_dia[dia],
                'producao': self.producao_dia.get(dia),
                'situacao': situacao(self.indicador, self.por_dia[dia]),
            }
            for dia in sorted(dias)
        ]

    # -- período livre --------------------------------------------------------

    def _valores_do_periodo(self, inicio: date, fim: date) -> list:
        """Todas as medições do intervalo, cruas — sem passar pela média do dia."""
        valores: list = []
        for dia, lista in self.valores_dia.items():
            if inicio <= dia <= fim:
                valores.extend(lista)
        return valores

    def producao_do_periodo(self, inicio: date, fim: date):
        total = sum(p for d, p in self.producao_dia.items() if inicio <= d <= fim and p)
        return total or None

    def celula_periodo(self, inicio: date, fim: date) -> dict:
        """
        A célula de um intervalo livre de datas, no mesmo formato da célula da semana.

        Duas diferenças que a tela precisa respeitar: a correção manual é gravada por
        SEMANA (`ResultadoBoletim`), então aqui o número é sempre o calculado — não há
        registro de "período 3/8 a 19/8" para aplicar —, e o ponderado é pesado pela
        produção do intervalo inteiro, e não pela de cada semana.
        """
        simples = False
        if self.indicador.agregacao == 'PONDERADO':
            pares, medicoes = [], 0
            for filho in self.componentes:
                valores = filho._valores_do_periodo(inicio, fim)
                if not valores:
                    continue
                pares.append((_media(valores), filho.producao_do_periodo(inicio, fim)))
                medicoes += len(valores)
            valor = producao = None
            if pares:
                pesos = [p for _, p in pares if p]
                if len(pesos) == len(pares) and sum(pesos) > 0:
                    valor = sum(v * p for v, p in pares) / sum(pesos)
                    producao = sum(pesos)
                else:
                    valor = _media([v for v, _ in pares])
                    simples = True
        else:
            valores = self._valores_do_periodo(inicio, fim)
            valor = _media(valores) if valores else None
            medicoes = len(valores)
            producao = self.producao_do_periodo(inicio, fim)

        return {
            'semana': None,
            'valor': valor,
            'valor_calculado': valor,
            'texto': '',
            'observacao': '',
            'origem': 'calculado',
            'medicoes': medicoes,
            'media_simples': simples,
            'producao': producao,
            'situacao': situacao(self.indicador, valor),
        }

    def absorver(self, outra: 'SerieIndicador'):
        """
        Junta os dias de outro ano do MESMO indicador.

        Serve ao período que cruza a virada do ano: o cálculo é feito ano a ano, e o
        intervalo 15/12 a 15/01 precisa dos dois. Só os mapas por dia são juntados —
        a série por semana continua sendo a do ano pedido, que é o que o gráfico mostra.
        """
        self.valores_dia.update(outra.valores_dia)
        self.por_dia.update(outra.por_dia)
        self.producao_dia.update(outra.producao_dia)

        por_id = {c.indicador.id: c for c in outra.componentes}
        for filho in self.componentes:
            gemeo = por_id.get(filho.indicador.id)
            if gemeo:
                filho.absorver(gemeo)
        if self.indicador.agregacao == 'PONDERADO':
            self._calcular_ponderado_diario()

    def celula(self, semana: int) -> dict:
        manual = self.manual.get(semana) or {}
        valor = self.valor_final(semana)
        medicoes = self.medicoes.get(semana, 0)
        return {
            'semana': semana,
            'valor': valor,
            'valor_calculado': self.calculado.get(semana),
            'texto': manual.get('texto') or '',
            'observacao': manual.get('observacao') or '',
            'origem': 'manual' if (manual.get('valor') is not None or manual.get('texto')) else 'calculado',
            'medicoes': medicoes,
            'media_simples': semana in self.simples,
            'producao': self.producao.get(semana),
            'situacao': situacao(self.indicador, valor),
        }
