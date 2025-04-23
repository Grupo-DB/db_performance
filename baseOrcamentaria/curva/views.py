from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
from sqlalchemy import create_engine
from baseOrcamentaria.orcamento.models import ContaContabil,CentroCusto, GrupoItens
import pandas as pd
import locale
import datetime
locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')  # br

# String de conexão
connection_string = 'mssql+pyodbc://DBCONSULTA:DB%40%402023**@172.50.10.5/DB?driver=ODBC+Driver+17+for+SQL+Server'
# Cria a engine
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['POST'])
def calculos_curva(request):
    cc_list = list(CentroCusto.objects.values_list('codigo', flat=True))
    cc_list_str = [str(codigo) for codigo in cc_list]
    grupo_itens_list = list(GrupoItens.objects.values_list('codigo', flat=True))
    grupo_itens_list = [str(codigo) for codigo in grupo_itens_list]
    filiais_list = request.data.get('filial', [])
    ano = request.data.get('ano', None)
    conta1 = '3401%'
    conta2 = '3402%' 
    conta = '4%'
    meses = request.data.get('periodo', [])

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
    
    # Validação dos meses
    if not isinstance(meses, list) or not all(isinstance(mes, int) and 1 <= mes <= 12 for mes in meses):
        raise ValueError("O parâmetro 'meses' deve ser uma lista de inteiros entre 1 e 12.")
    
    # Conversão de listas para strings no formato esperado pelo SQL
    filiais_string = ', '.join(map(str, filiais_list))
    grupo_itens_string = ', '.join(map(str, grupo_itens_list))
    cc_string = ", ".join(map(str, cc_list))
    meses_string = ", ".join(map(str, meses))

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
    
    meses_condition = f"MONTH(LC.LANCDATA) IN ({meses_string})" if meses else "1=1"
    
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
                AND ({meses_condition})
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

    df = pd.DataFrame(consulta_realizado)
    
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

    # Pegando os últimos 9 caracteres da conta
    consulta_realizado['CONTA_ULTIMOS_9'] = consulta_realizado['CONTA'].str[-9:]

    # Mapeando os grupos de itens
    grupo_itens_map = {
        item['codigo']: {
            'nome_completo': item['nome_completo'],
            'gestor_nome': item.get('gestor__nome', 'Sem Gestor')  # Use .get para evitar KeyError
        }
        for item in GrupoItens.objects.values('codigo', 'nome_completo', 'gestor__nome')
    }

    # Mapeando o grupo de itens no DataFrame
    consulta_realizado['GRUPO_ITENS'] = consulta_realizado['CONTA_ULTIMOS_9'].map(
    lambda codigo: grupo_itens_map.get(codigo, {}).get('nome_completo', 'Gestor Indefinido')
)

    # Agrupando os dados
    consulta_agrupada = consulta_realizado.groupby(['GRUPO_ITENS', 'CONTA_ULTIMOS_9']).agg({
    'SALDO': 'sum'
}).reset_index()
        
    # Criando o dicionário com saldo e nome do gestor
    dicionario_soma_nomes = {}
    total_soma_nomes = 0
    for _, row in consulta_agrupada.iterrows():
        grupo = row['GRUPO_ITENS']
        saldo = row['SALDO']
        
        # Obter o nome do gestor a partir do mapeamento
        gestor_nome = grupo_itens_map.get(row['CONTA_ULTIMOS_9'], {}).get('gestor_nome', 'Sem Gestor')
        
        if grupo not in dicionario_soma_nomes:
            dicionario_soma_nomes[grupo] = {
                'saldo': 0,
                'gestor': gestor_nome
            }

        dicionario_soma_nomes[grupo]['saldo'] += saldo
        total_soma_nomes += saldo
    total_soma_nomes_formatado = format_locale(total_soma_nomes)

    df_grupos_nomes = {}
    


