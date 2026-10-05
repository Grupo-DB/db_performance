"""Relatório de vendas e parcelas por representante (agronegócio).

Substitui o relatório que o laboratório/comercial montava à mão em planilha + PDF.
Acompanhamento de venda e de parcela, com a comissão do representante no rodapé.
A comissão incide **só sobre parcela recebida** — parcela em aberto aparece no
relatório mas não gera comissão. A taxa é **a mesma para todos os representantes** e
sai do parâmetro `AGRO_TAXA_RECEBIDO` (Comissões › Parâmetros), para poder ser mudada
sem deploy. O padrão é 5%.

Modelo validado contra o relatório manual do representante J.J. CRUZ (jul/2026), que
fechou ao centavo (R$ 149.919,00). Três regras saíram dessa conferência:

1. **O valor da linha é a PARCELA, não a nota**: `total do item / número de parcelas`.
   Mesma coisa para a quantidade. Era isso que explicava R$ 90.000 numa nota de
   R$ 180.000 com parcela 1/2.
2. **O período é a data do RECEBIMENTO da parcela**, não a da nota — por isso um
   relatório de julho lista notas de fevereiro a junho.
3. **Agrupamento**: representante da nota → cliente → parcelas.

O relatório manual conferido tinha dois erros de transcrição que aqui não acontecem:
quantidade da nota inteira onde devia ser a da parcela, e número de parcela trocado.

**Devoluções (05/10/2026).** No ERP a devolução não mexe no título: ela entra como
nota de entrada ligada ao ITEM da venda (`ITEMNOTAFISCALENTRADA.INFEINFNUM =
ITEMNOTAFISCAL.INFNUM`) e o financeiro baixa o título com um recebimento
`RECTIPO = 7`, na data e no valor da devolução — sem dinheiro entrando. Antes a
parcela contava como "recebida" por causa dessa baixa e a comissão saía sobre a
mercadoria devolvida (ex.: AGROFORTE, título 291282 em 02/10/2026: R$ 127.499,40
"recebidos", dos quais R$ 66.614,40 eram devolução). Agora:

- a baixa tipo 7 de nota que teve devolução não marca a parcela como recebida;
- o valor da parcela é o do item MENOS o que já tinha sido devolvido até a data do
  recebimento (até o fim do período, para parcela em aberto);
- devolução que chega DEPOIS de a parcela ter sido paga gera **estorno** da comissão
  daquela parte, no período da devolução (inclui o cliente que quita outro título
  com o crédito da devolução).

O tipo 7 sozinho não serve de filtro: ele também é usado em compensações sem
devolução (lote de desconto em folha, por exemplo). Por isso a exclusão vale só
para nota que tem devolução vinculada.

**Cancelamentos.** Nota cancelada (`NFSIT = 2`) não tem título no ERP e o número não
é reaproveitado, então nunca gerou parcela aqui. Elas aparecem listadas por
representante, só como informação.
"""
import datetime as dt

import pandas as pd
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ParametroComissao
from .views import engine

# Grupos de almoxarifado do agronegócio — mesma lista de views.calculos_comissoes.
GRUPOS_ALMOX_AGRO = (1974, 1587, 1828)

# Chave do parâmetro com a taxa única de comissão sobre o recebido, e o padrão
# se ela não estiver cadastrada. Guardada como fração (0.05 = 5%), igual às outras.
PARAM_TAXA = 'AGRO_TAXA_RECEBIDO'
TAXA_PADRAO = 0.05


def _taxa_comissao() -> float:
    """Taxa em % (5.0 = 5%). Vem do parâmetro ativo; cai no padrão se não existir."""
    try:
        pc = ParametroComissao.objects.filter(chave=PARAM_TAXA, ativo=True).first()
        fracao = float(pc.taxa) if pc else TAXA_PADRAO
    except Exception:
        fracao = TAXA_PADRAO
    return round(fracao * 100, 4)


