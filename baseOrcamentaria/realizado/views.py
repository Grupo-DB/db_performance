import calendar
from django.shortcuts import render
from datetime import datetime, timedelta
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
from sqlalchemy import create_engine
from baseOrcamentaria.orcamento.models import ContaContabil,CentroCusto
import pandas as pd
import locale
import datetime
locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')  # br

# String de conexão
connection_string = 'mssql+pyodbc://DBCONSULTA:%21%40%23123qweQWE@172.10.27.51:1433/DB?driver=ODBC+Driver+17+for+SQL+Server'
# Cria a engine
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['POST'])
def calculos_realizado(request):
    cc_list = request.data.get('ccs', [])
    filiais_list = request.data.get('filiais', [])
    ano = request.data.get('ano', None)
    conta1 = '3401%'
    conta2 = '3402%'
    conta = '4%'
    meses = request.data.get('periodo', [])
    # Validação das filiais
    if isinstance(filiais_list, list):
        try:
            filiais_list = [int(filial) for filial in filiais_list if str(filial).isdigit()]
        except ValueError:
            raise ValueError("A lista de filiais contém valores não numéricos.")
    else:
        raise ValueError("O parâmetro 'filiais' deve ser uma lista.")

    if not filiais_list:
        raise ValueError("A lista de filiais está vazia ou contém apenas valores inválidos.")

    # Validação de cc_list
    if isinstance(cc_list, list):
        try:
            cc_list = [int(cc) for cc in cc_list if str(cc).isdigit()]
        except ValueError:
            raise ValueError("A lista de 'ccs' contém valores não numéricos.")
    else:
        raise ValueError("O parâmetro 'ccs' deve ser uma lista.")

    # Validação dos meses
    if not isinstance(meses, list) or not all(isinstance(mes, int) and 1 <= mes <= 12 for mes in meses):
        raise ValueError("O parâmetro 'meses' deve ser uma lista de inteiros entre 1 e 12.")
    
    # Verifica se há meses futuros
    mes_atual = datetime.date.today().month
    #if any(mes > mes_atual for mes in meses):
        #raise ValueError("O parâmetro 'periodo' contém meses futuros, o que não é permitido.")
    
     # Determina a data de início e fim
    if ano:
        mes_inicio = min(meses)
        mes_fim = max(meses)

        data_inicio = datetime.date(ano, mes_inicio, 1)

        if mes_fim >= mes_atual:
            data_fim = datetime.date.today()
        else:
            ultimo_dia = calendar.monthrange(ano, mes_fim)[1]
            data_fim = datetime.date(ano, mes_fim, ultimo_dia)
    else:
        raise ValueError("O parâmetro 'ano' é obrigatório.")
    
    #print(f"Data de início: {data_inicio}")
    #print(f"Data de fim: {data_fim}")

    # Converte listas para strings no formato esperado pelo SQL
    filiais_string = ", ".join(map(str, filiais_list))
    cc_string = ", ".join(map(str, cc_list))
    meses_string = ", ".join(map(str, meses))
    
    # Constrói cláusula dinâmica para filtro 'CCSTCOD'
    if cc_list:
        cc_conditions = " OR ".join([f"CCSTCOD LIKE '%{cc}%'" for cc in cc_list])
    else:
        cc_conditions = "1=1"  # Condição neutra se 'cc_list' não for fornecida
 

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
                
