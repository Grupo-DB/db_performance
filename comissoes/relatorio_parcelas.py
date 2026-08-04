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
"""
import datetime as dt

import pandas as pd
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
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


def _sql(data_inicio: str, data_fim: str) -> str:
    grupos = ','.join(str(g) for g in GRUPOS_ALMOX_AGRO)
    return f"""
    SELECT
        R.REPNOME                            AS REPRESENTANTE,
        M.REPNOME                            AS MASTER,
        CLI.CLICOD                           AS CLIENTE_CODIGO,
        CLI.CLINOME                          AS CLIENTE_NOME,
        NF.NFNUM                             AS NOTA_FISCAL,
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
              AND CAST(REC.RECDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}')
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
                      AND CAST(REC2.RECDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}')
            OR CAST(CR.CRVENC AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
      )
    """


def _data_br(valor) -> str:
    if valor is None or pd.isna(valor):
        return ''
    if isinstance(valor, str):
        return valor
    return valor.strftime('%d/%m/%Y')


@csrf_exempt
@api_view(['POST'])
def relatorio_vendas_parcelas(request):
    data_inicio = request.data.get('dataInicio')
    data_fim = request.data.get('dataFim')
    if not data_inicio or not data_fim:
        return Response({'erro': 'Informe dataInicio e dataFim (AAAA-MM-DD).'}, status=400)

    filtro_rep = (request.data.get('representante') or '').strip().upper()
    # 'recebidas' (padrão) | 'abertas' | 'todas'
    situacao = (request.data.get('situacao') or 'todas').lower()

    df = pd.read_sql(_sql(data_inicio, data_fim), engine)

    if not len(df):
        return Response({
            'dataInicio': data_inicio, 'dataFim': data_fim,
            'representantes': [], 'taxa': _taxa_comissao(), 'totais': _totais_vazios(),
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
    df['VALOR'] = (df['TOTAL_NOTA'] / partot).round(2)
    df['QUANTIDADE'] = (df['QUANT_NOTA'] / partot).round(2)

    df['RECEBIDA'] = df['DATA_RECEBIMENTO'].notna()
    # Em aberto: não recebida na janela E título ainda não liquidado.
    df['EM_ABERTO'] = (~df['RECEBIDA']) & (df['RECEBIDO_TITULO'] < df['TOTAL_TITULO'] - 0.01)

    hoje = dt.date.today()
    venc = pd.to_datetime(df['VENCIMENTO'], errors='coerce').dt.date
    df['VENCIDA'] = df['EM_ABERTO'] & venc.notna() & (venc < hoje)

    if filtro_rep:
        df = df[df['REPRESENTANTE'] == filtro_rep]
    if situacao == 'recebidas':
        df = df[df['RECEBIDA']]
    elif situacao == 'abertas':
        df = df[df['EM_ABERTO']]
    else:
        # 'todas' ainda descarta parcela que não é nem recebida na janela nem em aberto
        # (título já liquidado fora do período) — ela não pertence a este relatório.
        df = df[df['RECEBIDA'] | df['EM_ABERTO']]

    taxa = _taxa_comissao()

    representantes = []
    for nome_rep, df_rep in df.groupby('REPRESENTANTE', sort=True):
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

        comissao = round(total_recebido * taxa / 100.0, 2)

        representantes.append({
            'representante': nome_rep,
            'master': ' / '.join(masters),
            'clientes': clientes,
            'taxa': taxa,
            'comissao': comissao,
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
        'clientes': 0, 'notas': 0, 'parcelas_recebidas': 0, 'parcelas_abertas': 0,
    }
