"""Relatório de comissões sobre o que a empresa JÁ RECEBEU (agronegócio).

Os representantes do agro são pagos sobre o valor efetivamente recebido do
cliente, não sobre o faturado. A cadeia no ERP é:

    NOTAFISCAL -> DUPLICATA -> CONTARECEBER -> ITEMRECEBIMENTO -> RECEBIMENTO

Dois rateios são necessários e ambos são feitos aqui, nunca no front:

1. Rateio do título por nota. Um mesmo título (CRNUM) pode cobrir várias notas
   (faturamento agrupado), então somar o recebido por nota duplicaria valor. A
   fração de cada nota é DUPVALOR / SUM(DUPVALOR) do título -- normalizar pela
   soma das duplicatas, e não por CRTOTAL, garante que o rateio nunca estoure
   (CRTOTAL diverge da soma em renegociação/abatimento).

2. Rateio agro dentro da nota. Notas mistas (agro + construção civil) existem,
   então só a fração VALOR_AGRO / VALOR_ITENS conta para a comissão do agro.

A comissão devida é `recebido_agro * taxa_comissao_recebimento` do representante.
Quem não tem taxa cadastrada entra no relatório com comissão zero e é listado em
`sem_taxa` -- silenciar isso esconderia representante não configurado.
"""
import datetime as dt

import pandas as pd
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import PagamentoComissao, Representante
from .views import engine

# Grupos de almoxarifado que definem produto do agronegócio.
# Mesma lista usada em views.calculos_comissoes -- se mudar lá, muda aqui.
GRUPOS_ALMOX_AGRO = (1974, 1587, 1828)


def _cte_nf_agro() -> str:
    """CTEs comuns: valor agro/total de cada nota e soma das duplicatas por título.

    Os filtros de venda válida são os mesmos da query principal de comissões
    (NFSIT=1, GALMPRODVENDA='S', flags de natureza de operação, série de acerto fora),
    para que o faturado deste relatório bata com o do acompanhamento.
    """
    grupos = ','.join(str(g) for g in GRUPOS_ALMOX_AGRO)
    return f"""
    WITH NF_AGRO AS (
        SELECT NF.NFCOD,
               SUM(CASE WHEN ESTQGALM IN ({grupos}) THEN INFTOTAL ELSE 0 END) AS VALOR_AGRO,
               SUM(INFTOTAL)                                                  AS VALOR_ITENS
        FROM NOTAFISCAL NF
        JOIN ITEMNOTAFISCAL   ON INFNFCOD = NF.NFCOD
        JOIN ESTOQUE          ON ESTQCOD = INFESTQ
        JOIN NATUREZAOPERACAO ON NOPCOD = INFNOP
        JOIN GRUPOALMOXARIFADO ON GALMCOD = ESTQGALM
        WHERE NF.NFSIT = 1
          AND GALMPRODVENDA = 'S'
          AND (SUBSTRING(NOPFLAGNF,1,1) = 'S' AND SUBSTRING(NOPFLAGNF,25,1) = 'N')
          AND NF.NFSNF NOT IN (8)
        GROUP BY NF.NFCOD
        HAVING SUM(CASE WHEN ESTQGALM IN ({grupos}) THEN INFTOTAL ELSE 0 END) > 0
    ),
    DUP_CR AS (
        SELECT DUPNUM, SUM(DUPVALOR) AS SOMA_DUP
        FROM DUPLICATA GROUP BY DUPNUM
    )
    """