""",engine)
    #Regra para obtenção dos valores usados
    consulta_realizado['SALDO'] = consulta_realizado.apply(
    lambda row: row["DEB_VALOR"] if str(row["CONTA_DEB"])[1] in ['3', '4'] else row["CRED_VALOR"],
    axis=1
)

    # Cria a coluna DESCRICAO
    consulta_realizado['DESCRICAO'] = consulta_realizado.apply(
        lambda row: row['ITEM'] if pd.notnull(row['ITEM']) else row['HISTORICO'],
        axis=1
    )

    # Converte os valores de QTD para 0 quando for null
    consulta_realizado['QTD'] = consulta_realizado['QTD'].fillna(1)

    #converte a data
    consulta_realizado['LANCDATA'] = pd.to_datetime(consulta_realizado['LANCDATA']).dt.strftime('%d/%m/%Y')

    if consulta_realizado['SALDO'].empty or consulta_realizado['SALDO'].sum() == 0:
        total = "0"  # Define como zero formatado
        total_formatado = "0"
    else:
        total = consulta_realizado['SALDO'].sum()  # Soma os valores
        total_formatado = locale.format_string("%.0f", total, grouping=True)

    ###-------------------------Obtem e agrua por grupo de contas----------------------------##   
    def definir_grupo_conta(conta_deb, conta_cred):
        conta_deb = str(conta_deb).lstrip("'")  # Remove a ' extra  
        conta_cred = str(conta_cred).lstrip("'")
        # Filtra apenas as contas que começam com '3' ou '4'
        if conta_deb[:1] in ['3', '4'] and conta_cred[:1] in ['3', '4']:
            return max(conta_deb[:6], conta_cred[:6])  # Retorna o valor maior entre as duas contas
        elif conta_deb[:1] in ['3', '4']:
            return conta_deb[:6]  # Retorna conta_deb se ela começar com '3' ou '4'
        elif conta_cred[:1] in ['3', '4']:
            return conta_cred[:6]  # Retorna conta_cred se ela começar com '3' ou '4'
        else:
            return None  

    consulta_realizado['GRUPO_CONTA'] = consulta_realizado.apply(
    lambda row: definir_grupo_conta(row['CONTA_DEB'], row['CONTA_CRED']),
    axis=1
)
    # Função para formatar valores com locale
    def format_locale(value):
        try:
            if not isinstance(value, (int, float)):
                value = float(value)  # Garante que seja numérico
            return locale.format_string("%.0f", value, grouping=True)
        except Exception as e:
            return str(value)  # Em caso de erro, retorna como string simples


    total_grupo = consulta_realizado.groupby('GRUPO_CONTA')['SALDO'].sum().to_dict()
    
    #Pega os nomes na tabela conta contabil 
    codigos = list(total_grupo.keys())
    consulta_conta = ContaContabil.objects.filter(
     nivel_4_conta__in=codigos
    ).values('nivel_4_conta', 'nivel_4_nome')
    # Converte o resultado da consulta para um dicionário
    grupo_contabil = {conta['nivel_4_conta']: conta['nivel_4_nome'] for conta in consulta_conta}

    total_grupo_com_nomes_detalhes = {}

    # Substitui os códigos pelos nomes no dicionário total_grupo
    total_grupo_com_nomes = {}
    for conta, valor in total_grupo.items():
        nome = grupo_contabil.get(conta, conta)  # Obtém o nome da conta, ou mantém o código
        if nome in  total_grupo_com_nomes:
            total_grupo_com_nomes[nome] += valor  # Soma os valores se o nome já existir
        else:
            total_grupo_com_nomes[nome] = valor
            total_grupo_com_nomes_detalhes[nome] = []

        detalhes = consulta_realizado[consulta_realizado['GRUPO_CONTA']== conta ]
        for _, row in detalhes.iterrows():
            if row['SALDO'] != 0:
                total_grupo_com_nomes_detalhes[nome].append({
                    'conta': conta,
                    'valor': valor,
                    'LANCCOD': row['LANCCOD'],
                    'LANCDATA': row['LANCDATA'],
                    'HISTORICO': row['HISTORICO'],
                    'SALDO': row['SALDO'],
                    'LANCREF': row['LANCREF'],
                    'SITUACAO': row['SITUACAO'],
                    'ITEM': row['ITEM'],
                    'QTD': row['QTD'],
                    'DESCRICAO': row['DESCRICAO'] 
                })

    total_grupo_com_nomes_formatado = {grupo: format_locale(valor) for grupo, valor in total_grupo_com_nomes.items()}

###-------------------------Obtem e agrua por grupo de contas----------------------------## 
    def definir_conta_contabil(conta_deb, conta_cred):
        conta_deb = str(conta_deb).lstrip("'")  # Remove a ' extra  
        conta_cred = str(conta_cred).lstrip("'")  
       
        if conta_deb[:1] in ['3', '4'] and conta_cred[:1] in ['3', '4']:
            return max(conta_deb[:13], conta_cred[:13])  # Retorna o valor maior entre as duas contas
        elif conta_deb[:1] in ['3', '4']:
            return conta_deb[:13]  # Retorna conta_deb se ela começar com '3' ou '4'
        elif conta_cred[:1] in ['3', '4']:
            return conta_cred[:13]  # Retorna conta_cred se ela começar com '3' ou '4'
        else:
            return None 

    consulta_realizado['CONTA_COMPLETA'] = consulta_realizado.apply(
        lambda row: definir_conta_contabil(row['CONTA_DEB'], row['CONTA_CRED']),
        axis=1
    )

    total_conta = consulta_realizado.groupby('CONTA_COMPLETA')['SALDO'].sum().to_dict()

     #Pega os nomes na tabela conta contabil 
    contas = list(total_conta.keys())
    consulta_completa = ContaContabil.objects.filter(
        nivel_analitico_conta__in=contas
    ).values('nivel_analitico_conta', 'nivel_5_nome','nivel_analitico_nome')
    # Converte o resultado da consulta para um dicionário
    conta_completa = {
        conta['nivel_analitico_conta']: f"{conta['nivel_5_nome']} - {conta['nivel_analitico_nome']}"
        for conta in consulta_completa
    }

    
     # Inicializa o dicionário para armazenar os detalhes das somas
    conta_completa_detalhes = {}

    conta_completa_nomes = {}
    for conta, valor in total_conta.items():
        nome = conta_completa.get(conta, conta)  # Obtém o nome da conta ou mantém o código
        if nome in conta_completa_nomes:
            conta_completa_nomes[nome] += valor  # Soma os valores se o nome já existir
        else:
            conta_completa_nomes[nome] = valor
            conta_completa_detalhes[nome] = []

        # Adiciona os detalhes agrupados
        detalhes = consulta_realizado[consulta_realizado['CONTA_COMPLETA'] == conta]
        for _, row in detalhes.iterrows():
            if row['SALDO'] != 0:  # Condicional para adicionar apenas linhas onde SALDO > 0
                conta_completa_detalhes[nome].append({
                    'conta': conta,
                    'valor': valor,
                    'LANCCOD': row['LANCCOD'],
                    'LANCDATA': row['LANCDATA'],
                    'HISTORICO': row['HISTORICO'],
                    'SALDO': row['SALDO'],
                    'LANCREF': row['LANCREF'],
                    'SITUACAO': row['SITUACAO'],
                    'ITEM': row['ITEM'],
                    'QTD': row['QTD'],
                    'DESCRICAO': row['DESCRICAO']
                })

    conta_completa_nomes_formatado = {conta: format_locale(valor) for conta, valor in conta_completa_nomes.items()}

    ##################################################################################
    codigos_requisicao = request.data.get('ccs',[])

    # Função para extrair códigos da string
    def extrair_codigos(codigos):
        if codigos is None:
            return []  # Retorna uma lista vazia se codigos for None
        return codigos.strip('+').split('+')
    
    codigos_excluir = ['4700', '4701', '4703']

    # Verifica se '0' está presente em filiais_list
    if '0'  in filiais_string:
        #print("Filiais diferentes de 0")
         # Exclui os códigos especificados de codigos_requisicao
        codigos_requisicao = [codigo for codigo in codigos_requisicao if codigo not in codigos_excluir]

    # Consulta os nomes correspondentes aos códigos requisitados
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

    # Substituir os códigos pelos nomes no agrupamento
    df_agrupado_nomes = {
        mapa_codigos_nomes.get(codigo, codigo): saldo
        for codigo, saldo in df_agrupado.items()
    }

    # Formatar os valores finais (opcional)
    df_agrupado_nomes_formatado = {
        nome: format_locale(valor) for nome, valor in df_agrupado_nomes.items()
    }


    def mapear_tipo_custo(conta_deb, conta_cred):
        custos_insumos = {'4101021', '4102021', '4103021', '4104021', '4105021', '4106021', '4107021', '4108021', '4109021', '4110021', '4111021', '4112021'}
        custos_materia_prima = {'4101023', '4102023', '4103023', '4104023', '4105023', '4106023', '4107023', '4108023', '4109023', '4110023', '4111023', '4112023'}
        custos_embalagens = {'4101022', '4102022', '4103022', '4104022', '4105022', '4106022', '4107022', '4108022', '4109022', '4110022', '4111022', '4112022'}

        for conta in [conta_deb, conta_cred]:  
            conta = str(conta).lstrip("'")  # Remove a ' extra
            prefixo = conta[:4]
            conta_completa = conta[:7]

            if prefixo == '3401':
                return 'Despesas Administrativas'
            elif prefixo == '3402':
                return 'Despesas Comerciais'
            elif prefixo.startswith('42'):
                return 'Custos Indiretos'
            elif prefixo.startswith('41'):
                if conta_completa in custos_insumos:
                    return 'Custo Direto Variável Insumos'
                elif conta_completa in custos_materia_prima:
                    return 'Custo Direto Variável Matéria Prima'
                elif conta_completa in custos_embalagens:
                    return 'Custo Direto Variável Embalagens'
                else:
                    return 'Custo Direto Fixo'
        return 'Tipo de custo desconhecido'

    # Aplicar a função a cada linha, passando ambas as colunas
    consulta_realizado['TIPO_CUSTO'] = consulta_realizado.apply(
        lambda row: mapear_tipo_custo(row['CONTA_DEB'], row['CONTA_CRED']),
        axis=1
    )

    total_tipo_deb = consulta_realizado.groupby('TIPO_CUSTO')['SALDO'].sum().to_dict()
    total_tipo_deb_formatado = {tipo: format_locale(valor) for tipo, valor in total_tipo_deb.items()}
    

    #Converte o DataFrame em um formato JSON serializável
    data_json = {
        'total_realizado': total_formatado,
        'total_real': total,
        #'total_deb_grupo_lista': consulta_realizado.to_dict(orient='records'),
        #'total_cred_grupo_lista': consulta_realizado.to_dict(orient='records'),
        'respostas':consulta_realizado.to_dict(orient='records'),
        'conta_completa_detalhes': conta_completa_detalhes,
        'total_grupo_com_nomes_detalhes': total_grupo_com_nomes_detalhes,
        'total_tipo_deb': total_tipo_deb_formatado,
        #'total_tipo_cred': total_tipo_cred,
        #'total_grupo': total_grupo_com_nomes_formatado,
        'total_conta': total_conta,
        'df_agrupado':df_agrupado_nomes_formatado,
        'grupo_contabil': grupo_contabil,
        'total_grupo_com_nomes': total_grupo_com_nomes_formatado,
        'conta_completa_nomes': conta_completa_nomes_formatado,
        'conta_completa':conta_completa,
        'contas':contas
        }
    
    # Retorna o JSON como resposta
    return JsonResponse(data_json, safe=False)
