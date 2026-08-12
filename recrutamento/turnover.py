"""
Turnover (rotatividade) e absenteísmo — indicadores de RH.

⚠️ A fonte NÃO é o app `recrutamento`: aqui só existe o funil de contratação
(candidato → vaga → processo). Quem tem admissão e desligamento de verdade é o
ERP, na tabela ``CONTRATOPESSOAL``:

    COPTCP      1 = EMPREGADO (CLT) · 2 = TRABALHADOR AUTONOMO · 3 = SOCIOS
    COPDTINICIO admissão
    COPDTFINAL  desligamento — '1899-12-30' é o "vazio" do ERP, ou seja, contrato
                em aberto. Nunca comparar com NULL só: 957 contratos usam a data
                falsa em vez de nulo.

Só entra ``COPTCP = 1``. Autônomo e sócio não compõem quadro de empregados e
inflariam o índice (são 423 contratos, quase todos sem data de saída).

A base foi conferida ano a ano contra a identidade
``efetivo_final = efetivo_inicial + admissões - desligamentos`` — fecha exato de
2021 a 2026, e o efetivo de hoje (532) bate com os 563 ativos do cadastro
`management_colaborador` a menos dos autônomos/estagiários que aquele cadastro
também carrega.

⚠️ **Defasagem de registro**: o desligamento só é fechado no ERP quando a
rescisão é processada. Em 11/08/2026 o último desligamento gravado era de
12/06/2026, então janelas curtas (90 dias) subestimam a saída do mês corrente e
do anterior. O endpoint devolve `ultimo_desligamento_registrado` para a tela
poder avisar.

**Absenteísmo**: NÃO tem fonte digital hoje. O ponto eletrônico do ERP
(`PONTODIA`/`PONTOREG`) parou em 26/04/2023 e os afastamentos (`RH_AFASTAMENTOS`)
em 23/03/2023 — a folha ponto passou a ser feita fora. O cálculo está preparado
em `apurar_absenteismo`, esperando a folha ponto dos últimos 90 dias que o
escritório contábil vai enviar (pedida em 11/08/2026).
"""

import os
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, text

# Mesma string das comissões: dentro da rede o ERP responde no IP interno.
# Para rodar de fora (máquina do dev), exportar ERP_ODBC_URL com o IP externo:
#   mssql+pyodbc://DBCONSULTA:...@45.6.118.50,65530/DB?driver=ODBC+Driver+17+for+SQL+Server
ERP_ODBC_URL = os.environ.get(
    'ERP_ODBC_URL',
    'mssql+pyodbc://DBCONSULTA:%21%40%23123qweQWE@172.10.27.51:1433/DB'
    '?driver=ODBC+Driver+17+for+SQL+Server',
)

_engine = None

# Qualquer data até aqui é o "vazio" do ERP, não um desligamento de verdade.
DATA_VAZIA = date(1900, 1, 1)

TIPO_EMPREGADO = 1


def engine():
    """Engine preguiçosa: o import do módulo não pode depender do ERP no ar."""
    global _engine
    if _engine is None:
        _engine = create_engine(ERP_ODBC_URL)
    return _engine


def _data(valor):
    if valor is None:
        return None
    if isinstance(valor, datetime):
        valor = valor.date()
    return valor if valor > DATA_VAZIA else None


def carregar_contratos():
    """
    Todos os contratos de EMPREGADO, como ``[(admissao, desligamento|None)]``.

    São ~1.150 linhas: vale trazer tudo e contar em Python, em vez de disparar
    quatro COUNTs por mês contra o ERP.
    """
    sql = text(
        'SELECT COPDTINICIO, COPDTFINAL FROM CONTRATOPESSOAL WHERE COPTCP = :tipo'
    )
    with engine().connect() as conexao:
        linhas = conexao.execute(sql, {'tipo': TIPO_EMPREGADO}).fetchall()
    contratos = []
    for inicio, final in linhas:
        inicio = _data(inicio)
        if inicio:
            contratos.append((inicio, _data(final)))
    return contratos


def efetivo(contratos, dia):
    """Quantos estavam na casa no FIM do dia ``dia``."""
    return sum(
        1 for inicio, final in contratos
        if inicio <= dia and (final is None or final > dia)
    )