def _sql_titulos(data_inicio: str, data_fim: str, modo: str) -> str:
    """Um registro por (nota, título): base do faturado, em aberto e vencido.

    RECEBIDO_TITULO é o total já recebido do título inteiro (todas as notas dele);
    o rateio para esta nota é feito depois, via SHARE_DUP.
    """
    if modo == 'emissao':
        filtro = f"CAST(NF.NFDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'"
    else:
        # Modo recebimento: só os títulos que tiveram algum recebimento na janela.
        filtro = f"""EXISTS (
            SELECT 1 FROM ITEMRECEBIMENTO IR2
            JOIN RECEBIMENTO REC2 ON REC2.RECNUM = IR2.IRECREC
            WHERE IR2.IRECCR = CR.CRNUM
              AND CAST(REC2.RECDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
        )"""

    return _cte_nf_agro() + f"""
    SELECT
        NF.NFCOD                              AS NF_COD,
        NF.NFNUM                              AS NOTA_FISCAL,
        CAST(NF.NFDATA AS DATE)               AS DATA_EMISSAO,
        CLINOME                               AS CLIENTE,
        R.REPNOME                             AS REPRESENTANTE,
        M.REPNOME                             AS MASTER,
        CR.CRNUM                              AS TITULO,
        D.DUPPARNUM                           AS PARCELA,
        CAST(CR.CRVENC AS DATE)               AS VENCIMENTO,
        D.DUPVALOR                            AS VALOR_PARCELA,
        (D.DUPVALOR / NULLIF(DC.SOMA_DUP, 0)) AS SHARE_DUP,
        COALESCE((SELECT SUM(IR.IRECVALOR) FROM ITEMRECEBIMENTO IR
                  WHERE IR.IRECCR = CR.CRNUM), 0)                AS RECEBIDO_TITULO,
        (NA.VALOR_AGRO / NULLIF(NA.VALOR_ITENS, 0))              AS PCT_AGRO
    FROM NF_AGRO NA
    JOIN NOTAFISCAL NF   ON NF.NFCOD = NA.NFCOD
    JOIN CLIENTE         ON CLICOD = NF.NFCLI
    LEFT JOIN REPRESENTANTE R ON R.REPCOD = NF.NFREP
    LEFT JOIN REPRESENTANTE M ON M.REPCOD = R.REPREPREF
    JOIN DUPLICATA D     ON D.DUPNFCOD = NA.NFCOD
    JOIN DUP_CR DC       ON DC.DUPNUM = D.DUPNUM
    JOIN CONTARECEBER CR ON CR.CRNUM = D.DUPNUM
    WHERE {filtro}
    """


def _sql_recebimentos(data_inicio: str, data_fim: str, modo: str) -> str:
    """Um registro por (nota, título, recebimento): base do valor recebido.

    No modo 'recebimento' a janela filtra a data do recebimento (o que entrou no
    caixa no período). No modo 'emissao' pega todos os recebimentos das notas do
    período, independente de quando o dinheiro entrou.
    """
    if modo == 'emissao':
        filtro = f"CAST(NF.NFDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'"
    else:
        filtro = f"CAST(REC.RECDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'"

    return _cte_nf_agro() + f"""
    SELECT
        NF.NFCOD                                AS NF_COD,
        NF.NFNUM                                AS NOTA_FISCAL,
        CR.CRNUM                                AS TITULO,
        R.REPNOME                               AS REPRESENTANTE,
        M.REPNOME                               AS MASTER,
        CAST(REC.RECDATA AS DATE)               AS DATA_RECEBIMENTO,
        -- valor do recebimento rateado para esta nota e depois para a parte agro
        IR.IRECVALOR * (D.DUPVALOR / NULLIF(DC.SOMA_DUP, 0))                     AS RECEBIDO_NF,
        IR.IRECVALOR * (D.DUPVALOR / NULLIF(DC.SOMA_DUP, 0))
                     * (NA.VALOR_AGRO / NULLIF(NA.VALOR_ITENS, 0))               AS RECEBIDO_AGRO
    FROM NF_AGRO NA
    JOIN NOTAFISCAL NF   ON NF.NFCOD = NA.NFCOD
    LEFT JOIN REPRESENTANTE R ON R.REPCOD = NF.NFREP
    LEFT JOIN REPRESENTANTE M ON M.REPCOD = R.REPREPREF
    JOIN DUPLICATA D     ON D.DUPNFCOD = NA.NFCOD
    JOIN DUP_CR DC       ON DC.DUPNUM = D.DUPNUM
    JOIN CONTARECEBER CR ON CR.CRNUM = D.DUPNUM
    JOIN ITEMRECEBIMENTO IR ON IR.IRECCR = CR.CRNUM
    JOIN RECEBIMENTO REC ON REC.RECNUM = IR.IRECREC
    WHERE {filtro}
    """