###################################################################################################

    codigos_requisicao = cc_list_str

    # Função para extrair códigos da string
    def extrair_codigos(codigos):
        # Remove "+" e transforma em lista de códigos
        return codigos.strip('+').split('+')
    
    # # Excluir os códigos 4700, 4701 e 4703
    # codigos_requisicao = [codigo for codigo in codigos_requisicao if codigo not in ['4700', '4701', '4703']]
    codigos_excluir = ['4700', '4701', '4703']

    # Verifica se '0' está presente em filiais_list
    if '0' not in filiais_list:
         # Exclui os códigos especificados de codigos_requisicao
        codigos_requisicao = [codigo for codigo in codigos_requisicao if codigo not in codigos_excluir]

    consulta_ccs = CentroCusto.objects.filter(
        codigo__in=codigos_requisicao
    ).values('codigo', 'nome')

    # Converte o resultado da consulta para um dicionário
    mapa_codigos_nomes = {
        item['codigo']: item['nome'] for item in consulta_ccs
    }

    # Aplicar a função para criar uma lista de códigos em cada linha
    consulta_realizado['CODIGOS_SEPARADOS'] = consulta_realizado['CCSTCOD'].apply(extrair_codigos)
    
    # Explodir a lista de códigos em várias linhas, um código por linha
    df_explodido = consulta_realizado.explode('CODIGOS_SEPARADOS')

    # Filtrar as linhas que contêm os códigos recebidos na requisição
    df_filtrado = df_explodido[df_explodido['CODIGOS_SEPARADOS'].isin(codigos_requisicao)]
    
    # Agrupar por código e somar os valores
    df_agrupado = df_filtrado.groupby('CODIGOS_SEPARADOS')['SALDO'].sum().to_dict()
    
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
    
        detalhes = consulta_realizado[consulta_realizado['CCSTCOD'].str.contains(codigo)]
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

   
    # Obter os códigos agrupados
    codigos_agrupados = list(df_agrupado.keys())

    # Certifique-se de que os códigos estão no formato correto (string)
    codigos_agrupados = [str(codigo) for codigo in codigos_agrupados]

    # Verifique os valores de codigos_agrupados
   

    # Consulta os centros de custo e seus pais com base nos códigos agrupados
    consulta_ccs_pais = CentroCusto.objects.filter(
        codigo__in=codigos_agrupados  # Substituí 'id' por 'codigo'
    ).values('codigo', 'nome', 'cc_pai__id', 'cc_pai__nome', 'gestor__nome')

    # Verifique os resultados da consulta
    

    # Cria um dicionário para mapear os códigos dos centros de custo para seus pais
    mapa_codigos_pais = {
        str(item['codigo']): {
            'cc_pai_id': str(item['cc_pai__id']) if item['cc_pai__id'] else None,
            'cc_pai_nome': item['cc_pai__nome'] or 'Sem Pai',
            'gestor_nome': item.get('gestor__nome', 'Sem Gestor')
        }
        for item in consulta_ccs_pais
    }

    df_agrupado_por_pai = {}
    total_geral = 0
    for codigo, saldo in df_agrupado.items():
        pai_info = mapa_codigos_pais.get(str(codigo), {'cc_pai_nome': 'Sem Pai', 'gestor_nome': 'Sem Gestor'})
        pai_nome = pai_info['cc_pai_nome']
        pai_gestor = pai_info['gestor_nome']
        if pai_nome not in df_agrupado_por_pai:
            df_agrupado_por_pai[pai_nome] = {
                'saldo': 0,
                'gestor': pai_gestor
            }
        df_agrupado_por_pai[pai_nome]['saldo'] += saldo 
        total_geral += saldo
    total_geral_formatado = format_locale(total_geral)

    df_agrupado_pais_detalhes = {}

    # Agrupar os valores por centro de custo pai e criar o detalhamento
    for codigo, saldo in df_agrupado.items():
        # Obter informações do pai a partir do mapeamento
        pai_info = mapa_codigos_pais.get(str(codigo), {'cc_pai_nome': 'Sem Pai'})
        pai_nome = pai_info['cc_pai_nome']

        # Inicializar o agrupamento e os detalhes para o pai, se necessário
        if pai_nome not in df_agrupado_pais_detalhes:
            df_agrupado_pais_detalhes[pai_nome] = {
                'saldo': 0,
                'detalhes': []
            }

        # Somar o saldo ao pai
        df_agrupado_pais_detalhes[pai_nome]['saldo'] += saldo

        # Adicionar os detalhes relacionados ao centro de custo ao pai
        detalhes = consulta_realizado[consulta_realizado['CCSTCOD'].str.contains(codigo)]
        for _, row in detalhes.iterrows():
            if row['SALDO'] != 0:
                df_agrupado_pais_detalhes[pai_nome]['detalhes'].append({
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
  

    # Formatar os valores finais (opcional)
    df_agrupado_por_pai_formatado = {
        pai: format_locale(valor) for pai, valor in df_agrupado_por_pai.items()
    }

    dicionario_soma_nomes_formatado = {
        nome: format_locale(saldo) for nome, saldo in dicionario_soma_nomes.items()
    }

    response_data = {
        #'total': total_formatado,
        #'dados': consulta_agrupada.to_dict(orient='records'),
        #'df_agrupado': df_agrupado_nomes_formatado,
        'agrupado_por_pai': df_agrupado_por_pai_formatado,
        #'teste': df_agrupado_nomes,
        #'df_agrupado_nomes_detalhes': df_agrupado_nomes_detalhes,
        #'df_agrupado_pais_detalhes': df_agrupado_pais_detalhes,
        'dicionario_soma_nomes': dicionario_soma_nomes_formatado,
        'total_soma_gps': total_soma_nomes,
        'total_soma_ccs': total_geral
    }

    return JsonResponse(response_data, safe=False)

#############################################################################

@csrf_exempt
@api_view(['POST'])
def meus_calculos_gp_curva(request):
    cc_list = list(CentroCusto.objects.values_list('codigo', flat=True))
    cc_list_str = [str(codigo) for codigo in cc_list]
    grupo_itens_list = request.data.get('grupos_itens', [])
    filiais_list = request.data.get('filial', [])
    ano = request.data.get('ano', None)
    conta1 = '3401%'
    conta2 = '3402%' 
    conta = '4%'
    meses = request.data.get('periodo', [])

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
    
    # Validação dos meses
    if not isinstance(meses, list) or not all(isinstance(mes, int) and 1 <= mes <= 12 for mes in meses):
        raise ValueError("O parâmetro 'meses' deve ser uma lista de inteiros entre 1 e 12.")
    
    # Conversão de listas para strings no formato esperado pelo SQL
    filiais_string = ', '.join(map(str, filiais_list))
    grupo_itens_list_str = ', '.join(map(str, grupo_itens_list))
    cc_string = ", ".join(map(str, cc_list))
    meses_string = ", ".join(map(str, meses))

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
    
    meses_condition = f"MONTH(LC.LANCDATA) IN ({meses_string})" if meses else "1=1"
    
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
                AND ({meses_condition})
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

    df = pd.DataFrame(consulta_realizado)
    
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

    # Pegando os últimos 9 caracteres da conta
    consulta_realizado['CONTA_ULTIMOS_9'] = consulta_realizado['CONTA'].str[-9:]

    # Mapeando os grupos de itens
    grupo_itens_map = {
        item['codigo']: {
            'nome_completo': item['nome_completo'],
            'gestor_nome': item.get('gestor__nome', 'Sem Gestor')  # Use .get para evitar KeyError
        }
        for item in GrupoItens.objects.values('codigo', 'nome_completo', 'gestor__nome')
    }

    # Mapeando o grupo de itens no DataFrame
    consulta_realizado['GRUPO_ITENS'] = consulta_realizado['CONTA_ULTIMOS_9'].map(
    lambda codigo: grupo_itens_map.get(codigo, {}).get('nome_completo', 'Gestor Indefinido')
)

    # Filtra o DataFrame com base nos grupos de itens fornecidos
    if grupo_itens_list:
        consulta_realizado = consulta_realizado[consulta_realizado['CONTA_ULTIMOS_9'].isin(grupo_itens_list)]

    # Agrupando os dados
    consulta_agrupada = consulta_realizado.groupby(['GRUPO_ITENS', 'CONTA_ULTIMOS_9']).agg({
    'SALDO': 'sum'
}).reset_index()
        
    # Criando o dicionário com saldo e nome do gestor
    dicionario_soma_nomes = {}
    total_soma_nomes = 0
    for _, row in consulta_agrupada.iterrows():
        grupo = row['GRUPO_ITENS']
        saldo = row['SALDO']
        
        # Obter o nome do gestor a partir do mapeamento
        gestor_nome = grupo_itens_map.get(row['CONTA_ULTIMOS_9'], {}).get('gestor_nome', 'Sem Gestor')
        
        if grupo not in dicionario_soma_nomes:
            dicionario_soma_nomes[grupo] = {
                'saldo': 0,
                'gestor': gestor_nome
            }

        dicionario_soma_nomes[grupo]['saldo'] += saldo
        total_soma_nomes += saldo
    total_soma_nomes_formatado = format_locale(total_soma_nomes)

    df_grupos_nomes = {}
    


###################################################################################################

    codigos_requisicao = cc_list_str

    # Função para extrair códigos da string
    def extrair_codigos(codigos):
        # Remove "+" e transforma em lista de códigos
        return codigos.strip('+').split('+')
    
    # # Excluir os códigos 4700, 4701 e 4703
    codigos_requisicao = [codigo for codigo in codigos_requisicao if codigo not in ['4700', '4701', '4703']]
    codigos_excluir = ['4700', '4701', '4703']

    # Verifica se '0' está presente em filiais_list
    if '0' not in filiais_string:
         # Exclui os códigos especificados de codigos_requisicao
        codigos_requisicao = [codigo for codigo in codigos_requisicao if codigo not in codigos_excluir]

    consulta_ccs = CentroCusto.objects.filter(
        codigo__in=codigos_requisicao
    ).values('codigo', 'nome')

    # Converte o resultado da consulta para um dicionário
    mapa_codigos_nomes = {
        item['codigo']: item['nome'] for item in consulta_ccs
    }

    # Aplicar a função para criar uma lista de códigos em cada linha
    consulta_realizado['CODIGOS_SEPARADOS'] = consulta_realizado['CCSTCOD'].apply(extrair_codigos)
    
    # Explodir a lista de códigos em várias linhas, um código por linha
    df_explodido = consulta_realizado.explode('CODIGOS_SEPARADOS')

    # Filtrar as linhas que contêm os códigos recebidos na requisição
    df_filtrado = df_explodido[df_explodido['CODIGOS_SEPARADOS'].isin(codigos_requisicao)]
    
    # Agrupar por código e somar os valores
    df_agrupado = df_filtrado.groupby('CODIGOS_SEPARADOS')['SALDO'].sum().to_dict()
    
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
    
        detalhes = consulta_realizado[consulta_realizado['CCSTCOD'].str.contains(codigo)]
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

   
    # Obter os códigos agrupados
    codigos_agrupados = list(df_agrupado.keys())

    # Certifique-se de que os códigos estão no formato correto (string)
    codigos_agrupados = [str(codigo) for codigo in codigos_agrupados]

    # Verifique os valores de codigos_agrupados
   

    # Consulta os centros de custo e seus pais com base nos códigos agrupados
    consulta_ccs_pais = CentroCusto.objects.filter(
        codigo__in=codigos_agrupados  # Substituí 'id' por 'codigo'
    ).values('codigo', 'nome', 'cc_pai__id', 'cc_pai__nome', 'gestor__nome')

    # Verifique os resultados da consulta
    

    # Cria um dicionário para mapear os códigos dos centros de custo para seus pais
    mapa_codigos_pais = {
        str(item['codigo']): {
            'cc_pai_id': str(item['cc_pai__id']) if item['cc_pai__id'] else None,
            'cc_pai_nome': item['cc_pai__nome'] or 'Sem Pai',
            'gestor_nome': item.get('gestor__nome', 'Sem Gestor')
        }
        for item in consulta_ccs_pais
    }

    df_agrupado_por_pai = {}
    total_geral = 0
    for codigo, saldo in df_agrupado.items():
        pai_info = mapa_codigos_pais.get(str(codigo), {'cc_pai_nome': 'Sem Pai', 'gestor_nome': 'Sem Gestor'})
        pai_nome = pai_info['cc_pai_nome']
        pai_gestor = pai_info['gestor_nome']
        if pai_nome not in df_agrupado_por_pai:
            df_agrupado_por_pai[pai_nome] = {
                'saldo': 0,
                'gestor': pai_gestor
            }
        df_agrupado_por_pai[pai_nome]['saldo'] += saldo 
        total_geral += saldo
    total_geral_formatado = format_locale(total_geral)

    df_agrupado_pais_detalhes = {}

    # Agrupar os valores por centro de custo pai e criar o detalhamento
    for codigo, saldo in df_agrupado.items():
        # Obter informações do pai a partir do mapeamento
        pai_info = mapa_codigos_pais.get(str(codigo), {'cc_pai_nome': 'Sem Pai'})
        pai_nome = pai_info['cc_pai_nome']

        # Inicializar o agrupamento e os detalhes para o pai, se necessário
        if pai_nome not in df_agrupado_pais_detalhes:
            df_agrupado_pais_detalhes[pai_nome] = {
                'saldo': 0,
                'detalhes': []
            }

        # Somar o saldo ao pai
        df_agrupado_pais_detalhes[pai_nome]['saldo'] += saldo

        # Adicionar os detalhes relacionados ao centro de custo ao pai
        detalhes = consulta_realizado[consulta_realizado['CCSTCOD'].str.contains(codigo)]
        for _, row in detalhes.iterrows():
            if row['SALDO'] != 0:
                df_agrupado_pais_detalhes[pai_nome]['detalhes'].append({
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
  

    # Formatar os valores finais (opcional)
    df_agrupado_por_pai_formatado = {
        pai: format_locale(valor) for pai, valor in df_agrupado_por_pai.items()
    }

    dicionario_soma_nomes_formatado = {
        nome: format_locale(saldo) for nome, saldo in dicionario_soma_nomes.items()
    }

    response_data = {
        #'total': total_formatado,
        #'dados': consulta_agrupada.to_dict(orient='records'),
        #'df_agrupado': df_agrupado_nomes_formatado,
        'agrupado_por_pai': df_agrupado_por_pai_formatado,
        #'teste': df_agrupado_nomes,
        #'df_agrupado_nomes_detalhes': df_agrupado_nomes_detalhes,
        #'df_agrupado_pais_detalhes': df_agrupado_pais_detalhes,
        'dicionario_soma_nomes': dicionario_soma_nomes_formatado,
        'total_soma_gps': total_soma_nomes,
        'total_soma_ccs': total_geral
    }

    return JsonResponse(response_data, safe=False)

#####################################################################################

@csrf_exempt
@api_view(['POST'])
def meus_calculos_cc_curva(request):
    cc_list = request.data.get('ccs_pai', [])
    cc_list_str = [str(codigo) for codigo in cc_list]
    grupo_itens_list = request.data.get('grupos_itens', [])
    filiais_list = request.data.get('filial', [])
    ano = request.data.get('ano', None)
    conta1 = '3401%'
    conta2 = '3402%' 
    conta = '4%'
    meses = request.data.get('periodo', [])

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
    
    # Validação dos meses
    if not isinstance(meses, list) or not all(isinstance(mes, int) and 1 <= mes <= 12 for mes in meses):
        raise ValueError("O parâmetro 'meses' deve ser uma lista de inteiros entre 1 e 12.")
    
    # Conversão de listas para strings no formato esperado pelo SQL
    filiais_string = ', '.join(map(str, filiais_list))
    
    grupo_itens_list_str = ', '.join(map(str, grupo_itens_list))
    cc_string = ", ".join(map(str, cc_list))
    meses_string = ", ".join(map(str, meses))

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
    
    meses_condition = f"MONTH(LC.LANCDATA) IN ({meses_string})" if meses else "1=1"
    
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
                AND ({meses_condition})
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

    df = pd.DataFrame(consulta_realizado)
    
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

    # Pegando os últimos 9 caracteres da conta
    consulta_realizado['CONTA_ULTIMOS_9'] = consulta_realizado['CONTA'].str[-9:]

    # Mapeando os grupos de itens
    grupo_itens_map = {
        item['codigo']: {
            'nome_completo': item['nome_completo'],
            'gestor_nome': item.get('gestor__nome', 'Sem Gestor')  # Use .get para evitar KeyError
        }
        for item in GrupoItens.objects.values('codigo', 'nome_completo', 'gestor__nome')
    }

    # Mapeando o grupo de itens no DataFrame
    consulta_realizado['GRUPO_ITENS'] = consulta_realizado['CONTA_ULTIMOS_9'].map(
    lambda codigo: grupo_itens_map.get(codigo, {}).get('nome_completo', 'Gestor Indefinido')
)

    # Filtra o DataFrame com base nos grupos de itens fornecidos
    if grupo_itens_list:
        consulta_realizado = consulta_realizado[consulta_realizado['CONTA_ULTIMOS_9'].isin(grupo_itens_list)]

    # Agrupando os dados
    consulta_agrupada = consulta_realizado.groupby(['GRUPO_ITENS', 'CONTA_ULTIMOS_9']).agg({
    'SALDO': 'sum'
}).reset_index()
        
    # Criando o dicionário com saldo e nome do gestor
    dicionario_soma_nomes = {}
    total_soma_nomes = 0
    for _, row in consulta_agrupada.iterrows():
        grupo = row['GRUPO_ITENS']
        saldo = row['SALDO']
        
        # Obter o nome do gestor a partir do mapeamento
        gestor_nome = grupo_itens_map.get(row['CONTA_ULTIMOS_9'], {}).get('gestor_nome', 'Sem Gestor')
        
        if grupo not in dicionario_soma_nomes:
            dicionario_soma_nomes[grupo] = {
                'saldo': 0,
                'gestor': gestor_nome
            }

        dicionario_soma_nomes[grupo]['saldo'] += saldo
        total_soma_nomes += saldo
    total_soma_nomes_formatado = format_locale(total_soma_nomes)

    df_grupos_nomes = {}
    


###################################################################################################

    codigos_requisicao = cc_list_str

    # Função para extrair códigos da string
    def extrair_codigos(codigos):
        # Remove "+" e transforma em lista de códigos
        return codigos.strip('+').split('+')
    
    # # Excluir os códigos 4700, 4701 e 4703
    codigos_requisicao = [codigo for codigo in codigos_requisicao if codigo not in ['4700', '4701', '4703']]
    codigos_excluir = ['4700', '4701', '4703']

    # Verifica se '0' está presente em filiais_list
    if '0' not in filiais_string:
         # Exclui os códigos especificados de codigos_requisicao
        codigos_requisicao = [codigo for codigo in codigos_requisicao if codigo not in codigos_excluir]

    consulta_ccs = CentroCusto.objects.filter(
        codigo__in=codigos_requisicao
    ).values('codigo', 'nome')
   

    # Converte o resultado da consulta para um dicionário
    mapa_codigos_nomes = {
        item['codigo']: item['nome'] for item in consulta_ccs
    }
    
    # Aplicar a função para criar uma lista de códigos em cada linha
    consulta_realizado['CODIGOS_SEPARADOS'] = consulta_realizado['CCSTCOD'].apply(extrair_codigos)
    
    # Explodir a lista de códigos em várias linhas, um código por linha
    df_explodido = consulta_realizado.explode('CODIGOS_SEPARADOS')
    
    # Filtrar as linhas que contêm os códigos recebidos na requisição
    df_filtrado = df_explodido[df_explodido['CODIGOS_SEPARADOS'].isin(codigos_requisicao)]
    
    # Agrupar por código e somar os valores
    df_agrupado = df_filtrado.groupby('CODIGOS_SEPARADOS')['SALDO'].sum().to_dict()
    
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
    
        detalhes = consulta_realizado[consulta_realizado['CCSTCOD'].str.contains(codigo)]
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

   
    # Obter os códigos agrupados
    codigos_agrupados = list(df_agrupado.keys())

    # Certifique-se de que os códigos estão no formato correto (string)
    codigos_agrupados = [str(codigo) for codigo in codigos_agrupados]

    # Verifique os valores de codigos_agrupados
   

    # Consulta os centros de custo e seus pais com base nos códigos agrupados
    consulta_ccs_pais = CentroCusto.objects.filter(
        codigo__in=codigos_agrupados  # Substituí 'id' por 'codigo'
    ).values('codigo', 'nome', 'cc_pai__id', 'cc_pai__nome', 'gestor__nome')
   

    mapa_codigos_pais = {
        str(item['codigo']): {
            'cc_pai_id': str(item['cc_pai__id']) if item['cc_pai__id'] else None,
            'cc_pai_nome': item['cc_pai__nome'] or 'Sem Pai',
            'gestor_nome': item.get('gestor__nome', 'Sem Gestor')
        }
        for item in consulta_ccs_pais
    }

    df_agrupado_por_pai = {}
    total_geral = 0
    for codigo, saldo in df_agrupado.items():
        pai_info = mapa_codigos_pais.get(str(codigo), {'cc_pai_nome': 'Sem Pai', 'gestor_nome': 'Sem Gestor'})
        pai_nome = pai_info['cc_pai_nome']
        pai_gestor = pai_info['gestor_nome']
        if pai_nome not in df_agrupado_por_pai:
            df_agrupado_por_pai[pai_nome] = {
                'saldo': 0,
                'gestor': pai_gestor
            }
        df_agrupado_por_pai[pai_nome]['saldo'] += saldo 
        total_geral += saldo
    total_geral_formatado = format_locale(total_geral)

    df_agrupado_pais_detalhes = {}

    # Agrupar os valores por centro de custo pai e criar o detalhamento
    for codigo, saldo in df_agrupado.items():
        # Obter informações do pai a partir do mapeamento
        pai_info = mapa_codigos_pais.get(str(codigo), {'cc_pai_nome': 'Sem Pai'})
        pai_nome = pai_info['cc_pai_nome']

        # Inicializar o agrupamento e os detalhes para o pai, se necessário
        if pai_nome not in df_agrupado_pais_detalhes:
            df_agrupado_pais_detalhes[pai_nome] = {
                'saldo': 0,
                'detalhes': []
            }

        # Somar o saldo ao pai
        df_agrupado_pais_detalhes[pai_nome]['saldo'] += saldo

        # Adicionar os detalhes relacionados ao centro de custo ao pai
        detalhes = consulta_realizado[consulta_realizado['CCSTCOD'].str.contains(codigo)]
        for _, row in detalhes.iterrows():
            if row['SALDO'] != 0:
                df_agrupado_pais_detalhes[pai_nome]['detalhes'].append({
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
  

    # Formatar os valores finais (opcional)
    df_agrupado_por_pai_formatado = {
        pai: format_locale(valor) for pai, valor in df_agrupado_por_pai.items()
    }

    dicionario_soma_nomes_formatado = {
        nome: format_locale(saldo) for nome, saldo in dicionario_soma_nomes.items()
    }

    response_data = {
        #'total': total_formatado,
        #'dados': consulta_agrupada.to_dict(orient='records'),
        #'df_agrupado': df_agrupado_nomes_formatado,
        'agrupado_por_pai': df_agrupado_por_pai_formatado,
        #'teste': df_agrupado_nomes,
        #'df_agrupado_nomes_detalhes': df_agrupado_nomes_detalhes,
        #'df_agrupado_pais_detalhes': df_agrupado_pais_detalhes,
        'dicionario_soma_nomes': dicionario_soma_nomes_formatado,
        'total_soma_gps': total_soma_nomes,
        'total_soma_ccs': total_geral
    }

    return JsonResponse(response_data, safe=False)