# Recebimento que conta como dinheiro: tudo, menos a baixa por devolução (tipo 7)
# em nota que teve devolução vinculada. `{rec}` é o alias da tabela RECEBIMENTO.
def _rec_valido(rec: str) -> str:
    return f"""NOT ({rec}.RECTIPO = 7 AND EXISTS (
            SELECT 1 FROM ITEMNOTAFISCAL IDV
            JOIN ITEMNOTAFISCALENTRADA EDV ON EDV.INFEINFNUM = IDV.INFNUM
            WHERE IDV.INFNFCOD = NF.NFCOD))"""


def _sql(data_inicio: str, data_fim: str) -> str:
    grupos = ','.join(str(g) for g in GRUPOS_ALMOX_AGRO)
    return f"""
    SELECT
        R.REPNOME                            AS REPRESENTANTE,
        M.REPNOME                            AS MASTER,
        CLI.CLICOD                           AS CLIENTE_CODIGO,
        CLI.CLINOME                          AS CLIENTE_NOME,
        NF.NFNUM                             AS NOTA_FISCAL,
        INFNUM                               AS ITEM,
        CAST(NF.NFDATA AS DATE)              AS DATA_EMISSAO,
        ESTQNOME                             AS DESCRICAO,
        INFQUANT                             AS QUANT_NOTA,
        INFUNIT                              AS UNITARIO,
        INFTOTAL                             AS TOTAL_NOTA,
        D.DUPNUM                             AS TITULO,
        D.DUPPARNUM                          AS PARCELA_NUM,
        D.DUPPARTOT                          AS PARCELA_TOT,
        CAST(CR.CRVENC AS DATE)              AS VENCIMENTO,
        -- Data do recebimento DENTRO da janela: é o que caracteriza "recebida no período".
        (SELECT MAX(CAST(REC.RECDATA AS DATE)) FROM ITEMRECEBIMENTO IR
            JOIN RECEBIMENTO REC ON REC.RECNUM = IR.IRECREC
            WHERE IR.IRECCR = CR.CRNUM
              AND CAST(REC.RECDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
              AND {_rec_valido('REC')})
                                             AS DATA_RECEBIMENTO,
        -- Total recebido do título em qualquer data: define se ainda está em aberto.
        COALESCE((SELECT SUM(IR.IRECVALOR) FROM ITEMRECEBIMENTO IR
            WHERE IR.IRECCR = CR.CRNUM), 0)  AS RECEBIDO_TITULO,
        CR.CRTOTAL                           AS TOTAL_TITULO
    FROM NOTAFISCAL NF
    JOIN CLIENTE CLI          ON CLICOD = NF.NFCLI
    JOIN ITEMNOTAFISCAL       ON INFNFCOD = NF.NFCOD
    JOIN ESTOQUE ESTQ         ON ESTQCOD = INFESTQ
    JOIN NATUREZAOPERACAO     ON NOPCOD = INFNOP
    JOIN GRUPOALMOXARIFADO    ON GALMCOD = ESTQGALM
    LEFT JOIN REPRESENTANTE R ON R.REPCOD = NF.NFREP
    LEFT JOIN REPRESENTANTE M ON M.REPCOD = R.REPREPREF
    JOIN DUPLICATA D          ON D.DUPNFCOD = NF.NFCOD
    JOIN CONTARECEBER CR      ON CR.CRNUM = D.DUPNUM
    WHERE NF.NFSIT = 1
      AND GALMPRODVENDA = 'S'
      AND (SUBSTRING(NOPFLAGNF,1,1) = 'S' AND SUBSTRING(NOPFLAGNF,25,1) = 'N')
      AND NF.NFSNF NOT IN (8)
      AND ESTQGALM IN ({grupos})
      AND (
            EXISTS (SELECT 1 FROM ITEMRECEBIMENTO IR2
                    JOIN RECEBIMENTO REC2 ON REC2.RECNUM = IR2.IRECREC
                    WHERE IR2.IRECCR = CR.CRNUM
                      AND CAST(REC2.RECDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
                      AND {_rec_valido('REC2')})
            OR CAST(CR.CRVENC AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
      )
    """