def _norm(nome) -> str:
    return (nome or '').strip().upper()


def _competencias(data_inicio: str, data_fim: str):
    """Faixa de competências AAAA-MM coberta pelo período."""
    return data_inicio[:7], data_fim[:7]


@csrf_exempt
@api_view(['POST'])
def comissoes_recebidas(request):
    data_inicio = request.data.get('dataInicio')
    data_fim = request.data.get('dataFim')
    if not data_inicio or not data_fim:
        return Response({'erro': 'Informe dataInicio e dataFim (AAAA-MM-DD).'}, status=400)

    modo = request.data.get('modo') or 'recebimento'
    if modo not in ('recebimento', 'emissao'):
        return Response({'erro': "modo deve ser 'recebimento' ou 'emissao'."}, status=400)

    filtro_rep = _norm(request.data.get('representante'))

    df_tit = pd.read_sql(_sql_titulos(data_inicio, data_fim, modo), engine)
    df_rec = pd.read_sql(_sql_recebimentos(data_inicio, data_fim, modo), engine)

    for df in (df_tit, df_rec):
        df['REPRESENTANTE'] = df['REPRESENTANTE'].fillna('').map(_norm)
        df['MASTER'] = df['MASTER'].fillna('').map(_norm)
        # Vendas sem representante externo credenciado ficam no nome de quem
        # assinou a nota; sem isso elas sumiriam do relatório.
        df.loc[df['REPRESENTANTE'] == '', 'REPRESENTANTE'] = '(SEM REPRESENTANTE)'

    if filtro_rep:
        df_tit = df_tit[df_tit['REPRESENTANTE'] == filtro_rep]
        df_rec = df_rec[df_rec['REPRESENTANTE'] == filtro_rep]

    # ---- Valores por título (faturado / em aberto / vencido), já rateados p/ agro
    if len(df_tit):
        df_tit['FATURADO_AGRO'] = df_tit['VALOR_PARCELA'] * df_tit['PCT_AGRO']
        bruto = df_tit['RECEBIDO_TITULO'] * df_tit['SHARE_DUP'] * df_tit['PCT_AGRO']
        # IRECVALOR inclui juros e multa, então o recebido pode passar do valor da
        # duplicata. Comissão incide sobre o principal, não sobre encargos de atraso:
        # a base é limitada ao faturado e o excedente vira `ENCARGOS`, exposto à parte.
        df_tit['RECEBIDO_DO_TITULO'] = bruto.clip(upper=df_tit['FATURADO_AGRO'])
        df_tit['ENCARGOS'] = (bruto - df_tit['RECEBIDO_DO_TITULO']).clip(lower=0)
        # Mesmo fator serve para descontar encargos do recebido datado (modo recebimento),
        # inclusive quando o título é quitado em parcelas de meses diferentes.
        df_tit['FATOR_PRINCIPAL'] = (df_tit['RECEBIDO_DO_TITULO'] / bruto.replace(0, pd.NA)).fillna(1.0)
        df_tit['ABERTO_AGRO'] = (df_tit['FATURADO_AGRO'] - df_tit['RECEBIDO_DO_TITULO']).clip(lower=0)
        hoje = dt.date.today()
        venc = pd.to_datetime(df_tit['VENCIMENTO'], errors='coerce').dt.date
        df_tit['VENCIDO_AGRO'] = df_tit['ABERTO_AGRO'].where(
            venc.notna() & (venc < hoje) & (df_tit['ABERTO_AGRO'] > 0.01), 0.0
        )
    else:
        for col in ('FATURADO_AGRO', 'RECEBIDO_DO_TITULO', 'ENCARGOS',
                    'FATOR_PRINCIPAL', 'ABERTO_AGRO', 'VENCIDO_AGRO'):
            df_tit[col] = pd.Series(dtype=float)

    # Aplica o mesmo desconto de encargos no recebido datado, por (nota, título)
    if len(df_rec) and len(df_tit):
        fatores = (df_tit.groupby(['NF_COD', 'TITULO'], as_index=False)['FATOR_PRINCIPAL'].min())
        df_rec = df_rec.merge(fatores, on=['NF_COD', 'TITULO'], how='left')
        df_rec['FATOR_PRINCIPAL'] = df_rec['FATOR_PRINCIPAL'].fillna(1.0)
        df_rec['RECEBIDO_AGRO'] = df_rec['RECEBIDO_AGRO'] * df_rec['FATOR_PRINCIPAL']

    # ---- Taxas cadastradas e repasses já pagos
    taxas, ids_rep, agro_flag = {}, {}, {}
    for rep in Representante.objects.all():
        chave = _norm(rep.nome)
        taxas[chave] = float(rep.taxa_comissao_recebimento or 0)
        ids_rep[chave] = rep.id
        agro_flag[chave] = _norm(rep.segmento) == 'AGRONEGOCIO'

    comp_de, comp_ate = _competencias(data_inicio, data_fim)
    pagos = {}
    qs_pag = PagamentoComissao.objects.filter(
        periodo__gte=comp_de, periodo__lte=comp_ate
    ).select_related('representante')
    for pag in qs_pag:
        chave = _norm(pag.representante.nome)
        pagos[chave] = pagos.get(chave, 0.0) + float(pag.valor)

    # ---- Agregação por representante
    nomes = sorted(set(df_tit['REPRESENTANTE']) | set(df_rec['REPRESENTANTE']))
    linhas, sem_taxa = [], []

    for nome in nomes:
        tit = df_tit[df_tit['REPRESENTANTE'] == nome]
        rec = df_rec[df_rec['REPRESENTANTE'] == nome]

        faturado = float(tit['FATURADO_AGRO'].sum()) if len(tit) else 0.0
        aberto = float(tit['ABERTO_AGRO'].sum()) if len(tit) else 0.0
        vencido = float(tit['VENCIDO_AGRO'].sum()) if len(tit) else 0.0
        recebido_datado = float(rec['RECEBIDO_AGRO'].sum()) if len(rec) else 0.0
        encargos = float(tit['ENCARGOS'].sum()) if len(tit) else 0.0

        if modo == 'emissao':
            # Parte do ITEMRECEBIMENTO do ERP não tem cabeçalho em RECEBIMENTO (~150 linhas
            # em 2026), ou seja: o dinheiro entrou mas não dá para datar. No modo emissão o
            # total recebido dessas notas tem que incluir esse valor, senão ele apareceria
            # como saldo em aberto. `recebido_sem_data` expõe a fatia não datável.
            recebido = float(tit['RECEBIDO_DO_TITULO'].sum()) if len(tit) else 0.0
            recebido_sem_data = max(recebido - recebido_datado, 0.0)
        else:
            # Por data de recebimento, só o que tem data pode entrar na janela.
            recebido = recebido_datado
            recebido_sem_data = 0.0

        taxa = taxas.get(nome, 0.0)
        if taxa <= 0 and nome != '(SEM REPRESENTANTE)':
            sem_taxa.append(nome)
        devida = recebido * taxa / 100.0
        pago = pagos.get(nome, 0.0)

        masters = [m for m in tit['MASTER'].unique() if m] if len(tit) else []

        # Detalhe título a título, para o drawer e o PDF
        titulos = []
        if len(tit):
            det = tit.sort_values(['DATA_EMISSAO', 'NOTA_FISCAL', 'PARCELA'])
            for _, r in det.iterrows():
                titulos.append({
                    'nota_fiscal': int(r['NOTA_FISCAL']),
                    'data_emissao': r['DATA_EMISSAO'].strftime('%d/%m/%Y') if pd.notna(r['DATA_EMISSAO']) else '',
                    'cliente': r['CLIENTE'],
                    'titulo': int(r['TITULO']),
                    'parcela': int(r['PARCELA']) if pd.notna(r['PARCELA']) else 0,
                    'vencimento': r['VENCIMENTO'].strftime('%d/%m/%Y') if pd.notna(r['VENCIMENTO']) else '',
                    'faturado': round(float(r['FATURADO_AGRO']), 2),
                    'recebido': round(float(r['RECEBIDO_DO_TITULO']), 2),
                    'aberto': round(float(r['ABERTO_AGRO']), 2),
                    'vencido': round(float(r['VENCIDO_AGRO']), 2),
                    'pct_agro': round(float(r['PCT_AGRO']) * 100, 2),
                })

        # Recebimentos do período, para conferir data a data
        recebimentos = []
        if len(rec):
            agr = (rec.groupby(['DATA_RECEBIMENTO', 'NOTA_FISCAL', 'TITULO'], as_index=False)
                      ['RECEBIDO_AGRO'].sum().sort_values('DATA_RECEBIMENTO'))
            for _, r in agr.iterrows():
                recebimentos.append({
                    'data': r['DATA_RECEBIMENTO'].strftime('%d/%m/%Y') if pd.notna(r['DATA_RECEBIMENTO']) else '',
                    'nota_fiscal': int(r['NOTA_FISCAL']),
                    'titulo': int(r['TITULO']),
                    'valor': round(float(r['RECEBIDO_AGRO']), 2),
                })

        linhas.append({
            'representante': nome,
            'representante_id': ids_rep.get(nome),
            'is_agro': agro_flag.get(nome, False),
            'master': masters[0] if len(masters) == 1 else ('' if not masters else ' / '.join(sorted(masters))),
            'faturado': round(faturado, 2),
            'recebido': round(recebido, 2),
            'recebido_sem_data': round(recebido_sem_data, 2),
            'encargos': round(encargos, 2),
            'em_aberto': round(aberto, 2),
            'vencido': round(vencido, 2),
            'pct_recebido': round(recebido / faturado * 100, 2) if faturado > 0 else None,
            'taxa': taxa,
            'comissao_devida': round(devida, 2),
            'comissao_paga': round(pago, 2),
            'saldo_a_pagar': round(devida - pago, 2),
            'qtd_notas': int(tit['NOTA_FISCAL'].nunique()) if len(tit) else 0,
            'qtd_titulos': int(tit['TITULO'].nunique()) if len(tit) else 0,
            'titulos': titulos,
            'recebimentos': recebimentos,
        })

    linhas.sort(key=lambda x: x['recebido'], reverse=True)

    totais = {
        'faturado': round(sum(l['faturado'] for l in linhas), 2),
        'recebido': round(sum(l['recebido'] for l in linhas), 2),
        'recebido_sem_data': round(sum(l['recebido_sem_data'] for l in linhas), 2),
        'encargos': round(sum(l['encargos'] for l in linhas), 2),
        'em_aberto': round(sum(l['em_aberto'] for l in linhas), 2),
        'vencido': round(sum(l['vencido'] for l in linhas), 2),
        'comissao_devida': round(sum(l['comissao_devida'] for l in linhas), 2),
        'comissao_paga': round(sum(l['comissao_paga'] for l in linhas), 2),
        'saldo_a_pagar': round(sum(l['saldo_a_pagar'] for l in linhas), 2),
    }

    return Response({
        'modo': modo,
        'dataInicio': data_inicio,
        'dataFim': data_fim,
        'competencia_de': comp_de,
        'competencia_ate': comp_ate,
        'representantes': linhas,
        'totais': totais,
        'sem_taxa': sorted(set(sem_taxa)),
    })
