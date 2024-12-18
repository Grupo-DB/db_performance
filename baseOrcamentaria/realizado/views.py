from django.shortcuts import render
from datetime import datetime, timedelta
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from rest_framework.decorators import api_view
from django.db import connections
from sqlalchemy import create_engine
from baseOrcamentaria.orcamento.models import ContaContabil
import pandas as pd
import locale

locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')  # br

# String de conexão
connection_string = 'mssql+pyodbc://DBCONSULTA:DB%40%402023**@172.50.10.5/DB?driver=ODBC+Driver+17+for+SQL+Server'
# Cria a engine
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['POST'])
def calculos_realizado(request):
    cc_list = request.data.get('ccs',[])
    filiais_list = request.data.get('filiais',[])
    ano = request.data.get('ano', None)
    conta1 = '3401%'
    conta2 = '3402%'
    conta = '4%'

    if isinstance(filiais_list, list):
        try:
            # Remove quaisquer valores não numéricos ou vazios
            filiais_list = [int(filial) for filial in filiais_list if str(filial).isdigit()]
        except ValueError:
            raise ValueError("A lista de filiais contém valores não numéricos.")
    else:
        raise ValueError("O parâmetro 'filiais' deve ser uma lista.")

    # Garante que a lista não está vazia
    if not filiais_list:
        raise ValueError("A lista de filiais está vazia ou contém apenas valores inválidos.")

    # Converte a lista de inteiros para uma string no formato esperado pelo SQL
    filiais_string = ", ".join(map(str, filiais_list))

    # Constrói a cláusula dinâmica para o filtro 'CCSTCOD'
    if cc_list:
        cc_conditions = " OR ".join([f"CCSTCOD LIKE '%{cc}%'" for cc in cc_list])
    else:
        cc_conditions = "1=1"  # Condição neutra se 'cc' não for fornecido

    if ano:
        data_inicio = f"{ano}-01-01"
        data_fim = f"{ano}-12-31"


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
                    LC.LANCEMP
                FROM LANCAMENTO LC
                LEFT OUTER JOIN CENTROCUSTO ON CCCOD = LC.LANCCC
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
                END AS UNIDADE
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
                END AS UNIDADE
            FROM LANCAMENTOS_BASE
                
                
""",engine)
    
    consulta_realizado['SALDO'] = consulta_realizado.apply(
    #lambda row: row["DEB_VALOR"] if row["CONTA_DEB"][1] in ['3', '4'] else row["CRED_VALOR"],
    lambda row: row["DEB_VALOR"] if str(row["CONTA_DEB"])[1] in ['3', '4'] else row["CRED_VALOR"],
    axis=1
)
    #total = int(consulta_realizado['SALDO'])
    if consulta_realizado['SALDO'].empty or consulta_realizado['SALDO'].sum() == 0:
        total = "0"  # Define como zero formatado
    else:
        total = consulta_realizado['SALDO'].sum()  # Soma os valores
        total = locale.format_string("%.0f", total, grouping=True)
    
    
    consulta_realizado['conta_deb_7'] = consulta_realizado['CONTA_DEB'].str[:7]
    consulta_realizado['conta_cred_7'] = consulta_realizado['CONTA_CRED'].str[:7]


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
            return None  # Retorna None se nenhuma das contas começar com '3' ou '4'



    consulta_realizado['GRUPO_CONTA'] = consulta_realizado.apply(
    lambda row: definir_grupo_conta(row['CONTA_DEB'], row['CONTA_CRED']),
    axis=1
)

    total_grupo = consulta_realizado.groupby('GRUPO_CONTA')['SALDO'].sum().to_dict()
    codigos = list(total_grupo.keys())

    consulta_conta = ContaContabil.objects.filter(
     nivel_4_conta__in=codigos
    ).values('nivel_4_conta', 'nivel_4_nome')

    # Converte o resultado da consulta para um dicionário
    grupo_contabil = {conta['nivel_4_conta']: conta['nivel_4_nome'] for conta in consulta_conta}

    # Substitui os códigos pelos nomes no dicionário total_grupo
    #total_grupo_com_nomes = {grupo_contabil.get(codigo, codigo): valor for codigo, valor in total_grupo.items()}

    total_grupo_com_nomes = {}
    for conta, valor in total_grupo.items():
        nome = grupo_contabil.get(conta, conta)  # Obtém o nome da conta, ou mantém o código
        if nome in  total_grupo_com_nomes:
            total_grupo_com_nomes[nome] += valor  # Soma os valores se o nome já existir
        else:
            total_grupo_com_nomes[nome] = valor


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
            return None  # Retorna None se nenhuma das contas começar com '3' ou '4'
    consulta_realizado['CONTA_COMPLETA'] = consulta_realizado.apply(
        lambda row: definir_conta_contabil(row['CONTA_DEB'], row['CONTA_CRED']),
        axis=1
    )
    total_conta = consulta_realizado.groupby('CONTA_COMPLETA')['SALDO'].sum().to_dict()
    contas = list(total_conta.keys())

    consulta_completa = ContaContabil.objects.filter(
        nivel_analitico_conta__in=contas
    ).values('nivel_analitico_conta', 'nivel_5_nome','nivel_analitico_nome')

    conta_completa = {
        conta['nivel_analitico_conta']: f"{conta['nivel_5_nome']} - {conta['nivel_analitico_nome']}"
        for conta in consulta_completa
    }

    conta_completa_nomes = {}

    for conta, valor in total_conta.items():
        nome = conta_completa.get(conta, conta)  # Obtém o nome da conta, ou mantém o código
        if nome in conta_completa_nomes:
            conta_completa_nomes[nome] += valor  # Soma os valores se o nome já existir
        else:
            conta_completa_nomes[nome] = valor

    ##################################################################################
    codigos_requisicao = request.data.get('ccs',[])
    
    def extrair_codigos(codigos):
    # Limpa a string, remove os "+" e transforma em uma lista de códigos
        return codigos.strip('+').split('+')    

    # Aplicar a função para criar uma lista de códigos em cada linha
    consulta_realizado['CODIGOS_SEPARADOS'] = consulta_realizado['CCSTCOD'].apply(extrair_codigos)

    # Explodir a lista de códigos em várias linhas, um código por linha
    df_explodido = consulta_realizado.explode('CODIGOS_SEPARADOS')

    # Filtrar as linhas que contêm os códigos recebidos na requisição
    df_filtrado = df_explodido[df_explodido['CODIGOS_SEPARADOS'].isin(codigos_requisicao)]

    # Agrupar por código e somar os valores
    df_agrupado = df_filtrado.groupby('CODIGOS_SEPARADOS')['SALDO'].sum().to_dict()


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

    

    #Converte o DataFrame em um formato JSON serializável
    data_json = {
        'total': total,
        #'total_deb_grupo_lista': consulta_realizado.to_dict(orient='records'),
        #'total_cred_grupo_lista': consulta_realizado.to_dict(orient='records'),
        #'respostas':consulta_realizado.to_dict(orient='records')
        'total_tipo_deb': total_tipo_deb,
        #'total_tipo_cred': total_tipo_cred,
        'total_grupo': total_grupo,
        'total_conta': total_conta,
        'df_agrupado':df_agrupado,
        'grupo_contabil': grupo_contabil,
        'total_grupo_com_nomes': total_grupo_com_nomes,
        'conta_completa_nomes': conta_completa_nomes,
        'conta_completa':conta_completa,
        'contas':contas
        }
    
    # Retorna o JSON como resposta
    return JsonResponse(data_json, safe=False)
