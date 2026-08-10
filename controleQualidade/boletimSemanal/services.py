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
    """
    filtro = Q()
    for termo in (texto or '').split(','):
        termo = termo.strip()
        if termo:
            filtro |= Q(**{f'{campo}__icontains': termo})
    return filtro


def _queryset_do_indicador(indicador, ano: int):
    """Análises que alimentam este indicador no ano — um filtro só, para o ano todo."""
    qs = Analise.objects.select_related('amostra', 'amostra__produto_amostra')

    for campo, texto in [
        ('amostra__material', indicador.material),
        ('amostra__tipo_amostra', indicador.tipo_amostra),
        ('amostra__local_coleta', indicador.local_coleta),
        ('amostra__finalidade', indicador.finalidade),
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
    return qs.distinct()


def valores_por_analise(indicador, ano: int):
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


def valores_por_semana(indicador, ano: int) -> dict[int, list[float]]:
    """Os valores do ano agrupados pela semana ISO — é o que alimenta o boletim."""
    valores, por_id = valores_por_analise(indicador, ano)
    por_semana: dict[int, list[float]] = {}
    for analise_id, valor in valores.items():
        semana = _semana_da_analise(por_id[analise_id], indicador, ano)
        if semana is not None:
            por_semana.setdefault(semana, []).append(valor)
    return por_semana


def analises_da_semana(indicador, ano: int, semana: int) -> list[dict]:
    """
    As análises que entraram no número de uma semana, com o que a tela precisa para
    listá-las e abrir cada uma: número da amostra, valor, data e ponto de coleta.
    """
    valores, por_id = valores_por_analise(indicador, ano)
    linhas = []
    for analise_id, valor in valores.items():
        analise = por_id[analise_id]
        if _semana_da_analise(analise, indicador, ano) != semana:
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
        })
    # Por data: é a ordem em que o laboratório lê o histórico da semana.
    linhas.sort(key=lambda l: (l['data'] or date.min, l['analise_id']))
    return linhas


def _valores_de_campo_especial(indicador, analises) -> dict[int, float]:
    """
    Valores que moram em campo JSON da análise (peneiras, por exemplo).

    Reaproveita o extrator do `filtrar-e-calcular` em vez de reescrever a leitura
    da malha — é código sensível, cheio de variações de rótulo de peneira.
    """
    try:
        from controleQualidade.analise.views import _extrair_valor_peneira
    except ImportError:
        logger.warning('Extrator de peneira indisponível; campo_especial ignorado.')
        return {}

    if indicador.campo_especial not in ('peneiras_secas', 'peneiras_umidas'):
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

def producao_por_semana(codigos: list[int], etapa, ano: int) -> dict[int, float]:
    """
    Toneladas produzidas por semana ISO, somando os códigos de estoque informados.

    Consulta o SQL Server do ERP — a mesma base dos painéis de produção. Os
    endpoints de lá só aceitam "atual/mensal/anual", então a consulta é própria,
    com intervalo de datas; o `engine` é importado de lá para não duplicar
    credencial de banco em mais um arquivo.

    Devolve {} em qualquer falha: a produção é um ENFEITE do boletim (serve para
    ponderar), e o laboratório não pode ficar sem a tela porque a rede do ERP caiu.
    """
    if not codigos:
        return {}
    try:
        import pandas as pd
        from bisGerenciais.dashboardOperacoes.cal.views import engine
    except Exception:
        logger.exception('Não foi possível preparar a consulta de produção do ERP')
        return {}

    lista_codigos = ','.join(str(c) for c in codigos)
    filtro_etapa = f"AND BPROEP = {int(etapa)}" if etapa else ''
    # A janela do dia de produção começa 07:10 (mesma convenção dos painéis).
    inicio = f'{ano - 1}-12-25 07:10:00'
    fim = f'{ano + 1}-01-05 07:10:00'
    sql = f"""
        SELECT BPRODATA1 AS DIA, ((ESTQPESO * IBPROQUANT) / 1000) AS PESO
          FROM BAIXAPRODUCAO
          JOIN ITEMBAIXAPRODUCAO ON BPROCOD = IBPROBPRO
          JOIN ESTOQUE ON ESTQCOD = IBPROREF
         WHERE CAST(BPRODATA1 AS datetime2) BETWEEN '{inicio}' AND '{fim}'
           AND BPROEMP = 1 AND BPROFIL = 0 AND BPROSIT = 1 AND IBPROTIPO = 'D'
           AND IBPROREF IN ({lista_codigos})
           {filtro_etapa}
    """
    try:
        df = pd.read_sql(sql, engine)
    except Exception:
        logger.exception('Falha ao consultar produção do ERP (codigos=%s, etapa=%s)', lista_codigos, etapa)
        return {}

    por_semana: dict[int, float] = {}
    for _, linha in df.iterrows():
        dia = linha['DIA']
        if dia is None:
            continue
        dia = dia.date() if hasattr(dia, 'date') else dia
        ano_iso, semana = semana_de(dia)
        if ano_iso != ano:
            continue
        por_semana[semana] = por_semana.get(semana, 0.0) + float(linha['PESO'] or 0)
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
        self.producao: dict[int, float] = {}
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
            por_semana = valores_por_semana(self.indicador, self.ano)
            for semana, valores in por_semana.items():
                self.calculado[semana] = _media(valores)
                self.medicoes[semana] = len(valores)

        codigos = self.indicador.codigos_producao()
        if codigos:
            self.producao = producao_por_semana(codigos, self.indicador.producao_etapa, self.ano)
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
            for filho in self.componentes:
                valor = filho.valor_final(semana)
                if valor is None:
                    continue
                pares.append((valor, filho.producao.get(semana)))
            if not pares:
                continue
            self.medicoes[semana] = len(pares)
            pesos = [p for _, p in pares if p]
            if len(pesos) == len(pares) and sum(pesos) > 0:
                total = sum(v * p for v, p in pares)
                self.calculado[semana] = total / sum(pesos)
                self.producao.setdefault(semana, sum(pesos))
            else:
                self.calculado[semana] = _media([v for v, _ in pares])
                self.medicoes[semana] = -len(pares)  # negativo = média simples (sem produção)

    # -- leitura -------------------------------------------------------------

    def valor_final(self, semana: int):
        """Manual vence calculado; texto sem número devolve None."""
        manual = self.manual.get(semana)
        if manual and manual.get('valor') is not None:
            return manual['valor']
        if manual and manual.get('texto'):
            return None
        return self.calculado.get(semana)

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
            'medicoes': abs(medicoes),
            'media_simples': medicoes < 0,
            'producao': self.producao.get(semana),
            'situacao': situacao(self.indicador, valor),
        }