def _devolucoes_dos_itens(itens) -> pd.DataFrame:
    """Todas as devoluções (qualquer data) dos itens de venda listados."""
    itens = sorted({int(i) for i in itens if pd.notna(i)})
    partes = []
    for i in range(0, len(itens), 900):
        lote = ','.join(str(x) for x in itens[i:i + 900])
        partes.append(pd.read_sql(f"""
            SELECT INFE.INFEINFNUM AS ITEM, CAST(NFE.NFEDATA AS DATE) AS DATA_DEVOLUCAO,
                   INFE.INFETOTAL AS VALOR_DEVOLVIDO, INFE.INFEQUANT AS QUANT_DEVOLVIDA
            FROM ITEMNOTAFISCALENTRADA INFE
            JOIN NOTAFISCALENTRADA NFE ON NFE.NFECOD = INFE.INFENFE
            WHERE INFE.INFEINFNUM IN ({lote})
        """, engine))
    if not partes:
        return pd.DataFrame(columns=['ITEM', 'DATA_DEVOLUCAO', 'VALOR_DEVOLVIDO', 'QUANT_DEVOLVIDA'])
    dev = pd.concat(partes, ignore_index=True)
    dev['DATA_DEVOLUCAO'] = pd.to_datetime(dev['DATA_DEVOLUCAO']).dt.date
    return dev


def _sql_devolucoes_periodo(data_inicio: str, data_fim: str) -> str:
    """Devoluções do período, com quantas parcelas da venda já tinham sido pagas antes delas."""
    grupos = ','.join(str(g) for g in GRUPOS_ALMOX_AGRO)
    return f"""
    SELECT
        R.REPNOME                            AS REPRESENTANTE,
        CLI.CLICOD                           AS CLIENTE_CODIGO,
        CLI.CLINOME                          AS CLIENTE_NOME,
        NF.NFNUM                             AS NOTA_FISCAL,
        CAST(NF.NFDATA AS DATE)              AS DATA_EMISSAO,
        NFE.NFENUMNF                         AS NOTA_DEVOLUCAO,
        CAST(NFE.NFEDATA AS DATE)            AS DATA_DEVOLUCAO,
        ESTQNOME                             AS DESCRICAO,
        INFE.INFEQUANT                       AS QUANT_DEVOLVIDA,
        INFE.INFETOTAL                       AS VALOR_DEVOLVIDO,
        (SELECT COUNT(*) FROM DUPLICATA DX WHERE DX.DUPNFCOD = NF.NFCOD) AS PARCELAS,
        (SELECT COUNT(*) FROM DUPLICATA DX WHERE DX.DUPNFCOD = NF.NFCOD AND EXISTS (
            SELECT 1 FROM ITEMRECEBIMENTO IRX JOIN RECEBIMENTO RX ON RX.RECNUM = IRX.IRECREC
            WHERE IRX.IRECCR = DX.DUPNUM AND RX.RECTIPO <> 7
              AND CAST(RX.RECDATA AS DATE) < CAST(NFE.NFEDATA AS DATE)))
                                             AS PARCELAS_PAGAS_ANTES
    FROM ITEMNOTAFISCALENTRADA INFE
    JOIN NOTAFISCALENTRADA NFE ON NFE.NFECOD = INFE.INFENFE
    JOIN ITEMNOTAFISCAL INF    ON INF.INFNUM = INFE.INFEINFNUM
    JOIN NOTAFISCAL NF         ON NF.NFCOD = INF.INFNFCOD
    JOIN CLIENTE CLI           ON CLI.CLICOD = NF.NFCLI
    JOIN ESTOQUE ESTQ          ON ESTQCOD = INF.INFESTQ
    LEFT JOIN REPRESENTANTE R  ON R.REPCOD = NF.NFREP
    WHERE NF.NFSIT = 1
      AND ESTQGALM IN ({grupos})
      AND CAST(NFE.NFEDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
    """


