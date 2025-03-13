from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
from sqlalchemy import create_engine
from baseOrcamentaria.orcamento.models import CentroCusto,CentroCustoPai
import pandas as pd
import locale
import datetime

locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')

# String de conexão
connection_string = 'mssql+pyodbc://DBCONSULTA:DB%40%402023**@172.50.10.5/DB?driver=ODBC+Driver+17+for+SQL+Server'
# Cria a engine
engine = create_engine(connection_string)


@csrf_exempt
@api_view(['POST'])
def calculos_realizados_grupo_itens(request):
    cc_list = request.data.get('ccs', [])
    grupo_itens_list = request.data.get('grupo_itens', [])
    filiais_list = request.data.get('filiais', [])
    ano = request.data.get('ano', None)
    conta1 = '3401%'
    conta2 = '3402%' 
    conta = '4%'

    # Validar filiais
    if isinstance(filiais_list, list):
        try:
            filiais_list = [int(filial) for filial in filiais_list if str(filial).isdigit()]
        except ValueError:
            raise ValueError('A lista de filiais contém valores não numéricos.')
    else:
        raise ValueError("O parâmetro 'filiais' deve ser uma lista.")

    if not filiais_list:
        raise ValueError('A lista de filiais está vazia, ou contém valores inválidos.')

    # Validação de cc_list
    if isinstance(cc_list, list):
        try:
            cc_list = [int(cc) for cc in cc_list if str(cc).isdigit()]
        except ValueError:
            raise ValueError("A lista de 'ccs' contém valores não numéricos.")
    else:
        raise ValueError("O parâmetro 'ccs' deve ser uma lista.")    
    
    # Validar grupo_itens
    if isinstance(grupo_itens_list, list):
        try:
            grupo_itens_list = [str(grupo_item).zfill(9) for grupo_item in grupo_itens_list if str(grupo_item).isdigit()]
        except ValueError:
            raise ValueError('A lista de grupo_itens contém valores não numéricos.')
    else:
        raise ValueError("O parâmetro 'grupo_itens' deve ser uma lista.")
    
    # Conversão de listas para strings no formato esperado pelo SQL
    filiais_string = ', '.join(map(str, filiais_list))
    grupo_itens_string = ', '.join(map(str, grupo_itens_list))
    cc_string = ", ".join(map(str, cc_list))

     # Constrói cláusula dinâmica para filtro 'CCSTCOD'
    if cc_list:
        cc_conditions = " OR ".join([f"CCSTCOD LIKE '%{cc}%'" for cc in cc_list])
    else:
        cc_conditions = "1=1"  # Condição neutra se 'cc_list' não for fornecida

    # Gera o intervalo de datas com base no ano
    if ano:
        data_inicio = f"{ano}-01-01"
        data_fim = datetime.date.today().strftime("%Y-%m-%d")
    else:
        raise ValueError("O parâmetro 'ano' é obrigatório.")
    
    consulta_realizado = pd.read_sql(f"""        
        WITH LANCAMENTOS_BASE AS (
            SELECT 
                LC.LANCCOD, 
                LC.LANCDATA, 
                '''' + LC.LANCDEB AS CONTA_DEB, 
                (SELECT PCNOME FROM PLANO WHERE PCCONTA = LC.LANCDEB) AS CONTA_NOME_DEB,
                '''' + LC.LANCCRED AS CONTA_CRED, 
                (SELECT PCNOME FROM PLANO WHERE PCCONTA = LC.LANCCRED) AS CONTA_NOME_CRED,
                CCNOMECOMP,
                CCSTCOD,
                LC.LANCVALOR,
                LC.LANCHIST,
                LC.LANCCOMP,
                LC.LANCTIPOREF,
                LC.LANCREF,
                LC.LANCSIT,
                LC.LANCFIL,
                LC.LANCEMP,
                ESTQNOME AS ITEM,
                BEST.BESTQUANT AS QTD
            FROM LANCAMENTO LC
            LEFT OUTER JOIN CENTROCUSTO ON CCCOD = LC.LANCCC
            LEFT OUTER JOIN BAIXAESTOQUE BEST ON BEST.BESTCOD = LC.LANCREF
                                            AND BEST.BESTEMP = LC.LANCEMP 
                                            AND BEST.BESTFIL = LC.LANCFIL
                                            AND LC.LANCTIPOREF = 13
                                            AND LC.LANCSIT = 0      
            LEFT OUTER JOIN ESTOQUE ESTQ ON ESTQ.ESTQCOD = BEST.BESTESTQ
            WHERE 
                CAST(LC.LANCDATA AS DATE) BETWEEN '{data_inicio}' AND '{data_fim}'
                AND LC.LANCEMP = 1
                AND LC.LANCFIL IN ({filiais_string})
                AND LANCSIT = 0
                AND ({cc_conditions})
                AND (
                    LC.LANCCRED LIKE '{conta}'
                    OR LC.LANCCRED LIKE '{conta1}'
                    OR LC.LANCCRED LIKE '{conta2}'
                    OR LC.LANCDEB LIKE '{conta}'
                    OR LC.LANCDEB LIKE '{conta1}'
                    OR LC.LANCDEB LIKE '{conta2}'
                )
        )

        SELECT 
            LANCCOD, 
            LANCDATA, 
            CONTA_DEB, 
            CONTA_NOME_DEB, 
            CONTA_CRED, 
            CONTA_NOME_CRED,
            CCNOMECOMP,
            CCSTCOD, 
            LANCVALOR AS DEB_VALOR, 
            0.00 AS CRED_VALOR, 
            'AUT' AS TIPO,
            CASE 
                WHEN LANCTIPOREF = 14 THEN 
                    (SELECT TREGNOME 
                    FROM TIPOREGISTRO
                    JOIN REGISTRO ON REGTREG = TREGCOD
                    WHERE REGCOD = LANCREF)
                ELSE 
                    (SELECT REFNOME FROM REFERENCIA WHERE REFCOD = LANCTIPOREF)
            END AS REFERENCIA, 
            LANCREF,
            (SELECT HISTMASCARA FROM HISTORICO WHERE HISTCOD = LANCHIST) + ' ' + LANCCOMP AS HISTORICO,
            CASE 
                WHEN LANCSIT = 0 THEN 'ATIVO' 
                WHEN LANCSIT = 1 THEN 'CANCELADO' 
                ELSE '?????' 
            END AS SITUACAO,
            CASE 
                WHEN LANCFIL = 0 THEN (SELECT EMPSIGLA FROM EMPRESA WHERE EMPCOD = LANCEMP) 
                ELSE (SELECT FILSIGLA FROM FILIAL WHERE FILCOD = LANCFIL) 
            END AS UNIDADE,
            ITEM,
            QTD
        FROM LANCAMENTOS_BASE

        UNION

        SELECT 
            LANCCOD, 
            LANCDATA, 
            CONTA_DEB, 
            CONTA_NOME_DEB, 
            CONTA_CRED, 
            CONTA_NOME_CRED,
            CCNOMECOMP,
            CCSTCOD, 
            0.00 AS DEB_VALOR, 
            -LANCVALOR AS CRED_VALOR, 
            'AUT' AS TIPO,
            CASE 
                WHEN LANCTIPOREF = 14 THEN 
                    (SELECT TREGNOME 
                    FROM TIPOREGISTRO
                    JOIN REGISTRO ON REGTREG = TREGCOD
                    WHERE REGCOD = LANCREF)
                ELSE 
                    (SELECT REFNOME FROM REFERENCIA WHERE REFCOD = LANCTIPOREF)
            END AS REFERENCIA, 
            LANCREF,
            (SELECT HISTMASCARA FROM HISTORICO WHERE HISTCOD = LANCHIST) + ' ' + LANCCOMP AS HISTORICO,
            CASE 
                WHEN LANCSIT = 0 THEN 'ATIVO' 
                WHEN LANCSIT = 1 THEN 'CANCELADO' 
                ELSE '?????' 
            END AS SITUACAO,
            CASE 
                WHEN LANCFIL = 0 THEN (SELECT EMPSIGLA FROM EMPRESA WHERE EMPCOD = LANCEMP) 
                ELSE (SELECT FILSIGLA FROM FILIAL WHERE FILCOD = LANCFIL) 
            END AS UNIDADE,
            ITEM,
            QTD
        FROM LANCAMENTOS_BASE
                
    """, engine)
    
    # Regra para obtenção dos valores usados
    consulta_realizado['SALDO'] = consulta_realizado.apply(
        lambda row: row["DEB_VALOR"] if str(row["CONTA_DEB"])[1] in ['3', '4'] else row["CRED_VALOR"],
        axis=1
    )

    # Cria a coluna CONTA
    consulta_realizado['CONTA'] = consulta_realizado.apply(
        lambda row: row['CONTA_DEB'] if str(row['CONTA_DEB'])[1] in ['3', '4'] else row['CONTA_CRED'],
        axis=1
    )

    # Remove os apóstrofos da coluna CONTA
    consulta_realizado['CONTA'] = consulta_realizado['CONTA'].str.replace("'", "")

    # Cria a coluna DESCRICAO
    consulta_realizado['DESCRICAO'] = consulta_realizado.apply(
        lambda row: row['ITEM'] if pd.notnull(row['ITEM']) else row['HISTORICO'],
        axis=1
    )

    def format_locale(value):
        try:
            if not isinstance(value, (int, float)):
                value = float(value)  # Garante que seja numérico
            return locale.format_string("%.0f", value, grouping=True)
        except Exception as e:
            return str(value)  # Em caso de erro, retorna como string simples

    # Converte os valores de QTD para 0 quando for null
    consulta_realizado['QTD'] = consulta_realizado['QTD'].fillna(1)

    # Converte a data
    consulta_realizado['LANCDATA'] = pd.to_datetime(consulta_realizado['LANCDATA']).dt.strftime('%d/%m/%Y')

    # Extrai os últimos 9 dígitos da coluna CONTA
    consulta_realizado['CONTA_ULTIMOS_9'] = consulta_realizado['CONTA'].str[-9:]

    # Verifica se os últimos 9 dígitos foram extraídos corretamente
    print(consulta_realizado[['CONTA', 'CONTA_ULTIMOS_9']].head())

    # Filtra as linhas onde os últimos 9 dígitos estão em grupo_itens_list
    consulta_filtrada = consulta_realizado[consulta_realizado['CONTA_ULTIMOS_9'].isin(grupo_itens_list)]

    # Verifica se a filtragem foi feita corretamente
    print(consulta_filtrada[['CONTA', 'CONTA_ULTIMOS_9']].head())

    # Agrupa e soma os valores
    consulta_agrupada = consulta_filtrada.groupby('CONTA_ULTIMOS_9').agg({
        'SALDO': 'sum',
        'DEB_VALOR': 'sum',
        'CRED_VALOR': 'sum',
        'CCSTCOD': 'last',
        'QTD': 'sum'
    }).reset_index()

    if consulta_agrupada['SALDO'].empty or consulta_agrupada['SALDO'].sum() == 0:
        total = "0"  # Define como zero formatado
        total_formatado = "0"
        dados = consulta_agrupada.to_dict(orient='records')
    else:
        total = consulta_agrupada['SALDO'].sum()  # Soma os valores
        total_formatado = locale.format_string("%.0f", total, grouping=True)