def apurar_periodo(contratos, inicio, fim, rotulo=''):
    """
    Um período fechado, com as duas leituras de turnover.

    ``turnover`` é a fórmula clássica — ((admissões + desligamentos) / 2)
    dividido pelo efetivo médio —, que foi a escolhida pelo RH em 11/08/2026.
    ``turnover_desligamento`` (só as saídas) vai junto porque é a leitura que
    mostra perda real de gente, e as duas costumam ser cobradas na mesma reunião.
    """
    admissoes = sum(1 for i, _ in contratos if inicio <= i <= fim)
    desligamentos = sum(1 for _, f in contratos if f and inicio <= f <= fim)
    inicial = efetivo(contratos, inicio - timedelta(days=1))
    final = efetivo(contratos, fim)
    medio = (inicial + final) / 2

    def taxa(valor):
        return round(valor / medio * 100, 2) if medio else None

    return {
        'rotulo': rotulo,
        'inicio': inicio.isoformat(),
        'fim': fim.isoformat(),
        'dias': (fim - inicio).days + 1,
        'admissoes': admissoes,
        'desligamentos': desligamentos,
        'efetivo_inicial': inicial,
        'efetivo_final': final,
        'efetivo_medio': round(medio, 1),
        'turnover': taxa((admissoes + desligamentos) / 2),
        'turnover_desligamento': taxa(desligamentos),
    }


def _fim_do_mes(ano, mes):
    return date(ano + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1)


def apurar_ano(contratos, ano, hoje=None):
    """O ano fechado + os 12 meses dele (o ano corrente para no mês de hoje)."""
    hoje = hoje or date.today()
    fim_ano = min(date(ano, 12, 31), hoje)
    dados = apurar_periodo(contratos, date(ano, 1, 1), fim_ano, rotulo=str(ano))

    meses = []
    for mes in range(1, 13):
        inicio_mes = date(ano, mes, 1)
        if inicio_mes > hoje:
            break
        mensal = apurar_periodo(
            contratos, inicio_mes, min(_fim_do_mes(ano, mes), hoje),
            rotulo=f'{ano:04d}-{mes:02d}',
        )
        meses.append(mensal)

    taxas = [m['turnover'] for m in meses if m['turnover'] is not None]
    dados['meses'] = meses
    # A média dos meses NÃO é o índice anual — é um número menor, mensal. Vai
    # junto porque parte dos painéis de RH chama isso de "índice médio".
    dados['media_mensal'] = round(sum(taxas) / len(taxas), 2) if taxas else None
    dados['ano'] = ano
    return dados


def apurar_absenteismo(inicio, fim):
    """
    Absenteísmo do período, a partir da folha ponto importada.

    A fonte NÃO é o ERP: o ponto eletrônico (``PONTODIA``/``PONTOREG``) parou em
    26/04/2023. Desde então o dado vem do espelho de ponto em PDF que o
    escritório contábil manda por competência, importado em
    ``recrutamento/folha_ponto.py`` -- que é onde estão a leitura, as armadilhas
    do relatório e a definição dos índices.

    Enquanto nenhuma competência tiver sido importada, devolve
    ``disponivel: False`` com o motivo, para a tela e o PDF mostrarem o
    indicador como pendente em vez de sumirem com ele.

    ``inicio``/``fim`` ficam no payload só como referência do que a tela pediu:
    o período de fato é o das competências importadas (de 26 a 25), que não
    coincide com a janela de 90 dias do turnover.
    """
    from .folha_ponto import apurar_do_banco

    dados = apurar_do_banco()
    dados['janela_pedida'] = {'inicio': inicio.isoformat(), 'fim': fim.isoformat()}
    return dados


def apurar(anos=(2022, 2023), dias=90, hoje=None):
    """Payload do endpoint: os anos pedidos, a janela curta e o absenteísmo."""
    hoje = hoje or date.today()
    contratos = carregar_contratos()

    anos_apurados = [apurar_ano(contratos, ano, hoje=hoje) for ano in anos]
    taxas = [a['turnover'] for a in anos_apurados if a['turnover'] is not None]

    inicio_janela = hoje - timedelta(days=dias - 1)
    janela = apurar_periodo(
        contratos, inicio_janela, hoje, rotulo=f'Últimos {dias} dias',
    )

    desligamentos = [f for _, f in contratos if f]
    admissoes = [i for i, _ in contratos]

    return {
        'gerado_em': hoje.isoformat(),
        'fonte': 'ERP · CONTRATOPESSOAL (COPTCP=1, empregados CLT)',
        'formula': '((admissões + desligamentos) / 2) ÷ efetivo médio × 100',
        'anos': anos_apurados,
        'media_anos': round(sum(taxas) / len(taxas), 2) if taxas else None,
        'janela': janela,
        'absenteismo': apurar_absenteismo(inicio_janela, hoje),
        # Deixa a tela avisar que a janela curta pode estar incompleta.
        'ultima_admissao_registrada': max(admissoes).isoformat() if admissoes else None,
        'ultimo_desligamento_registrado': (
            max(desligamentos).isoformat() if desligamentos else None
        ),
    }