def _sql_canceladas(data_inicio: str, data_fim: str) -> str:
    grupos = ','.join(str(g) for g in GRUPOS_ALMOX_AGRO)
    return f"""
    SELECT R.REPNOME AS REPRESENTANTE, CLI.CLICOD AS CLIENTE_CODIGO, CLI.CLINOME AS CLIENTE_NOME,
           NF.NFNUM AS NOTA_FISCAL, CAST(NF.NFDATA AS DATE) AS DATA_EMISSAO, SUM(INF.INFTOTAL) AS VALOR
    FROM NOTAFISCAL NF
    JOIN CLIENTE CLI          ON CLI.CLICOD = NF.NFCLI
    JOIN ITEMNOTAFISCAL INF   ON INF.INFNFCOD = NF.NFCOD
    JOIN ESTOQUE ESTQ         ON ESTQCOD = INF.INFESTQ
    LEFT JOIN REPRESENTANTE R ON R.REPCOD = NF.NFREP
    WHERE NF.NFSIT = 2
      AND ESTQGALM IN ({grupos})
      AND CAST(NF.NFDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
    GROUP BY R.REPNOME, CLI.CLICOD, CLI.CLINOME, NF.NFNUM, CAST(NF.NFDATA AS DATE)
    """


def _nome_rep(serie: pd.Series) -> pd.Series:
    nomes = serie.fillna('').str.strip().str.upper()
    return nomes.where(nomes != '', '(SEM REPRESENTANTE)')


def _data_br(valor) -> str:
    if valor is None or pd.isna(valor):
        return ''
    if isinstance(valor, str):
        return valor
    return valor.strftime('%d/%m/%Y')