###################################################################################################

    codigos_requisicao = request.data.get('ccs',[])

    # Função para extrair códigos da string
    def extrair_codigos(codigos):
        # Remove "+" e transforma em lista de códigos
        return codigos.strip('+').split('+')
    
    # Excluir os códigos 4700, 4701 e 4703
    codigos_requisicao = [codigo for codigo in codigos_requisicao if codigo not in ['4700', '4701', '4703']]

    consulta_ccs = CentroCusto.objects.filter(
        codigo__in=codigos_requisicao
    ).values('codigo', 'nome')

    # Converte o resultado da consulta para um dicionário
    mapa_codigos_nomes = {
        item['codigo']: item['nome'] for item in consulta_ccs
    }

    # Aplicar a função para criar uma lista de códigos em cada linha
    consulta_filtrada['CODIGOS_SEPARADOS'] = consulta_filtrada['CCSTCOD'].apply(extrair_codigos)

    # Explodir a lista de códigos em várias linhas, um código por linha
    df_explodido = consulta_filtrada.explode('CODIGOS_SEPARADOS')
    
    # Filtrar as linhas que contêm os códigos recebidos na requisição
    df_filtrado = df_explodido[df_explodido['CODIGOS_SEPARADOS'].isin(codigos_requisicao)]

    # Agrupar por código e somar os valores
    df_agrupado = df_filtrado.groupby('CODIGOS_SEPARADOS')['SALDO'].sum().to_dict()

    codigos = list(df_agrupado.keys())
    
    df_agrupado_nomes = {}
    df_agrupado_nomes_detalhes = {}

    # Substituir os códigos pelos nomes no agrupamento
    for codigo, saldo in df_agrupado.items():
        nome = mapa_codigos_nomes.get(codigo, codigo)
        if nome not in df_agrupado_nomes:
            df_agrupado_nomes[nome] = saldo
            df_agrupado_nomes_detalhes[nome] = []
        else:
            df_agrupado_nomes[nome] += saldo
    
        detalhes = consulta_filtrada[consulta_filtrada['CCSTCOD'].str.contains(codigo)]
        for _, row in detalhes.iterrows():
            if row['SALDO'] != 0:
                df_agrupado_nomes_detalhes[nome].append({
                    'conta': row['CONTA'],
                    'LANCCOD': row['LANCCOD'],
                    'LANCDATA': row['LANCDATA'],
                    'HISTORICO': row['HISTORICO'],
                    'SALDO': row['SALDO'],
                    'LANCREF': row['LANCREF'],
                    'SITUACAO': row['SITUACAO'],
                    'ITEM': row['ITEM'],
                    'QTD': row['QTD'],
                    'COD': row['CCSTCOD'],
                    'DESCRICAO': row['DESCRICAO'] 
                })

    # Formatar os valores finais (opcional)
    df_agrupado_nomes_formatado = {
        nome: format_locale(valor) for nome, valor in df_agrupado_nomes.items()
    }

    response_data = {
        'total': total_formatado,
        'dados': consulta_agrupada.to_dict(orient='records'),
        'df_agrupado': df_agrupado_nomes_formatado,
        'teste': df_agrupado_nomes,
        'df_agrupado_nomes_detalhes': df_agrupado_nomes_detalhes
    }

    return JsonResponse(response_data, safe=False)