# Comissão por representante: só Admin, Master e vendasAgro (05/10/2026). Antes não
# exigia nem login — o DEFAULT_PERMISSION_CLASSES do projeto está vazio.
GRUPOS_RELATORIO = ('Admin', 'Master', 'vendasAgro')


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def relatorio_vendas_parcelas(request):
    user = request.user
    if not (user.is_superuser or user.groups.filter(name__in=GRUPOS_RELATORIO).exists()):
        return Response({'detail': 'Acesso restrito a Admin, Master e vendasAgro.'}, status=403)
    data_inicio = request.data.get('dataInicio')
    data_fim = request.data.get('dataFim')
    if not data_inicio or not data_fim:
        return Response({'erro': 'Informe dataInicio e dataFim (AAAA-MM-DD).'}, status=400)

    filtro_rep = (request.data.get('representante') or '').strip().upper()
    # 'recebidas' (padrão) | 'abertas' | 'todas'
    situacao = (request.data.get('situacao') or 'todas').lower()

    df = pd.read_sql(_sql(data_inicio, data_fim), engine)
    df_dev_periodo = pd.read_sql(_sql_devolucoes_periodo(data_inicio, data_fim), engine)
    df_canc = pd.read_sql(_sql_canceladas(data_inicio, data_fim), engine)
    taxa = _taxa_comissao()

    if not len(df) and not len(df_dev_periodo) and not len(df_canc):
        return Response({
            'dataInicio': data_inicio, 'dataFim': data_fim,
            'representantes': [], 'taxa': taxa, 'totais': _totais_vazios(),
        })

    df['REPRESENTANTE'] = df['REPRESENTANTE'].fillna('').str.strip().str.upper()
    df['MASTER'] = df['MASTER'].fillna('').str.strip().str.upper()
    df.loc[df['REPRESENTANTE'] == '', 'REPRESENTANTE'] = '(SEM REPRESENTANTE)'
    df['CLIENTE_NOME'] = df['CLIENTE_NOME'].fillna('').str.strip()
    df['DESCRICAO'] = df['DESCRICAO'].fillna('').str.strip()

    # PARCELA_TOT = 0 aparece em título sem parcelamento; tratar como 1 evita divisão por zero
    # e mantém o valor cheio na linha, que é o comportamento correto.
    partot = df['PARCELA_TOT'].fillna(1).replace(0, 1)
    df['PARCELA_TOT_EXIB'] = partot.astype(int)
    df['PARCELA_NUM_EXIB'] = df['PARCELA_NUM'].fillna(1).replace(0, 1).astype(int)
    df['RECEBIDA'] = df['DATA_RECEBIMENTO'].notna()

    # Devolvido do item até a data que vale para a parcela: a do recebimento (o que foi
    # pago já era líquido da devolução) ou o fim do período, se a parcela está em aberto.
    # Devolução depois do pagamento não entra aqui: vira estorno no período dela.
    fim_periodo = dt.date.fromisoformat(data_fim)
    data_ref = pd.to_datetime(df['DATA_RECEBIMENTO'], errors='coerce').dt.date
    data_ref = data_ref.where(df['RECEBIDA'], fim_periodo)
    df['DEVOLVIDO'] = 0.0
    df['QUANT_DEVOLVIDA_NOTA'] = 0.0
    dev_itens = _devolucoes_dos_itens(df['ITEM']) if len(df) else None
    if dev_itens is not None and len(dev_itens):
        por_item = dev_itens.groupby('ITEM')
        valores, quants = [], []
        for item, ref in zip(df['ITEM'], data_ref):
            if item in por_item.groups:
                g = por_item.get_group(item)
                g = g[g['DATA_DEVOLUCAO'] <= ref]
                valores.append(float(g['VALOR_DEVOLVIDO'].sum()))
                quants.append(float(g['QUANT_DEVOLVIDA'].sum()))
            else:
                valores.append(0.0)
                quants.append(0.0)
        df['DEVOLVIDO'] = valores
        df['QUANT_DEVOLVIDA_NOTA'] = quants
    df['VALOR'] = ((df['TOTAL_NOTA'] - df['DEVOLVIDO']).clip(lower=0) / partot).round(2)
    df['QUANTIDADE'] = ((df['QUANT_NOTA'] - df['QUANT_DEVOLVIDA_NOTA']).clip(lower=0) / partot).round(2)
    df['DEVOLVIDO_PARCELA'] = (df['DEVOLVIDO'] / partot).round(2)
    # Item devolvido por inteiro: a parcela não tem mais o que receber nem o que comissionar.
    df = df[df['VALOR'] > 0.004].copy()
    # Em aberto: não recebida na janela E título ainda não liquidado.
    df['EM_ABERTO'] = (~df['RECEBIDA']) & (df['RECEBIDO_TITULO'] < df['TOTAL_TITULO'] - 0.01)

    hoje = dt.date.today()
    venc = pd.to_datetime(df['VENCIMENTO'], errors='coerce').dt.date
    df['VENCIDA'] = df['EM_ABERTO'] & venc.notna() & (venc < hoje)

    # Estorno: devolução do período sobre parcela que já tinha sido paga antes dela.
    if len(df_dev_periodo):
        df_dev_periodo['REPRESENTANTE'] = _nome_rep(df_dev_periodo['REPRESENTANTE'])
        parcelas = df_dev_periodo['PARCELAS'].fillna(1).replace(0, 1)
        df_dev_periodo['BASE_ESTORNO'] = (
            df_dev_periodo['VALOR_DEVOLVIDO'] * df_dev_periodo['PARCELAS_PAGAS_ANTES'].fillna(0) / parcelas
        ).round(2)
    if len(df_canc):
        df_canc['REPRESENTANTE'] = _nome_rep(df_canc['REPRESENTANTE'])

    if filtro_rep:
        df = df[df['REPRESENTANTE'] == filtro_rep]
        if len(df_dev_periodo):
            df_dev_periodo = df_dev_periodo[df_dev_periodo['REPRESENTANTE'] == filtro_rep]
        if len(df_canc):
            df_canc = df_canc[df_canc['REPRESENTANTE'] == filtro_rep]
    if situacao == 'recebidas':
        df = df[df['RECEBIDA']]
    elif situacao == 'abertas':
        df = df[df['EM_ABERTO']]
    else:
        # 'todas' ainda descarta parcela que não é nem recebida na janela nem em aberto
        # (título já liquidado fora do período) — ela não pertence a este relatório.
        df = df[df['RECEBIDA'] | df['EM_ABERTO']]

    nomes = set(df['REPRESENTANTE']) if len(df) else set()
    if len(df_dev_periodo):
        nomes |= set(df_dev_periodo['REPRESENTANTE'])
    if len(df_canc):
        nomes |= set(df_canc['REPRESENTANTE'])
    vazio = df.iloc[0:0]

    representantes = []
    for nome_rep in sorted(nomes):
        df_rep = df[df['REPRESENTANTE'] == nome_rep] if len(df) else vazio
        masters = sorted({m for m in df_rep['MASTER'] if m})
        clientes = []
        for (cod, nome_cli), df_cli in df_rep.groupby(['CLIENTE_CODIGO', 'CLIENTE_NOME'], sort=True):
            recebidas, abertas = [], []
            ordenado = df_cli.sort_values(['DATA_EMISSAO', 'NOTA_FISCAL', 'PARCELA_NUM_EXIB'])
            for _, r in ordenado.iterrows():
                linha = {
                    'parcela': f"{r['PARCELA_NUM_EXIB']}/{r['PARCELA_TOT_EXIB']}",
                    'nota_fiscal': int(r['NOTA_FISCAL']),
                    'data_emissao': _data_br(r['DATA_EMISSAO']),
                    'descricao': r['DESCRICAO'],
                    'quantidade': float(r['QUANTIDADE']),
                    'unitario': round(float(r['UNITARIO'] or 0), 2),
                    'valor': float(r['VALOR']),
                    # Parte da parcela que o cliente devolveu (já descontada de `valor`).
                    'devolvido': float(r['DEVOLVIDO_PARCELA']),
                    'vencimento': _data_br(r['VENCIMENTO']),
                    'titulo': int(r['TITULO']),
                }
                if r['RECEBIDA']:
                    linha['data_recebimento'] = _data_br(r['DATA_RECEBIMENTO'])
                    recebidas.append(linha)
                else:
                    linha['vencida'] = bool(r['VENCIDA'])
                    abertas.append(linha)
            clientes.append({
                'codigo': int(cod) if pd.notna(cod) else None,
                'nome': nome_cli,
                'recebidas': recebidas,
                'abertas': abertas,
                'total_recebido': round(sum(l['valor'] for l in recebidas), 2),
                'total_aberto': round(sum(l['valor'] for l in abertas), 2),
            })
        clientes.sort(key=lambda c: c['total_recebido'], reverse=True)

        rec = df_rep[df_rep['RECEBIDA']]
        ab = df_rep[df_rep['EM_ABERTO']]
        total_recebido = round(float(rec['VALOR'].sum()), 2)

        comissao_recebido = round(total_recebido * taxa / 100.0, 2)

        devolucoes = []
        dev_rep = df_dev_periodo[df_dev_periodo['REPRESENTANTE'] == nome_rep] if len(df_dev_periodo) else []
        for _, d in (dev_rep.iterrows() if len(dev_rep) else []):
            devolucoes.append({
                'cliente': (d['CLIENTE_NOME'] or '').strip(),
                'nota_fiscal': int(d['NOTA_FISCAL']),
                'data_emissao': _data_br(d['DATA_EMISSAO']),
                'nota_devolucao': int(d['NOTA_DEVOLUCAO']) if pd.notna(d['NOTA_DEVOLUCAO']) else None,
                'data_devolucao': _data_br(d['DATA_DEVOLUCAO']),
                'descricao': (d['DESCRICAO'] or '').strip(),
                'quantidade': round(float(d['QUANT_DEVOLVIDA'] or 0), 2),
                'valor': round(float(d['VALOR_DEVOLVIDO'] or 0), 2),
                'parcelas_pagas_antes': int(d['PARCELAS_PAGAS_ANTES'] or 0),
                'parcelas': int(d['PARCELAS'] or 0),
                'base_estorno': float(d['BASE_ESTORNO']),
                'estorno': round(float(d['BASE_ESTORNO']) * taxa / 100.0, 2),
            })
        estorno = round(sum(x['estorno'] for x in devolucoes), 2)

        canceladas = []
        canc_rep = df_canc[df_canc['REPRESENTANTE'] == nome_rep] if len(df_canc) else []
        for _, c in (canc_rep.iterrows() if len(canc_rep) else []):
            canceladas.append({
                'cliente': (c['CLIENTE_NOME'] or '').strip(),
                'nota_fiscal': int(c['NOTA_FISCAL']),
                'data_emissao': _data_br(c['DATA_EMISSAO']),
                'valor': round(float(c['VALOR'] or 0), 2),
            })

        representantes.append({
            'representante': nome_rep,
            'master': ' / '.join(masters),
            'clientes': clientes,
            'taxa': taxa,
            # Líquida: sobre o recebido, menos o estorno das devoluções do período.
            'comissao': round(comissao_recebido - estorno, 2),
            'comissao_recebido': comissao_recebido,
            'estorno_devolucao': estorno,
            'devolucoes': devolucoes,
            'total_devolvido': round(sum(x['valor'] for x in devolucoes), 2),
            'canceladas': canceladas,
            'total_cancelado': round(sum(x['valor'] for x in canceladas), 2),
            'total_recebido': total_recebido,
            'total_aberto': round(float(ab['VALOR'].sum()), 2),
            'total_vencido': round(float(df_rep[df_rep['VENCIDA']]['VALOR'].sum()), 2),
            'qtd_clientes': int(df_rep['CLIENTE_CODIGO'].nunique()),
            'qtd_notas': int(df_rep['NOTA_FISCAL'].nunique()),
            'qtd_parcelas_recebidas': int(len(rec)),
            'qtd_parcelas_abertas': int(len(ab)),
        })

    representantes.sort(key=lambda r: r['total_recebido'], reverse=True)

    return Response({
        'dataInicio': data_inicio,
        'dataFim': data_fim,
        'situacao': situacao,
        'representantes': representantes,
        'taxa': taxa,
        'totais': {
            'comissao': round(sum(r['comissao'] for r in representantes), 2),
            'estorno_devolucao': round(sum(r['estorno_devolucao'] for r in representantes), 2),
            'devolvido': round(sum(r['total_devolvido'] for r in representantes), 2),
            'devolucoes': sum(len(r['devolucoes']) for r in representantes),
            'cancelado': round(sum(r['total_cancelado'] for r in representantes), 2),
            'canceladas': sum(len(r['canceladas']) for r in representantes),
            'recebido': round(sum(r['total_recebido'] for r in representantes), 2),
            'aberto': round(sum(r['total_aberto'] for r in representantes), 2),
            'vencido': round(sum(r['total_vencido'] for r in representantes), 2),
            'representantes': len(representantes),
            'clientes': int(df['CLIENTE_CODIGO'].nunique()) if len(df) else 0,
            'notas': int(df['NOTA_FISCAL'].nunique()) if len(df) else 0,
            'parcelas_recebidas': int(df['RECEBIDA'].sum()) if len(df) else 0,
            'parcelas_abertas': int(df['EM_ABERTO'].sum()) if len(df) else 0,
        },
    })


def _totais_vazios():
    return {
        'comissao': 0.0, 'recebido': 0.0, 'aberto': 0.0, 'vencido': 0.0, 'representantes': 0,
        'estorno_devolucao': 0.0, 'devolvido': 0.0, 'devolucoes': 0, 'cancelado': 0.0, 'canceladas': 0,
        'clientes': 0, 'notas': 0, 'parcelas_recebidas': 0, 'parcelas_abertas': 0,
    }
