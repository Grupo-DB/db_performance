import re
from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework import viewsets
from sqlalchemy import create_engine
from django.views.decorators.csrf import csrf_exempt
from django.db import connections
from .models import Regiao, Representante, Meta, Comissao
from .serializers import RegiaoSerializer, RepresentanteSerializer, MetaSerializer, ComissaoSerializer
import pandas as pd
import locale

class RegiaoViewSet(viewsets.ModelViewSet):
    queryset = Regiao.objects.all()
    serializer_class = RegiaoSerializer

class RepresentanteViewSet(viewsets.ModelViewSet):
    queryset = Representante.objects.all()
    serializer_class = RepresentanteSerializer

class MetaViewSet(viewsets.ModelViewSet):
    queryset = Meta.objects.all()
    serializer_class = MetaSerializer

class ComissaoViewSet(viewsets.ModelViewSet):
    queryset = Comissao.objects.all()
    serializer_class = ComissaoSerializer


#========================   Consulta de vendas para montar cálculos =========================#
 # String de conexão
connection_string = 'mssql+pyodbc://DBCONSULTA:%21%40%23123qweQWE@172.10.27.51:1433/DB?driver=ODBC+Driver+17+for+SQL+Server'

### Para uso em LOCALENV
#connection_string = 'mssql+pyodbc://DBCONSULTA:%21%40%23123qweQWE@45.6.118.50,65530/DB?driver=ODBC+Driver+17+for+SQL+Server'


# Cria a engine
engine = create_engine(connection_string)

@csrf_exempt
@api_view(['POST'])
def calculos_comissoes(request):
    dataInicio = request.data.get('dataInicio')
    dataFim = request.data.get('dataFim')
    consulta_vendas = pd.read_sql(f"""
        SELECT  
        GRFNOME,
        CASE
        WHEN NFFIL = 0 THEN EMPSIGLA
        ELSE FILSIGLA
        END EMPRESAFILIAL, 
        NFDATA DATA_EMISSAO,
        NFNUM NOTA_FISCAL, 
        ESPSIGLA UNIDADE,
        NOPNOME +  ' (' +  
        SUBSTRING(CAST(INFCFOP AS VARCHAR(MAX)), 1, 1) +  '.' + 
        SUBSTRING(CAST(INFCFOP AS VARCHAR(MAX)), 2, 3) +  ')' NATUREZA_OPERACAO,

        CLINOME CLIENTE_NOME, CLICOD CLIENTE_CODIGO, CLICNPJCPF CLIENTE_CNPJCPF,
        (SELECT CIDNOME + '-' + ESTUF FROM CIDADE
        JOIN ESTADO ON ESTCOD = CIDEST
        WHERE CIDCOD = CLICIDADE) CLIENTE_CIDADE,
        CASE
        WHEN (SELECT PPDADOCHAR FROM PESPARAMETRO 
                WHERE PPTPP = 579 AND PPREF = INF.INFPED) = 'S' AND NFECLI > 0 THEN (SELECT CIDNOME + '-' + ESTUF FROM ENDERECOCLIENTE
                                                                JOIN CIDADE ON CIDCOD = ECLICIDADE
                                                                JOIN ESTADO ON ESTCOD = CIDEST
                                                                WHERE ECLICOD = NFECLI
                                                                AND ECLICLI = NFCLI)
        ELSE (SELECT CIDNOME + '-' + ESTUF FROM CIDADE
                JOIN ESTADO ON ESTCOD = CIDEST
                WHERE CIDCOD = CLICIDADE)
        END CIDADE_FATURAMENTO, SEGCNOME SEGMENTO_CLIENTE,
        R.REPNOME REPRESENTANTE, R.REPCOD REPRESENTANTE_CODIGO, 
        M.REPNOME REPRESENTANTE_MASTER, M.REPNOME REPRESENTANTE_MASTER_CODIGO,

        ESTQNOME ESTOQUE, ESTQCOD ESTOQUE_CODIGO, 
        CASE
        WHEN ESTQGRP = 0 THEN GALMNOME
        ELSE GRPNOME
        END GRUPO, 
        CASE
        WHEN ESTQGALM IN (1974,1587, 1828) THEN 'AGRONEGOCIO'  --/foi adicionado o codgrupo 1974/
        ELSE 'CONSTRUCAO CIVIL'
        END SEGMENTO_PRODUTO,
        INFQUANT QUANTIDADE,
        --((INFQUANT * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000) QUANTIDADE_TN, 
        ((INFQUANT * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / NULLIF(1000.0, 0)) AS QUANTIDADE_TN,
        --((INFTOTAL / (NFTOTPRO+NFTOTSERV)) * (NFTOTPRO+NFTOTSERV)) VALOR_PRODUTO,
        ((INFTOTAL / NULLIF((NFTOTPRO + NFTOTSERV), 0)) * (NFTOTPRO + NFTOTSERV)) AS VALOR_PRODUTO,
        (INFICMSSTVALOR) ICMSST,
        (INFDAFRETE) FRETE,
        --((INFTOTAL / (NFTOTPRO+NFTOTSERV)) * NFTOTAL) VALOR_TOTAL,
        ((INFTOTAL / NULLIF((NFTOTPRO + NFTOTSERV), 0)) * NFTOTAL) AS VALOR_TOTAL,
        (SELECT EGCNOME FROM PESPARAMETRO PP
        JOIN RH_ESTOQUE_GRUPO_COMERCIAL ON EGCCOD = PP.PPDADOINTEGER
        WHERE PP.PPTPP = 577
        AND PP.PPREF = ESTQ.ESTQCOD) GRUPO_COMERCIAL,
        (SELECT EGCNOME FROM PESPARAMETRO PP
        JOIN TIPOPESPARAMETRO TPP ON TPPCOD = PPTPP
        JOIN RH_ESTOQUE_GRUPO_COMERCIAL ON EGCCOD = PP.PPDADOINTEGER
        WHERE TPPSIGLA = 'GRUPO_COMERCIAL_LINHA_PRODUTOS'
        AND PP.PPREF = ESTQ.ESTQCOD) GRUPO_COMERCIAL_LINHA_PRODUTOS,
        CASE
        WHEN R.REPREPREF > 0 THEN M.REPNOME
        WHEN CLICOD IN (37, 2454) THEN 'YARA'
        WHEN ESTQGALM IN (1587, 1828) THEN R.REPNOME
        ELSE CASE
                WHEN (SELECT PPDADOCHAR FROM PESPARAMETRO 
                WHERE PPTPP = 579 AND PPREF = INF.INFPED) = 'S' AND NFECLI > 0 THEN (SELECT RGNOME FROM ENDERECOCLIENTE
                                                                JOIN CIDADE ON CIDCOD = ECLICIDADE
                                                                JOIN REGIAO ON RGCOD = CIDRG
                                                                WHERE ECLICOD = NFECLI
                                                                AND ECLICLI = NFCLI)
                ELSE (SELECT RGNOME FROM CIDADE
                    JOIN REGIAO ON RGCOD = CIDRG
                    WHERE CIDCOD = CLICIDADE)
            END
        END REGIAO,

        (SELECT  CONVERT(CHAR(10),[CRVENC],103)
        FROM CONTARECEBER
        JOIN DUPLICATA ON DUPNUM = CRNUM    
        WHERE DUPNFCOD            = NF.NFCOD
        AND DUPPARNUM             = 1
        )PRAZO_1,

        (SELECT  CONVERT(CHAR(10),[CRVENC],103)
        FROM CONTARECEBER
        JOIN DUPLICATA ON DUPNUM = CRNUM    
        WHERE DUPNFCOD            = NF.NFCOD
        AND DUPPARNUM             = 2
        )PRAZO_2,

        (SELECT  CONVERT(CHAR(10),[CRVENC],103)
        FROM CONTARECEBER
        JOIN DUPLICATA ON DUPNUM = CRNUM    
        WHERE DUPNFCOD            = NF.NFCOD
        AND DUPPARNUM             = 3
        )PRAZO_3,

        (SELECT  CONVERT(CHAR(10),[CRVENC],103)
        FROM CONTARECEBER
        JOIN DUPLICATA ON DUPNUM = CRNUM    
        WHERE DUPNFCOD            = NF.NFCOD
        AND DUPPARNUM             = 4
        )PRAZO_4,

        (SELECT  CONVERT(CHAR(10),[CRVENC],103)
        FROM CONTARECEBER
        JOIN DUPLICATA ON DUPNUM = CRNUM    
        WHERE DUPNFCOD            = NF.NFCOD
        AND DUPPARNUM             = 5
        )PRAZO_5,     

        (SELECT  CONVERT(CHAR(10),[CRVENC],103)
        FROM CONTARECEBER
        JOIN DUPLICATA ON DUPNUM = CRNUM    
        WHERE DUPNFCOD            = NF.NFCOD
        AND DUPPARNUM             = 6
        )PRAZO_6,     

        (SELECT  CONVERT(CHAR(10),[CRVENC],103)
        FROM CONTARECEBER
        JOIN DUPLICATA ON DUPNUM = CRNUM    
        WHERE DUPNFCOD            = NF.NFCOD
        AND DUPPARNUM             = 7
        )PRAZO_7,     

        (SELECT  CONVERT(CHAR(10),[CRVENC],103)
        FROM CONTARECEBER
        JOIN DUPLICATA ON DUPNUM = CRNUM    
        WHERE DUPNFCOD            = NF.NFCOD
        AND DUPPARNUM             = 8
        )PRAZO_8,

        (SELECT  CONVERT(CHAR(10),[CRVENC],103)
        FROM CONTARECEBER
        JOIN DUPLICATA ON DUPNUM = CRNUM    
        WHERE DUPNFCOD            = NF.NFCOD
        AND DUPPARNUM             = 9
        )PRAZO_9,

        (SELECT  CONVERT(CHAR(10),[CRVENC],103)
        FROM CONTARECEBER
        JOIN DUPLICATA ON DUPNUM = CRNUM    
        WHERE DUPNFCOD            = NF.NFCOD
        AND DUPPARNUM             = 10
        )PRAZO_10,

        (SELECT IPEDDIFTABPRECO 
        FROM ITEMPEDIDO
        WHERE IPEDPED = INF.INFPED
        AND IPEDESTQ  = INF.INFESTQ
        AND IPEDEMB   = INF.INFEMB
        AND IPEDIDENT = INF.INFIDENT
        )VLR_DIF_TAB_PRECO,

        INFUNIT, 

    (SELECT CASE WHEN IPEDDIFTABPRECO  <> 0
                --THEN CAST(IPEDUNIT / ((IPEDDIFTABPRECO /100) +1) AS NUMERIC(8,2))
                THEN CAST(IPEDUNIT / ((NULLIF(IPEDDIFTABPRECO, 0) /100) +1) AS NUMERIC(8,2))
                ELSE IPEDUNIT 
            END 
    FROM ITEMPEDIDO
    WHERE IPEDPED = INF.INFPED
    AND IPEDESTQ  = INF.INFESTQ
    AND IPEDEMB   = INF.INFEMB
    AND IPEDIDENT = INF.INFIDENT
    )VLR_TAB_PRECO,
    
    (SELECT  SUM(DATEDIFF(DAY, BB.NFDATA, CRVENC)) / 
    --COUNT(*) PRAZO_MD_LINEAR
    NULLIF(COUNT(*),0) PRAZO_MD_LINEAR
    FROM CONTARECEBER
    JOIN DUPLICATA ON DUPNUM = CRNUM
    JOIN NOTAFISCAL BB ON BB.NFCOD = DUPNFCOD
    WHERE BB.NFCOD = NF.NFCOD
    )PRAZO_MD_LINEAR

    FROM NOTAFISCAL NF
        JOIN CLIENTE ON CLICOD = NFCLI
    LEFT JOIN REPRESENTANTE R ON R.REPCOD = NFREP
    LEFT JOIN REPRESENTANTE M ON M.REPCOD = R.REPREPREF
        JOIN ITEMNOTAFISCAL INF ON INFNFCOD = NFCOD
        JOIN NATUREZAOPERACAO ON NOPCOD = INFNOP
        JOIN ESTOQUE ESTQ ON ESTQCOD = INFESTQ
        JOIN ESPECIE ON ESPCOD = ESTQESP 
        JOIN GRUPOFISCAL ON GRFCOD = ESTQGRF
        JOIN GRUPOALMOXARIFADO ON GALMCOD = ESTQGALM
    LEFT JOIN GRUPOPRODUTO ON GRPCOD = ESTQGRP
            JOIN EMPRESA ON EMPCOD = NFEMP
    LEFT JOIN FILIAL ON FILCOD = NFFIL
    LEFT OUTER JOIN SEGMENTOCLIENTE ON SEGCREF = 1 AND SEGCCOD = CLISEGC

    WHERE NFSIT = 1
    AND CAST(NFDATA AS DATE) BETWEEN '{dataInicio}' AND '{dataFim}'
    AND GALMPRODVENDA = 'S' 
    AND (SUBSTRING(NOPFLAGNF, 1, 1) = 'S' AND SUBSTRING(NOPFLAGNF, 25, 1) = 'N') --Flag Operação Finan. 'S' e Não Rep. Receita 'N'
    AND NFSNF NOT IN (8) -- Serie Acerto

    /*------------------------------------------------------------------------------------------------------------------------------------------
                                                            DEVOLUÇÕES
    ------------------------------------------------------------------------------------------------------------------------------------------*/
    UNION ALL 

    SELECT  
    GRFNOME,
    CASE
        WHEN NFFIL = 0 THEN EMPSIGLA
        ELSE FILSIGLA
    END EMPRESAFILIAL, 
    NFEDATA DATA_EMISSAO, 
    NFENUMNF NOTA_FISCAL, 
            ESPSIGLA UNIDADE,
    NOPENOME +  ' (' +  
    SUBSTRING(CAST(INFECFOP AS VARCHAR(MAX)), 1, 1) +  '.' + 
    SUBSTRING(CAST(INFECFOP AS VARCHAR(MAX)), 2, 3) +  ')' NATUREZA_OPERACAO,
    CLINOME CLIENTE_NOME, CLICOD CLIENTE_CODIGO, CLICNPJCPF CLIENTE_CNPJCPF,
    (SELECT CIDNOME + '-' + ESTUF FROM CIDADE
        JOIN ESTADO ON ESTCOD = CIDEST
        WHERE CIDCOD = CLICIDADE) CLIENTE_CIDADE,
    CASE
        WHEN (SELECT PPDADOCHAR FROM PESPARAMETRO 
            WHERE PPTPP = 579 AND PPREF = INF.INFPED) = 'S' AND NF.NFECLI > 0 THEN (SELECT CIDNOME + '-' + ESTUF FROM ENDERECOCLIENTE
                                                                JOIN CIDADE ON CIDCOD = ECLICIDADE
                                                                JOIN ESTADO ON ESTCOD = CIDEST
                                                                WHERE ECLICOD = NF.NFECLI
                                                                AND ECLICLI = NFCLI)
        ELSE (SELECT CIDNOME + '-' + ESTUF FROM CIDADE
            JOIN ESTADO ON ESTCOD = CIDEST
            WHERE CIDCOD = CLICIDADE)
    END CIDADE_FATURAMENTO, SEGCNOME SEGMENTO_CLIENTE,
    R.REPNOME REPRESENTANTE, R.REPCOD REPRESENTANTE_CODIGO, 
    M.REPNOME REPRESENTANTE_MASTER, M.REPNOME REPRESENTANTE_MASTER_CODIGO,
    ESTQNOME ESTOQUE, ESTQCOD ESTOQUE_CODIGO, 
    CASE
        WHEN ESTQGRP = 0 THEN GALMNOME
        ELSE GRPNOME
    END GRUPO, 
    CASE
        WHEN ESTQGALM IN (1974,1587, 1828) THEN 'AGRONEGOCIO'        --foi adicionado o codgrupo 1974/
        ELSE 'CONSTRUCAO CIVIL'
    END SEGMENTO_PRODUTO,
    -INFEQUANT QUANTIDADE,
    --((INFEQUANT * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END) / 1000) QUANTIDADE_TN, 
    -(NULLIF((INFEQUANT * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END),0) / 1000) QUANTIDADE_TN,
    -INFETOTAL VALOR_PRODUTO,
    --((INFEICMSSTVALOR/INFTOTAL)*INFETOTAL) ICMSST,
    -((INFEICMSSTVALOR/NULLIF(INFTOTAL,0))*INFETOTAL) ICMSST,
    --((INFDAFRETE/INFTOTAL)*INFETOTAL) FRETE,
    -((INFDAFRETE/NULLIF(INFTOTAL,0))*INFETOTAL) FRETE,
    -INFTOTAL  VALOR_TOTAL,
    (SELECT EGCNOME FROM PESPARAMETRO PP
        JOIN RH_ESTOQUE_GRUPO_COMERCIAL ON EGCCOD = PP.PPDADOINTEGER
        WHERE PP.PPTPP = 577
        AND PP.PPREF = ESTQ.ESTQCOD) GRUPO_COMERCIAL,
        (SELECT EGCNOME FROM PESPARAMETRO PP
        JOIN TIPOPESPARAMETRO TPP ON TPPCOD = PPTPP
        JOIN RH_ESTOQUE_GRUPO_COMERCIAL ON EGCCOD = PP.PPDADOINTEGER
        WHERE TPPSIGLA = 'GRUPO_COMERCIAL_LINHA_PRODUTOS'
        AND PP.PPREF = ESTQ.ESTQCOD) GRUPO_COMERCIAL_LINHA_PRODUTOS,
    CASE
        WHEN R.REPREPREF > 0 THEN M.REPNOME
        WHEN CLICOD IN (37, 2454) THEN 'YARA'
        WHEN ESTQGALM IN (1587, 1828) THEN R.REPNOME
        ELSE CASE
            WHEN (SELECT PPDADOCHAR FROM PESPARAMETRO 
            WHERE PPTPP = 579 AND PPREF = INF.INFPED) = 'S' AND NF.NFECLI > 0 THEN (SELECT RGNOME FROM ENDERECOCLIENTE
                                                                JOIN CIDADE ON CIDCOD = ECLICIDADE
                                                                JOIN REGIAO ON RGCOD = CIDRG
                                                                WHERE ECLICOD = NF.NFECLI
                                                                AND ECLICLI = NFCLI)
            ELSE (SELECT RGNOME FROM CIDADE
                JOIN REGIAO ON RGCOD = CIDRG
                WHERE CIDCOD = CLICIDADE)
            END
    END REGIAO,
    NULL PRAZO_1, NULL PRAZO_2, NULL PRAZO_3, NULL PRAZO_4, NULL PRAZO_5, 
    NULL PRAZO_6, NULL PRAZO_7, NULL PRAZO_8, NULL PRAZO_9, NULL PRAZO_10,
    NULL VLR_DIF_TAB_PRECO, NULL INFUNIT,  NULL VLR_TAB_PRECO, NULL PRAZO_MD_LINEAR

    FROM NOTAFISCAL NF
            JOIN CLIENTE ON CLICOD = NFCLI
    LEFT JOIN REPRESENTANTE R ON R.REPCOD = NFREP
    LEFT JOIN REPRESENTANTE M ON M.REPCOD = R.REPREPREF
        JOIN ITEMNOTAFISCAL INF ON INFNFCOD = NFCOD
        JOIN ITEMNOTAFISCALENTRADA ON INFEINFNUM = INF.INFNUM
        JOIN NATUREZAOPERACAOENTRADA ON NOPECOD = INFENOPE
        JOIN NATUREZAOPERACAO ON NOPCOD = INFNOP
        JOIN NOTAFISCALENTRADA ON NFECOD = INFENFE
        JOIN ESTOQUE ESTQ ON ESTQCOD = INFESTQ 
        JOIN GRUPOFISCAL ON GRFCOD = ESTQGRF
        JOIN ESPECIE ON ESPCOD = ESTQESP
        JOIN GRUPOALMOXARIFADO ON GALMCOD = ESTQGALM
        JOIN EMPRESA ON EMPCOD = NFEMP
    LEFT JOIN GRUPOPRODUTO ON GRPCOD = ESTQGRP
    LEFT JOIN FILIAL ON FILCOD = NFFIL
    LEFT OUTER JOIN SEGMENTOCLIENTE ON SEGCREF = 1 AND SEGCCOD = CLISEGC
    WHERE NFSIT          = 1
    AND CAST(NFEDATA AS DATE) BETWEEN '{dataInicio}' AND '{dataFim}'
    AND GALMPRODVENDA = 'S'
    AND (SUBSTRING(NOPFLAGNF, 1, 1) = 'S' 
            AND SUBSTRING(NOPFLAGNF, 25, 1) = 'N') --Flag Operação Finan. 'S' e Não Rep. Receita 'N'
    AND NFSNF NOT IN (8) -- Serie Acerto

    ORDER BY 2, 3, 4
                                """, engine)
    
    df = consulta_vendas.copy()

    import logging
    logger = logging.getLogger(__name__)
    #logger.warning(f"COLUNAS DO DF: {list(df.columns)}")

    # Metas opcionais recebidas no POST para sobrescrever as do banco
    metas_request = request.data.get('metas', {})
    considerar_potencializadores = request.data.get('considerar_potencializadores', True)
    licenca_maternidade_alexandra = request.data.get('licenca_maternidade_alexandra', False)

    # Normaliza campos relevantes
    df.columns = [c.strip() for c in df.columns]
    df['REPRESENTANTE'] = df['REPRESENTANTE'].fillna('').str.strip().str.upper()
    df['REPRESENTANTE_MASTER'] = df['REPRESENTANTE_MASTER'].fillna('').str.strip().str.upper()
    df['GRUPO_COMERCIAL'] = df['GRUPO_COMERCIAL'].fillna('').str.strip().str.upper()
    df['GRUPO_COMERCIAL_LINHA_PRODUTOS'] = df['GRUPO_COMERCIAL_LINHA_PRODUTOS'].fillna('').str.strip().str.upper()
    df['SEGMENTO_PRODUTO'] = df['SEGMENTO_PRODUTO'].fillna('').str.strip().str.upper()
    df['REGIAO'] = df['REGIAO'].fillna('').str.strip().str.upper()
    if 'CIDADE_FATURAMENTO' not in df.columns:
        df['CIDADE_FATURAMENTO'] = ''
    df['CIDADE_FATURAMENTO'] = df['CIDADE_FATURAMENTO'].fillna('').str.strip().str.upper()
    df['EMPRESAFILIAL'] = df['EMPRESAFILIAL'].fillna('').str.strip().str.upper()
    df['CLIENTE_NOME'] = df['CLIENTE_NOME'].fillna('').str.strip().str.upper()

    import datetime
    data_inicio_dt = datetime.datetime.strptime(dataInicio, '%Y-%m-%d').date()
    periodo_chave = f"{data_inicio_dt.month:02d}/{data_inicio_dt.year}"

    # Busca metas do banco para o período e monta no mesmo formato do metas_request
    # chave: "MM/AAAAREP_NOME" → {"CB": valor, "PRIMOR": valor, ...}
    from .models import Meta as MetaModel
    metas_db = {}
    try:
        qs = MetaModel.objects.filter(
            data_meta__range=[dataInicio, dataFim]
        ).select_related('representante')
        for m in qs:
            if not m.representante or not m.grupo:
                continue
            rep_nome_norm = re.sub(r'\s*-\s*\d+\s*$', '', m.representante.nome.strip().upper())
            chave = f"{periodo_chave}{rep_nome_norm}"
            if chave not in metas_db:
                metas_db[chave] = {}
            grupo_key = m.grupo.strip().upper()
            # Normaliza variantes de CB/CAL CREM para a chave usada no cálculo
            _cb_termos = ['CB CAL', 'CAL PINTURA', 'CERRO BRANCO', 'CAL CREM', 'CB/CAL']
            if any(t in grupo_key for t in _cb_termos):
                grupo_key = 'CB'
            metas_db[chave][grupo_key] = float(m.valor)
    except Exception:
        pass
    # POST body tem prioridade sobre banco
    metas_efetivas = {**metas_db, **metas_request}
    # Ativa potencializadores automaticamente se houver metas no banco
    if metas_db and not metas_request:
        considerar_potencializadores = True

    # ===== CONSTRUÇÃO CIVIL =====
    df_cc = df[df['SEGMENTO_PRODUTO'] == 'CONSTRUCAO CIVIL'].copy()

    # Grupos de gestão → taxas base
    taxas_externo = {'CB': 0.019, 'PRIMOR': 0.005, 'PRIMEX': 0.007, 'FINALIZA': 0.014}
    taxas_interno = {'CB': 0.002, 'PRIMOR': 0.002, 'PRIMEX': 0.002, 'FINALIZA': 0.002}
    bonus_externo = 0.001   # +0,10% por grupo atingido
    bonus_interno = 0.0005  # +0,05% por grupo atingido

    # GRUPO_COMERCIAL (coluna AA da planilha) é a base do filtro de grupo
    grupo_cb_termos    = ['CB CAL', 'CAL PINTURA', 'CERRO BRANCO', 'CAL CREM', 'CB/CAL']
    grupo_primor_termos = ['PRIMOR']
    grupo_primex_termos = ['PRIMEX']
    grupo_finaliza_termos = ['FINALIZA']

    def grupo_gestao(linha):
        l = str(linha).upper()
        if any(g in l for g in grupo_cb_termos):
            return 'CB'
        if any(g in l for g in grupo_primor_termos):
            return 'PRIMOR'
        if any(g in l for g in grupo_primex_termos):
            return 'PRIMEX'
        if any(g in l for g in grupo_finaliza_termos):
            return 'FINALIZA'
        return 'OUTROS'

    df_cc = df_cc.copy()
    # Usa GRUPO_COMERCIAL como fonte primária; fallback para GRUPO_COMERCIAL_LINHA_PRODUTOS e depois GRUPO
    def grupo_gestao_row(row):
        result = grupo_gestao(row['GRUPO_COMERCIAL'])
        if result == 'OUTROS':
            result = grupo_gestao(row['GRUPO_COMERCIAL_LINHA_PRODUTOS'])
        if result == 'OUTROS':
            result = grupo_gestao(row['GRUPO'])
        return result
    df_cc['GRUPO_GESTAO'] = df_cc.apply(grupo_gestao_row, axis=1)

    resultado = {}
    # Tabela de base de vendas para comparação (espelha a planilha)
    base_vendas = {}

    def vendas_por_grupo(df_rep):
        """Retorna dict com soma de VALOR_PRODUTO por grupo — igual à coluna V da planilha."""
        return {
            g: round(float(df_rep[df_rep['GRUPO_GESTAO'] == g]['VALOR_PRODUTO'].sum()), 2)
            for g in ['CB', 'PRIMOR', 'PRIMEX', 'FINALIZA']
        }

    def vendas_por_grupo_total(df_rep):
        """Retorna dict com soma de VALOR_TOTAL por grupo — usado para Adriano Born."""
        return {
            g: round(float(df_rep[df_rep['GRUPO_GESTAO'] == g]['VALOR_TOTAL'].sum()), 2)
            for g in ['CB', 'PRIMOR', 'PRIMEX', 'FINALIZA']
        }

    def comissao_ext_com_bonus(vendas, nome_chave):
        """Retorna (total, comissao_por_grupo) para a equipe externa."""
        total = 0.0
        por_grupo = {}
        for grupo, taxa in taxas_externo.items():
            venda_g = vendas.get(grupo, 0)
            taxa_final = taxa
            if considerar_potencializadores and nome_chave in metas_efetivas:
                meta_g = metas_efetivas[nome_chave].get(grupo, 0)
                if meta_g > 0 and venda_g >= meta_g:
                    taxa_final += bonus_externo
            val = venda_g * taxa_final
            por_grupo[grupo] = round(val, 2)
            total += val
        return total, por_grupo

    def comissao_int_com_bonus(vendas, nome_chave):
        """Calcula comissão interna com potencializador se metas disponíveis."""
        total = 0.0
        for grupo, taxa in taxas_interno.items():
            venda_g = vendas.get(grupo, 0)
            taxa_final = taxa
            if considerar_potencializadores and nome_chave in metas_efetivas:
                meta_g = metas_efetivas[nome_chave].get(grupo, 0)
                if meta_g > 0 and venda_g >= meta_g:
                    taxa_final += bonus_interno
            total += venda_g * taxa_final
        return total

    # ---- Vinculação: representante externo (REPNOME exato do BD) → interno Matriz ----
    # Cada chave é uma substring do REPNOME no BD
    VINCULO_INT_MATRIZ = {
        'RODRIGO CHAVES CRUZ (FRONTEIRA)': 'HELENA VARGAS MARQUES',
        'RODRIGO CHAVES CRUZ (PLANALTO)':  'VAGNER MOREIRA PAZ',
        'GLAUBER BRITO DA PAIXAO':          'VAGNER MOREIRA PAZ',
        'JAKLAINY DUARTE LEMOS':            None,   # sem interno vinculado
        'LUIS AURELIO FERREIRA MACIEL':     'HELENA VARGAS MARQUES',
        'DANIEL MARQUES MOREIRA':           'VAGNER MOREIRA PAZ',
        'JONATHAN SOARES BUENO':            None,
        'JONATHAN S BUENO (LITORAL)':       None,
        'GUILHERME FREITAS ILHA':           'HELENA VARGAS MARQUES',
        'GUILHERME F ILHA (METROPOLITANA 3)': None,
        'DANIEL M MOREIRA (METROPOLITANA 1)': None,
        'DANIEL M MOREIRA (METROPOLITANA 3)': None,
    }

    # Nomes que geram comissão para a Jocelaine (0,01%) — todos com vinc interno
    # e também sem interno (base é todos os externos com interno na metodologia)
    REPS_BASE_JOCELAINE = [k for k, v in VINCULO_INT_MATRIZ.items() if v is not None]

    # Regiões MPA (0,03% sobre vendas desses reps nessas regiões)
    REP_MPA_TERMOS = [
        'JAKLAINY DUARTE LEMOS',
        'JONATHAN SOARES BUENO', 'JONATHAN S BUENO',
        'GUILHERME F ILHA (METROPOLITANA 3)',
        'DANIEL M MOREIRA (METROPOLITANA 1)',
    ]

    # Potencializador Agner: 1,5% jul/2025, -0,05%/mês, mín 1,05%
    meses_desde_jul2025 = max(0, (data_inicio_dt.year - 2025) * 12 + (data_inicio_dt.month - 7))
    taxa_potencializador_agner = max(0.015 - 0.0005 * meses_desde_jul2025, 0.0105)

    # ---- 1. Vendedores Externos CC ----
    vendedores_internos_acum = {
        'HELENA VARGAS MARQUES': {'total': 0.0, 'detalhamento': []},
        'VAGNER MOREIRA PAZ':    {'total': 0.0, 'detalhamento': []},
    }
    base_jocelaine_vendas = 0.0
    base_mpa_vendas = 0.0
    total_comissao_primex = 0.0  # base para Marco Alan Lopes (10%)

    for rep_chave, vinc_int in VINCULO_INT_MATRIZ.items():
        # Inclui vendas diretas (REPRESENTANTE) + vendas de sub-representantes (REPRESENTANTE_MASTER)
        mask_rep = df_cc['REPRESENTANTE'].str.contains(rep_chave, na=False, regex=False)
        mask_master = df_cc['REPRESENTANTE_MASTER'].str.contains(rep_chave, na=False, regex=False)
        df_rep = df_cc[mask_rep | mask_master]
        if df_rep.empty:
            continue
        vendas = vendas_por_grupo(df_rep)
        chave_meta = f"{periodo_chave}{rep_chave}"
        comissao_rep, comissao_grupos = comissao_ext_com_bonus(vendas, chave_meta)

        base_vendas[rep_chave] = vendas
        total_comissao_primex += comissao_grupos.get('PRIMEX', 0.0)
        resultado[rep_chave] = {
            'comissao': round(comissao_rep, 2),
            'comissao_por_grupo': comissao_grupos,
            'vendas_por_grupo': vendas,
            'vendedor_interno': vinc_int,
            'tipo': 'Vendedor Externo CC'
        }

        # Acumula para interno Matriz com detalhamento por grupo
        if vinc_int in vendedores_internos_acum:
            comissao_int = comissao_int_com_bonus(vendas, chave_meta)
            # Calcula comissão por grupo (considerando potencializador se aplicável)
            comissao_por_grupo = {}
            for grupo, taxa in taxas_interno.items():
                venda_g = vendas.get(grupo, 0)
                taxa_final = taxa
                if considerar_potencializadores and chave_meta in metas_efetivas:
                    meta_g = metas_efetivas[chave_meta].get(grupo, 0)
                    if meta_g > 0 and venda_g >= meta_g:
                        taxa_final += bonus_interno
                comissao_por_grupo[grupo] = round(venda_g * taxa_final, 2)
            vendedores_internos_acum[vinc_int]['total'] += comissao_int
            vendedores_internos_acum[vinc_int]['detalhamento'].append({
                'representante_externo': rep_chave,
                'comissao_por_grupo': comissao_por_grupo,
                'comissao': round(comissao_int, 2),
            })
            base_jocelaine_vendas += sum(vendas.values())

        # Acumula base MPA se for rep MPA
        if any(t in rep_chave for t in REP_MPA_TERMOS):
            base_mpa_vendas += sum(vendas.values())

    # Agner: comissão igual aos demais reps (taxas_externo por grupo + potencializador) * 1.05 final
    df_agner = df_cc[df_cc['REPRESENTANTE'].str.contains('AGNER', na=False)]
    df_agner_nao_atm = df_agner[~df_agner['EMPRESAFILIAL'].str.contains('ATM', na=False)]
    total_agner = df_agner['VALOR_PRODUTO'].sum()
    total_agner_matriz = df_agner_nao_atm['VALOR_PRODUTO'].sum()
    proporcao_agner_matriz = (total_agner_matriz / total_agner) if total_agner > 0 else 0
    vendas_agner = vendas_por_grupo(df_agner)
    comissao_agner_base, comissao_grupos_agner = comissao_ext_com_bonus(vendas_agner, f"{periodo_chave}AGNER LORETO WALMRATH")
    # Adicional CARBOMAX: SUMIFS(V:V, K:K, AGNER, AA:AA, "CARBOMAX") * 0,8%
    venda_agner_carbomax = df_agner[df_agner['GRUPO_COMERCIAL'].str.contains('CARBOMAX', na=False)]['VALOR_PRODUTO'].sum()
    comissao_agner_base += venda_agner_carbomax * 0.008
    comissao_agner = comissao_agner_base * 1.05
    total_comissao_primex += comissao_grupos_agner.get('PRIMEX', 0.0)
    comissao_int_agner_total = comissao_int_com_bonus(vendas_agner, f"{periodo_chave}AGNER LORETO WALMRATH")
    comissao_int_agner_proporcional = comissao_int_agner_total * proporcao_agner_matriz
    agner_int_helena = comissao_int_agner_proporcional / 2
    vendedores_internos_acum['HELENA VARGAS MARQUES']['total'] += agner_int_helena
    vendedores_internos_acum['HELENA VARGAS MARQUES']['detalhamento'].append({
        'representante_externo': 'AGNER LORETO WALMRATH',
        'comissao_por_grupo': {g: round(vendas_agner.get(g, 0) * taxas_interno[g] * proporcao_agner_matriz / 2, 2) for g in taxas_interno},
        'comissao': round(agner_int_helena, 2),
    })
    jocelaine_agner = comissao_int_agner_proporcional / 2

    resultado['AGNER LORETO WALMRATH'] = {
        'comissao': round(float(comissao_agner), 2),
        'comissao_base': round(float(comissao_agner_base), 2),
        'comissao_por_grupo': comissao_grupos_agner,
        'vendas_por_grupo': vendas_agner,
        'venda_carbomax': round(float(venda_agner_carbomax), 2),
        'tipo': 'Vendedor Externo CC'
    }

    # ---- 2. Adriano Born ----
    df_adriano = df_cc[df_cc['REPRESENTANTE'].str.contains('ADRIANO L. BORN|ADRIANO BORN', na=False, regex=True)]
    venda_adriano = df_adriano['VALOR_TOTAL'].sum()
    chave_adriano = f"{periodo_chave}ADRIANO L. BORN REPRESENTACOES EIRELI"
    try:
        metas_adriano_qs = Meta.objects.filter(
            representante__nome__icontains='Adriano Born',
            segmento='CONSTRUCAO CIVIL',
            data_meta__range=[dataInicio, dataFim]
        )
        meta_adriano = sum(float(m.valor) for m in metas_adriano_qs)
    except Exception:
        meta_adriano = 0
    # Fallback: soma todos os grupos de metas_efetivas para o Adriano
    if meta_adriano == 0:
        _metas_adriano_grupos = metas_efetivas.get(chave_adriano, {})
        meta_adriano = sum(_metas_adriano_grupos.values()) if _metas_adriano_grupos else 0
    pct_atingido = (venda_adriano / meta_adriano * 100) if meta_adriano > 0 else 0
    if pct_atingido >= 120:
        taxa_adriano = 0.05
    elif pct_atingido >= 100:
        taxa_adriano = 0.04
    elif pct_atingido >= 50:
        taxa_adriano = 0.03
    else:
        taxa_adriano = 0.02
    # Comissão interna Vagner via Adriano Born (0,2%/grupo com potencializador)
    vendas_adriano_grupos = vendas_por_grupo_total(df_adriano)
    comissao_int_adriano = comissao_int_com_bonus(vendas_adriano_grupos, chave_adriano)
    comissao_pg_adriano = {}
    for grupo, taxa in taxas_interno.items():
        venda_g = vendas_adriano_grupos.get(grupo, 0)
        taxa_final = taxa
        if considerar_potencializadores and chave_adriano in metas_efetivas:
            meta_g = metas_efetivas[chave_adriano].get(grupo, 0)
            if meta_g > 0 and venda_g >= meta_g:
                taxa_final += bonus_interno
        comissao_pg_adriano[grupo] = round(venda_g * taxa_final, 2)

    # Comissão por grupo à taxa externa (para Marco Alan Lopes / debug) — com potencializador
    _, comissao_ext_pg_adriano = comissao_ext_com_bonus(vendas_adriano_grupos, chave_adriano)

    resultado['ADRIANO L. BORN REPRESENTACOES EIRELI'] = {
        'comissao': round(float(venda_adriano * taxa_adriano), 2),
        'taxa_aplicada': taxa_adriano,
        'percentual_meta': round(pct_atingido, 2),
        'venda_total': round(float(venda_adriano), 2),
        'vendas_por_grupo': vendas_adriano_grupos,
        'comissao_por_grupo_externo': comissao_ext_pg_adriano,
        'tipo': 'Representante Externo CC'
    }

    vendedores_internos_acum['VAGNER MOREIRA PAZ']['total'] += comissao_int_adriano
    vendedores_internos_acum['VAGNER MOREIRA PAZ']['detalhamento'].append({
        'representante_externo': 'ADRIANO L. BORN REPRESENTACOES EIRELI',
        'comissao_por_grupo': comissao_pg_adriano,
        'comissao': round(comissao_int_adriano, 2),
    })
    base_jocelaine_vendas += sum(vendas_adriano_grupos.values())
    # Adriano também entra na base PRIMEX para Marco Alan Lopes (com potencializador se aplicável)
    total_comissao_primex += comissao_ext_pg_adriano.get('PRIMEX', 0.0)

    # ---- 3. Vendedores Internos Matriz ----
    for nome, data in vendedores_internos_acum.items():
        resultado[nome] = {
            'comissao': round(data['total'], 2),
            'detalhamento': data['detalhamento'],
            'tipo': 'Vendedor Interno Matriz CC'
        }

    # ---- 4. Jocelaine (Auxiliar de Vendas Matriz) ----
    comissao_jocelaine = base_jocelaine_vendas * 0.0001 + jocelaine_agner
    resultado['JOCELAINE FARIAS BAHU'] = {
        'comissao': round(comissao_jocelaine, 2),
        'base_vendas': round(float(base_jocelaine_vendas), 2),
        'tipo': 'Auxiliar Vendas Matriz CC'
    }

    # ---- 4b. Marco Alan Lopes — 10% do total de comissões PRIMEX ----
    resultado['MARCO ALAN LOPES'] = {
        'comissao': round(total_comissao_primex * 0.10, 2),
        'base_primex': round(total_comissao_primex, 2),
        'base_primex_breakdown': {k: round(v['comissao_por_grupo'].get('PRIMEX', 0.0), 2) for k, v in resultado.items() if isinstance(v, dict) and 'comissao_por_grupo' in v},
        'adriano_primex': round(comissao_ext_pg_adriano.get('PRIMEX', 0.0), 2),
        'tipo': 'Comissão PRIMEX CC'
    }

    # ---- 5. Marina Gabrielly Pereira (MPA) ----
    df_quero_quero = df[df['CLIENTE_NOME'].str.contains('QUERO', na=False)]
    venda_quero_quero = df_quero_quero['VALOR_PRODUTO'].sum()
    venda_mpa = base_mpa_vendas
    comissao_marina = venda_quero_quero * 0.001 + venda_mpa * 0.0003
    resultado['MARINA GABRIELLY PEREIRA'] = {
        'comissao': round(float(comissao_marina), 2),
        'venda_quero_quero': round(float(venda_quero_quero), 2),
        'venda_mpa': round(float(venda_mpa), 2),
        'tipo': 'Vendedor Interno MPA'
    }

    # ---- 6. Vendedores Internos ATM ----
    REP_ATM = {
        'FRANCISCO MOREIRA GUIMARAES':          'ALEXANDRA PERUSSI',
        'E E MAUDA REPRES COMERCIAIS LTDA':     'MARIANE DO ROCIO MOREIRA',
        'RENOVA REPRESENTACOES LTDA':           'ALEXANDRA PERUSSI',
        'IMPERIO COMERCIO DE MOSAICO PORTUGUES': 'ALEXANDRA PERUSSI',
        # KRICAL é cliente (CLIENTE_NOME), não representante — tratado separadamente abaixo
        'ADRIANO MARQUES DIAS':                 'MARIANE DO ROCIO MOREIRA',
        'AGNER LORETO WALMRATH':                'MARIANE DO ROCIO MOREIRA',
        'RODRIGO CHAVES CRUZ (PLANALTO)':       'MARIANE DO ROCIO MOREIRA',
    }
    RMC_CIDADES = [
        'ALMIRANTE TAMANDARE-PR', 'ARAUCARIA-PR', 'BOCAIUVA DO SUL-PR', 'CAMPINA GRANDE DO SUL-PR',
        'CAMPO LARGO-PR', 'CAMPO MAGRO-PR', 'CERRO AZUL-PR', 'COLOMBO-PR', 'CURITIBA-PR',
        'FAZENDA RIO GRANDE-PR', 'ITAPERUCU-PR', 'PINHAIS-PR', 'QUATRO BARRAS-PR',
        'RIO BRANCO DO SUL-PR', 'SAO JOSE DOS PINHAIS-PR',
    ]

    atm_internos = {'ALEXANDRA PERUSSI': 0.0, 'MARIANE DO ROCIO MOREIRA': 0.0, 'DARCILEI DOS SANTOS': 0.0}

    # Filtra somente vendas faturadas pela filial ATM
    df_atm_fil = df_cc[df_cc['EMPRESAFILIAL'].str.contains('ATM', na=False)]

    # Máscaras de grupo para dolomita e cal sucro (busca em todas as colunas de grupo)
    _mask_dolomit = (
        df_cc['GRUPO_COMERCIAL'].str.contains('DOLOMIT', na=False) |
        df_cc['GRUPO_COMERCIAL_LINHA_PRODUTOS'].str.contains('DOLOMIT', na=False) |
        df_cc['GRUPO'].str.contains('DOLOMIT', na=False)
    )
    _mask_cal_sucro = (
        df_cc['GRUPO_COMERCIAL'].str.contains('CAL SUCRO', na=False) |
        df_cc['GRUPO_COMERCIAL_LINHA_PRODUTOS'].str.contains('CAL SUCRO', na=False) |
        df_cc['GRUPO'].str.contains('CAL SUCRO', na=False)
    )

    # 0,25% sobre reps externos vinculados
    # AGNER e RODRIGO PLANALTO: apenas vendas expedidas pela ATM (*)
    REP_ATM_SOMENTE_ATM = {'AGNER LORETO WALMRATH', 'RODRIGO CHAVES CRUZ (PLANALTO)'}
    for rep_ext, int_atm in REP_ATM.items():
        if rep_ext in REP_ATM_SOMENTE_ATM:
            df_rep_atm = df_atm_fil[df_atm_fil['REPRESENTANTE'].str.contains(rep_ext, na=False, regex=False)]
        else:
            df_rep_atm = df_cc[df_cc['REPRESENTANTE'].str.contains(rep_ext, na=False, regex=False)]
        atm_internos[int_atm] = atm_internos.get(int_atm, 0) + df_rep_atm['VALOR_PRODUTO'].sum() * 0.0025

    # Cal Sucro: 0,125% → 100% Mariane (todas as filiais)
    df_cal_sucro = df_cc[_mask_cal_sucro]
    atm_internos['MARIANE DO ROCIO MOREIRA'] += df_cal_sucro['VALOR_PRODUTO'].sum() * 0.00125

    # KRICAL: cliente tratado como rep ATM de Mariane — filtra por CLIENTE_NOME
    df_krical = df_cc[df_cc['CLIENTE_NOME'].str.contains('KRICAL', na=False)]
    atm_internos['MARIANE DO ROCIO MOREIRA'] += df_krical['VALOR_PRODUTO'].sum() * 0.0025

    # Termos de externos CC da Matriz (VINCULO_INT_MATRIZ + Adriano Born) — usados para excluir da dolomita
    def is_ext_cc_matriz(r):
        """Somente externos CC da Matriz (VINCULO_INT_MATRIZ + Adriano Born), não reps ATM."""
        termos_matriz = list(VINCULO_INT_MATRIZ.keys()) + ['ADRIANO']
        return any(t in r for t in termos_matriz)

    # Todos os termos de externos CC e reps ATM — usados para excluir do ATM Direto
    todos_ext_cc_termos = (
        list(VINCULO_INT_MATRIZ.keys()) +
        list(REP_ATM.keys()) +
        ['AGNER LORETO WALMRATH', 'ADRIANO']
    )

    def is_ext_cc(r):
        return any(t in r for t in todos_ext_cc_termos)

    # Para dolomita: excluir apenas reps com interno vinculado (v != None) + reps ATM
    # Reps com None em VINCULO_INT_MATRIZ (ex: GUILHERME F ILHA METROPOLITANA 3) não têm outro destino → incluídos
    _vinculo_com_interno = [k for k, v in VINCULO_INT_MATRIZ.items() if v is not None]
    todos_ext_cc_termos_dolomita = (
        _vinculo_com_interno +
        list(REP_ATM.keys()) +
        ['AGNER LORETO WALMRATH', 'ADRIANO']
    )

    def is_ext_cc_dolomita(r):
        return any(t in r for t in todos_ext_cc_termos_dolomita)

    # Dolomita: 0,5% por região (todas as filiais, excluindo externos CC e reps ATM por REPRESENTANTE)
    # RMC + Outros estados → Alexandra | Demais PR + SC + RS + UY + EX → Mariane
    df_dolomita_atm = df_cc[
        _mask_dolomit &
        ~df_cc['REPRESENTANTE'].apply(is_ext_cc_dolomita).astype(bool)
    ].copy()

    def classifica_regiao_atm(cidade):
        if any(c in cidade for c in RMC_CIDADES):
            return 'ALEXANDRA'  # RMC → Alexandra
        if cidade.endswith('-PR'):
            return 'MARIANE'    # Interior PR → Mariane
        if cidade.endswith(('-SC', '-RS', '-UY')):
            return 'MARIANE'    # SC, RS, UY → Mariane
        if cidade.endswith('-EX'):
            return 'MARIANE'    # Exterior → Mariane
        return 'ALEXANDRA'      # Outros estados → Alexandra

    df_dolomita_atm['REGIAO_ATM'] = df_dolomita_atm['CIDADE_FATURAMENTO'].apply(classifica_regiao_atm)
    atm_internos['ALEXANDRA PERUSSI'] += df_dolomita_atm[df_dolomita_atm['REGIAO_ATM'] == 'ALEXANDRA']['VALOR_PRODUTO'].sum() * 0.005
    atm_internos['MARIANE DO ROCIO MOREIRA'] += df_dolomita_atm[df_dolomita_atm['REGIAO_ATM'] == 'MARIANE']['VALOR_PRODUTO'].sum() * 0.005

    # ATM Direto: 0,5% (somente filial ATM, excluindo dolomita, cal sucro, externos CC e KRICAL por CLIENTE_NOME)
    _mask_krical_cliente = df_atm_fil['CLIENTE_NOME'].str.contains('KRICAL', na=False)
    df_atm_direto = df_atm_fil[
        ~_mask_dolomit.reindex(df_atm_fil.index, fill_value=False) &
        ~_mask_cal_sucro.reindex(df_atm_fil.index, fill_value=False) &
        ~df_atm_fil['REPRESENTANTE'].apply(is_ext_cc).astype(bool) &
        ~_mask_krical_cliente
    ].copy()
    df_atm_direto['REGIAO_ATM'] = df_atm_direto['CIDADE_FATURAMENTO'].apply(classifica_regiao_atm)
    atm_internos['ALEXANDRA PERUSSI'] += df_atm_direto[df_atm_direto['REGIAO_ATM'] == 'ALEXANDRA']['VALOR_PRODUTO'].sum() * 0.005
    atm_internos['MARIANE DO ROCIO MOREIRA'] += df_atm_direto[df_atm_direto['REGIAO_ATM'] == 'MARIANE']['VALOR_PRODUTO'].sum() * 0.005

    # Darcilei: 0,04% sobre total ATM filial CC excluindo apenas COFCO
    # (equivalente à fórmula =SUMIFS(V:V,B:B,"F08 - UP ATM",S:S,"CC") - SUMIFS(...,F:F,"*cofco*") da planilha)
    _mask_cofco = df_atm_fil['CLIENTE_NOME'].str.contains('COFCO', case=False, na=False)
    venda_up_atm = df_atm_fil[~_mask_cofco]['VALOR_PRODUTO'].sum()
    atm_internos['DARCILEI DOS SANTOS'] += venda_up_atm * 0.0004

    # DEBUG: breakdown por componente
    _atm_debug = {}
    for rep_ext, int_atm in REP_ATM.items():
        if rep_ext in REP_ATM_SOMENTE_ATM:
            _df = df_atm_fil[df_atm_fil['REPRESENTANTE'].str.contains(rep_ext, na=False, regex=False)]
        else:
            _df = df_cc[df_cc['REPRESENTANTE'].str.contains(rep_ext, na=False, regex=False)]
        _atm_debug[f'025_{rep_ext}'] = round(float(_df['VALOR_PRODUTO'].sum() * 0.0025), 2)
    # KRICAL: filtrado por CLIENTE_NOME
    _atm_debug['025_KRICAL DIST DE MAT DE CONSTRUCAO EIRELI'] = round(float(df_krical['VALOR_PRODUTO'].sum() * 0.0025), 2)
    _atm_debug['cal_sucro_base'] = round(float(df_cal_sucro['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['cal_sucro_comissao'] = round(float(df_cal_sucro['VALOR_PRODUTO'].sum() * 0.00125), 2)
    _atm_debug['dolomita_alexandra_base'] = round(float(df_dolomita_atm[df_dolomita_atm['REGIAO_ATM'] == 'ALEXANDRA']['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['dolomita_mariane_base'] = round(float(df_dolomita_atm[df_dolomita_atm['REGIAO_ATM'] == 'MARIANE']['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['atm_direto_alexandra_base'] = round(float(df_atm_direto[df_atm_direto['REGIAO_ATM'] == 'ALEXANDRA']['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['atm_direto_mariane_base'] = round(float(df_atm_direto[df_atm_direto['REGIAO_ATM'] == 'MARIANE']['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['venda_up_atm'] = round(float(venda_up_atm), 2)
    _atm_debug['darcilei_004_comissao'] = round(float(venda_up_atm * 0.0004), 2)
    # Breakdown: RMC vs outros estados (Alexandra)
    _mask_rmc_dol = df_dolomita_atm['CIDADE_FATURAMENTO'].apply(lambda c: any(rc in c for rc in RMC_CIDADES) if isinstance(c, str) else False)
    _alex_dol = df_dolomita_atm['REGIAO_ATM'] == 'ALEXANDRA'
    _atm_debug['dolomita_alexandra_rmc_base'] = round(float(df_dolomita_atm[_alex_dol & _mask_rmc_dol]['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['dolomita_alexandra_outros_base'] = round(float(df_dolomita_atm[_alex_dol & ~_mask_rmc_dol]['VALOR_PRODUTO'].sum()), 2)
    _mask_rmc_dir = df_atm_direto['CIDADE_FATURAMENTO'].apply(lambda c: any(rc in c for rc in RMC_CIDADES) if isinstance(c, str) else False)
    _alex_dir = df_atm_direto['REGIAO_ATM'] == 'ALEXANDRA'
    _atm_debug['atm_direto_alexandra_rmc_base'] = round(float(df_atm_direto[_alex_dir & _mask_rmc_dir]['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['atm_direto_alexandra_outros_base'] = round(float(df_atm_direto[_alex_dir & ~_mask_rmc_dir]['VALOR_PRODUTO'].sum()), 2)
    # Total ATM filial bruto (sem filtro)
    _atm_debug['atm_fil_total_bruto'] = round(float(df_atm_fil['VALOR_PRODUTO'].sum()), 2)
    # Breakdown do ATM filial por componente para reconciliação com planilha
    _mask_cal_sucro_atm2 = _mask_cal_sucro.reindex(df_atm_fil.index, fill_value=False)
    _mask_dolomit_atm2 = _mask_dolomit.reindex(df_atm_fil.index, fill_value=False)
    _mask_ext_matriz_atm = df_atm_fil['REPRESENTANTE'].apply(is_ext_cc_matriz).astype(bool)
    _mask_ext_atm_reps = df_atm_fil['REPRESENTANTE'].apply(lambda r: any(t in r for t in list(REP_ATM.keys()))).astype(bool)
    _atm_debug['atm_fil_cal_sucro'] = round(float(df_atm_fil[_mask_cal_sucro_atm2]['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['atm_fil_dolomita'] = round(float(df_atm_fil[_mask_dolomit_atm2]['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['atm_fil_externos_cc_matriz'] = round(float(df_atm_fil[_mask_ext_matriz_atm]['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['atm_fil_reps_atm'] = round(float(df_atm_fil[_mask_ext_atm_reps & ~_mask_ext_matriz_atm]['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['atm_fil_sem_cofco'] = round(float(venda_up_atm), 2)
    _atm_debug['atm_fil_cofco_excluido'] = round(float(df_atm_fil[_mask_cofco]['VALOR_PRODUTO'].sum()), 2)
    _atm_debug['empresafilial_values'] = df_atm_fil['EMPRESAFILIAL'].value_counts().to_dict()
    # Top representantes em ATM direto (para identificar KRICAL pelo nome real)
    _atm_debug['atm_direto_top_reps'] = df_atm_direto.groupby('REPRESENTANTE')['VALOR_PRODUTO'].sum().nlargest(15).round(2).to_dict()
    _atm_debug['atm_direto_top_clientes'] = df_atm_direto.groupby('CLIENTE_NOME')['VALOR_PRODUTO'].sum().nlargest(20).round(2).to_dict()
    # Top clientes da dolomita (para identificar KRICAL como cliente)
    _atm_debug['dolomita_top_clientes'] = df_dolomita_atm.groupby('CLIENTE_NOME')['VALOR_PRODUTO'].sum().nlargest(15).round(2).to_dict()
    # Reps excluídos da dolomita com seus valores (para diagnóstico)
    _df_dol_excl = df_cc[_mask_dolomit & df_cc['REPRESENTANTE'].apply(is_ext_cc_dolomita).astype(bool)]
    _df_dol_excl_mariane = _df_dol_excl[_df_dol_excl['CIDADE_FATURAMENTO'].apply(classifica_regiao_atm) == 'MARIANE']
    _atm_debug['dolomita_excluida_mariane_por_rep'] = _df_dol_excl_mariane.groupby('REPRESENTANTE')['VALOR_PRODUTO'].sum().round(2).to_dict()
    # Dolomita somente da filial ATM (para comparar com dolomita total)
    _mask_dolomit_atm_only = _mask_dolomit.reindex(df_atm_fil.index, fill_value=False)
    df_dolomita_atm_fil_only = df_atm_fil[_mask_dolomit_atm_only & ~df_atm_fil['REPRESENTANTE'].apply(is_ext_cc_dolomita).astype(bool)]
    _atm_debug['dolomita_somente_filial_atm_total'] = round(float(df_dolomita_atm_fil_only['VALOR_PRODUTO'].sum()), 2)
    # Top cidades em atm_direto_outros_estados (Alexandra)
    _outros = df_atm_direto[_alex_dir & ~_mask_rmc_dir]
    _top_outros = _outros.groupby('CIDADE_FATURAMENTO')['VALOR_PRODUTO'].sum().nlargest(10).round(2).to_dict()
    _atm_debug['atm_direto_outros_top_cidades'] = _top_outros
    _atm_debug['alexandra_antes_maternidade'] = round(float(atm_internos['ALEXANDRA PERUSSI']), 2)
    _atm_debug['mariane_antes_maternidade'] = round(float(atm_internos['MARIANE DO ROCIO MOREIRA']), 2)
    _atm_debug['darcilei_antes_maternidade'] = round(float(atm_internos['DARCILEI DOS SANTOS']), 2)
    resultado['_atm_debug'] = _atm_debug

    # Licança Maternidade: comissão de Alexandra vai para Darcilei somente quando ativa
    if licenca_maternidade_alexandra:
        atm_internos['DARCILEI DOS SANTOS'] += atm_internos['ALEXANDRA PERUSSI']
        atm_internos['ALEXANDRA PERUSSI'] = 0.0

    for nome, val in atm_internos.items():
        resultado[nome] = {'comissao': round(val, 2), 'tipo': 'Vendedor Interno ATM'}

    # ---- 7. Marco Alan Lopes (Correa) CC ----
    # RS: soma de TODAS as filiais (inclusive ATM), mas apenas para reps CC cadastrados
    # (planilha inclui todas as filiais; exclui Agro reps como Everton/Ildomar que têm vendas CC-RS pontuais)
    _cc_rep_termos_rs = list(VINCULO_INT_MATRIZ.keys()) + list(REP_ATM.keys()) + ['ADRIANO L. BORN', 'ADRIANO BORN']
    def _is_cc_rep(r):
        return any(t in r for t in _cc_rep_termos_rs)

    df_sc = df_cc[df_cc['CIDADE_FATURAMENTO'].str.endswith('-SC', na=False)]
    _mask_yara_cc_rs = df_cc['CLIENTE_NOME'].str.contains('YARA', na=False)
    df_rs = df_cc[
        df_cc['CIDADE_FATURAMENTO'].str.endswith('-RS', na=False) &
        ~_mask_yara_cc_rs &
        df_cc['REPRESENTANTE'].apply(_is_cc_rep)
    ]
    venda_sc = df_sc['VALOR_PRODUTO'].sum()
    venda_rs = df_rs['VALOR_PRODUTO'].sum()
    comissao_sc = venda_sc * 0.005 if venda_sc >= 600000 else 3000.0
    comissao_rs = venda_rs * 0.0005
    # DEBUG: breakdown RS por filial para identificar discrepância com planilha
    _df_rs_sem_atm = df_rs[~df_rs['EMPRESAFILIAL'].str.contains('ATM', na=False)]
    _rs_debug = {
        'rs_total_cc': round(float(venda_rs), 2),
        'rs_por_filial': df_rs.groupby('EMPRESAFILIAL')['VALOR_PRODUTO'].sum().round(2).to_dict(),
        'rs_sem_atm': round(float(_df_rs_sem_atm['VALOR_PRODUTO'].sum()), 2),
        'rs_yara_excluido': round(float(df_cc[df_cc['CIDADE_FATURAMENTO'].str.endswith('-RS', na=False) & _mask_yara_cc_rs]['VALOR_PRODUTO'].sum()), 2),
        'rs_sem_atm_por_vendedor': _df_rs_sem_atm.groupby('REPRESENTANTE')['VALOR_PRODUTO'].sum().sort_values(ascending=False).round(2).to_dict(),
        'rs_sem_atm_por_vendedor_e_filial': {f"{r[0]} | {r[1]}": v for r, v in _df_rs_sem_atm.groupby(['REPRESENTANTE', 'EMPRESAFILIAL'])['VALOR_PRODUTO'].sum().sort_values(ascending=False).round(2).items()},
        'rs_sem_atm_top_clientes': _df_rs_sem_atm.groupby('CLIENTE_NOME')['VALOR_PRODUTO'].sum().nlargest(15).round(2).to_dict(),
        'sc_total_cc': round(float(venda_sc), 2),
        'sc_por_filial': df_sc.groupby('EMPRESAFILIAL')['VALOR_PRODUTO'].sum().round(2).to_dict(),
    }
    resultado['_marco_correa_debug'] = _rs_debug
    resultado['MARCO ANTONIO CORREA'] = {
        'comissao': round(comissao_sc + comissao_rs + 12500, 2),
        'comissao_sc': round(float(comissao_sc), 2),
        'venda_sc': round(float(venda_sc), 2),
        'comissao_rs': round(float(comissao_rs), 2),
        'venda_rs': round(float(venda_rs), 2),
        'fixo': 12500,
        'tipo': 'Comissão Marco Correa CC',
    }

    # ===== AGRONEGÓCIO =====
    df_agro = df[df['SEGMENTO_PRODUTO'] == 'AGRONEGOCIO'].copy()
    df_agro['GRUPO_COMERCIAL'] = df_agro['GRUPO_COMERCIAL'].fillna('').str.strip().str.upper()
    df_agro['GRUPO_COMERCIAL_LINHA_PRODUTOS'] = df_agro['GRUPO_COMERCIAL_LINHA_PRODUTOS'].fillna('').str.strip().str.upper()
    df_agro['REPRESENTANTE_MASTER'] = df_agro['REPRESENTANTE_MASTER'].fillna('').str.strip().str.upper()

    _mask_yara_agro    = df_agro['CLIENTE_NOME'].str.contains('YARA', na=False)
    _mask_cotrijal_agro = df_agro['CLIENTE_NOME'].str.contains('COTRIJAL', na=False)

    # ---- 1. Vendedor Interno Agro (Felinto Pazinato Neto) ----
    df_agro_oxido     = df_agro[df_agro['GRUPO_COMERCIAL'].str.contains('OXIDO', na=False)]
    df_agro_nao_oxido = df_agro[~df_agro['GRUPO_COMERCIAL'].str.contains('OXIDO', na=False)]
    comissao_int_agro = df_agro_nao_oxido['VALOR_PRODUTO'].sum() * 0.001 + df_agro_oxido['VALOR_PRODUTO'].sum() * 0.01
    resultado['FELINTO PAZINATO NETO'] = {
        'comissao': round(float(comissao_int_agro), 2),
        'tipo': 'Vendedor Interno Agronegócio'
    }

    # ---- 2. Ildomar e Everton ----
    # A planilha cria coluna "Representante Agro" via:
    #   =IF([@Segmento]="AGRONEGOCIO", XLOOKUP([@[Cidade Faturamento]], AR:AR, AS:AS), "")
    # Exclui YARA. Então: total_vendedor = SUMIFS por Representante Agro (excl YARA)
    # Fórmula comissão:
    #   comissao = total_vendedor * 0.8% + (total_agro - total_vendedor) * 0.1%
    #            = total_vendedor * 0.7% + total_agro * 0.1%
    import unicodedata

    def _norm_cidade(s):
        """Remove acentos e caixa alta para comparação consistente com a planilha."""
        nfkd = unicodedata.normalize('NFKD', str(s) if s else '')
        return nfkd.encode('ascii', 'ignore').decode('ascii').upper().strip()

    # Mapeamento Cidade Faturamento → Representante Agro (tabela "Apoio Base" AR:AS)
    _CIDADE_AGRO_REP_RAW = {
        'ALECRIM-RS': 'EVERTON MARQUES DORNELES',
        'CANDIDO GODOI-RS': 'EVERTON MARQUES DORNELES',
        'INDEPENDENCIA-RS': 'EVERTON MARQUES DORNELES',
        'NOVO MACHADO-RS': 'EVERTON MARQUES DORNELES',
        'PORTO LUCENA-RS': 'EVERTON MARQUES DORNELES',
        'PORTO MAUA-RS': 'EVERTON MARQUES DORNELES',
        'PORTO VERA CRUZ-RS': 'EVERTON MARQUES DORNELES',
        'SANTA ROSA-RS': 'EVERTON MARQUES DORNELES',
        'SANTO CRISTO-RS': 'EVERTON MARQUES DORNELES',
        'SAO JOSE DO INHACORA-RS': 'EVERTON MARQUES DORNELES',
        'TRES DE MAIO-RS': 'EVERTON MARQUES DORNELES',
        'TUCUNDUVA-RS': 'EVERTON MARQUES DORNELES',
        'TUPARENDI-RS': 'EVERTON MARQUES DORNELES',
        'BARRA DO GUARITA-RS': 'EVERTON MARQUES DORNELES',
        'BOA VISTA DO BURICA-RS': 'EVERTON MARQUES DORNELES',
        'BOM PROGRESSO-RS': 'EVERTON MARQUES DORNELES',
        'BRAGA-RS': 'EVERTON MARQUES DORNELES',
        'CAMPO NOVO-RS': 'EVERTON MARQUES DORNELES',
        'CRISSIUMAL-RS': 'EVERTON MARQUES DORNELES',
        'DERRUBADAS-RS': 'EVERTON MARQUES DORNELES',
        'DOUTOR MAURICIO CARDOSO-RS': 'EVERTON MARQUES DORNELES',
        'ESPERANCA DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'HORIZONTINA-RS': 'EVERTON MARQUES DORNELES',
        'HUMAITA-RS': 'EVERTON MARQUES DORNELES',
        'MIRAGUAI-RS': 'EVERTON MARQUES DORNELES',
        'NOVA CANDELARIA-RS': 'EVERTON MARQUES DORNELES',
        'REDENTORA-RS': 'EVERTON MARQUES DORNELES',
        'SAO MARTINHO-RS': 'EVERTON MARQUES DORNELES',
        'SEDE NOVA-RS': 'EVERTON MARQUES DORNELES',
        'TENENTE PORTELA-RS': 'EVERTON MARQUES DORNELES',
        'TIRADENTES DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'TRES PASSOS-RS': 'EVERTON MARQUES DORNELES',
        'VISTA GAUCHA-RS': 'EVERTON MARQUES DORNELES',
        'FREDERICO WESTPHALEN-RS': 'EVERTON MARQUES DORNELES',
        'ALPESTRE-RS': 'EVERTON MARQUES DORNELES',
        'AMETISTA DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'CAICARA-RS': 'EVERTON MARQUES DORNELES',
        'CONSTANTINA-RS': 'EVERTON MARQUES DORNELES',
        'CRISTAL DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'DOIS IRMAOS DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'ENGENHO VELHO-RS': 'EVERTON MARQUES DORNELES',
        'ERVAL SECO-RS': 'EVERTON MARQUES DORNELES',
        'GRAMADO DOS LOUREIROS-RS': 'EVERTON MARQUES DORNELES',
        'IRAI-RS': 'EVERTON MARQUES DORNELES',
        'LIBERATO SALZANO-RS': 'EVERTON MARQUES DORNELES',
        'NONOAI-RS': 'EVERTON MARQUES DORNELES',
        'NOVO TIRADENTES-RS': 'EVERTON MARQUES DORNELES',
        'NOVO XINGU-RS': 'EVERTON MARQUES DORNELES',
        'PALMITINHO-RS': 'EVERTON MARQUES DORNELES',
        'PINHEIRINHO DO VALE-RS': 'EVERTON MARQUES DORNELES',
        'PLANALTO-RS': 'EVERTON MARQUES DORNELES',
        'RIO DOS INDIOS-RS': 'EVERTON MARQUES DORNELES',
        'RODEIO BONITO-RS': 'EVERTON MARQUES DORNELES',
        'RONDINHA-RS': 'EVERTON MARQUES DORNELES',
        'SEBERI-RS': 'EVERTON MARQUES DORNELES',
        'TAQUARUCU DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'TRES PALMEIRAS-RS': 'EVERTON MARQUES DORNELES',
        'TRINDADE DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'VICENTE DUTRA-RS': 'EVERTON MARQUES DORNELES',
        'VISTA ALEGRE-RS': 'EVERTON MARQUES DORNELES',
        'ARATIBA-RS': 'EVERTON MARQUES DORNELES',
        'AUREA-RS': 'EVERTON MARQUES DORNELES',
        'BARAO DE COTEGIPE-RS': 'EVERTON MARQUES DORNELES',
        'BARRA DO RIO AZUL-RS': 'EVERTON MARQUES DORNELES',
        'BENJAMIN CONSTANT DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'CAMPINAS DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'CARLOS GOMES-RS': 'EVERTON MARQUES DORNELES',
        'CENTENARIO-RS': 'EVERTON MARQUES DORNELES',
        'CRUZALTENSE-RS': 'EVERTON MARQUES DORNELES',
        'ENTRE RIOS DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'EREBANGO-RS': 'EVERTON MARQUES DORNELES',
        'ERECHIM-RS': 'EVERTON MARQUES DORNELES',
        'ERVAL GRANDE-RS': 'EVERTON MARQUES DORNELES',
        'ESTACAO-RS': 'EVERTON MARQUES DORNELES',
        'FAXINALZINHO-RS': 'EVERTON MARQUES DORNELES',
        'FLORIANO PEIXOTO-RS': 'EVERTON MARQUES DORNELES',
        'GAURAMA-RS': 'EVERTON MARQUES DORNELES',
        'GETULIO VARGAS-RS': 'EVERTON MARQUES DORNELES',
        'IPIRANGA DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'ITATIBA DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'JACUTINGA-RS': 'EVERTON MARQUES DORNELES',
        'MARCELINO RAMOS-RS': 'EVERTON MARQUES DORNELES',
        'MARIANO MORO-RS': 'EVERTON MARQUES DORNELES',
        'PAULO BENTO-RS': 'EVERTON MARQUES DORNELES',
        'PONTE PRETA-RS': 'EVERTON MARQUES DORNELES',
        'QUATRO IRMAOS-RS': 'EVERTON MARQUES DORNELES',
        'SAO VALENTIM-RS': 'EVERTON MARQUES DORNELES',
        'SEVERIANO DE ALMEIDA-RS': 'EVERTON MARQUES DORNELES',
        'TRES ARROIOS-RS': 'EVERTON MARQUES DORNELES',
        'VIADUTOS-RS': 'EVERTON MARQUES DORNELES',
        'BARRACAO-RS': 'EVERTON MARQUES DORNELES',
        'CACIQUE DOBLE-RS': 'EVERTON MARQUES DORNELES',
        'IBIACA-RS': 'EVERTON MARQUES DORNELES',
        'MACHADINHO-RS': 'EVERTON MARQUES DORNELES',
        'MAXIMILIANO DE ALMEIDA-RS': 'EVERTON MARQUES DORNELES',
        'PAIM FILHO-RS': 'EVERTON MARQUES DORNELES',
        'SANANDUVA-RS': 'EVERTON MARQUES DORNELES',
        'SANTO EXPEDITO DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'SAO JOAO DA URTIGA-RS': 'EVERTON MARQUES DORNELES',
        'SAO JOSE DO OURO-RS': 'EVERTON MARQUES DORNELES',
        'TUPANCI DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'CAIBATE-RS': 'EVERTON MARQUES DORNELES',
        'CAMPINA DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'CERRO LARGO-RS': 'EVERTON MARQUES DORNELES',
        'GUARANI DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'MATO QUEIMADO-RS': 'EVERTON MARQUES DORNELES',
        'PORTO XAVIER-RS': 'EVERTON MARQUES DORNELES',
        'ROQUE GONZALES-RS': 'EVERTON MARQUES DORNELES',
        'SALVADOR DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'SAO PAULO DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'SAO PEDRO DO BUTIA-RS': 'EVERTON MARQUES DORNELES',
        'SETE DE SETEMBRO-RS': 'EVERTON MARQUES DORNELES',
        'BOSSOROCA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CATUIPE-RS': 'EVERTON MARQUES DORNELES',
        'DEZESSEIS DE NOVEMBRO-RS': 'EVERTON MARQUES DORNELES',
        'ENTRE-IJUIS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'EUGENIO DE CASTRO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'GIRUA-RS': 'EVERTON MARQUES DORNELES',
        'PIRAPO-RS': 'EVERTON MARQUES DORNELES',
        'ROLADOR-RS': 'EVERTON MARQUES DORNELES',
        'SANTO ANGELO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SANTO ANTONIO DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'SAO LUIZ GONZAGA-RS': 'EVERTON MARQUES DORNELES',
        'SAO MIGUEL DAS MISSOES-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SAO NICOLAU-RS': 'EVERTON MARQUES DORNELES',
        'SENADOR SALGADO FILHO-RS': 'EVERTON MARQUES DORNELES',
        'UBIRETAMA-RS': 'EVERTON MARQUES DORNELES',
        'VITORIA DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'AJURICABA-RS': 'EVERTON MARQUES DORNELES',
        'ALEGRIA-RS': 'EVERTON MARQUES DORNELES',
        'AUGUSTO PESTANA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'BOZANO-RS': 'EVERTON MARQUES DORNELES',
        'CHIAPETTA-RS': 'EVERTON MARQUES DORNELES',
        'CONDOR-RS': 'EVERTON MARQUES DORNELES',
        'CORONEL BARROS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CORONEL BICACO-RS': 'EVERTON MARQUES DORNELES',
        'IJUI-RS': 'ILDOMAR DA FONTE CARVALHO',
        'INHACORA-RS': 'EVERTON MARQUES DORNELES',
        'NOVA RAMADA-RS': 'EVERTON MARQUES DORNELES',
        'PANAMBI-RS': 'EVERTON MARQUES DORNELES',
        'PEJUCARA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SANTO AUGUSTO-RS': 'EVERTON MARQUES DORNELES',
        'SAO VALERIO DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'ALMIRANTE TAMANDARE DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'BARRA FUNDA-RS': 'EVERTON MARQUES DORNELES',
        'BOA VISTA DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'CARAZINHO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CERRO GRANDE-RS': 'EVERTON MARQUES DORNELES',
        'CHAPADA-RS': 'EVERTON MARQUES DORNELES',
        'COQUEIROS DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'JABOTICABA-RS': 'EVERTON MARQUES DORNELES',
        'LAJEADO DO BUGRE-RS': 'EVERTON MARQUES DORNELES',
        'NOVA BOA VISTA-RS': 'EVERTON MARQUES DORNELES',
        'NOVO BARREIRO-RS': 'EVERTON MARQUES DORNELES',
        'PALMEIRA DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'PINHAL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SAGRADA FAMILIA-RS': 'EVERTON MARQUES DORNELES',
        #'SANTO ANTONIO DO PLANALTO-RS': 'EVERTON MARQUES DORNELES',
        'SAO JOSE DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'SAO PEDRO DAS MISSOES-RS': 'EVERTON MARQUES DORNELES',
        'SARANDI-RS': 'EVERTON MARQUES DORNELES',
        'AGUA SANTA-RS': 'EVERTON MARQUES DORNELES',
        'CAMARGO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CASCA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CASEIROS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CHARRUA-RS': 'EVERTON MARQUES DORNELES',
        'CIRIACO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'COXILHA-RS': 'EVERTON MARQUES DORNELES',
        'DAVID CANABARRO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ERNESTINA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'GENTIL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'IBIRAIARAS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'MARAU-RS': 'ILDOMAR DA FONTE CARVALHO',
        'MATO CASTELHANO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'MULITERNO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'NICOLAU VERGUEIRO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PASSO FUNDO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PONTAO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'RONDA ALTA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SANTA CECILIA DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SANTO ANTONIO DO PALMA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SAO DOMINGOS DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SERTAO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'TAPEJARA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'VANINI-RS': 'ILDOMAR DA FONTE CARVALHO',
        'VILA LANGARO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'VILA MARIA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ALTO ALEGRE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'BOA VISTA DO CADEADO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'BOA VISTA DO INCRA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CAMPOS BORGES-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CRUZ ALTA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ESPUMOSO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'FORTALEZA DOS VALOS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'IBIRUBA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'JACUIZINHO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'JOIA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'QUINZE DE NOVEMBRO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SALDANHA MARINHO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SALTO DO JACUI-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SANTA BARBARA DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'NAO-ME-TOQUE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'COLORADO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'LAGOA DOS TRES CANTOS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SELBACH-RS': 'ILDOMAR DA FONTE CARVALHO',
        'TAPERA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'TIO HUGO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'VICTOR GRAEFF-RS': 'ILDOMAR DA FONTE CARVALHO',
        'BARROS CASSAL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'FONTOURA XAVIER-RS': 'ILDOMAR DA FONTE CARVALHO',
        'IBIRAPUITA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'LAGOAO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'MORMACO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SAO JOSE DO HERVAL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SOLEDADE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'TUNAS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CAPAO DO CIPO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ITACURUBI-RS': 'EVERTON MARQUES DORNELES',
        'JARI-RS': 'ILDOMAR DA FONTE CARVALHO',
        'JULIO DE CASTILHOS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PINHAL GRANDE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'QUEVEDOS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SANTIAGO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'TUPANCIRETA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'UNISTALDA-RS': 'EVERTON MARQUES DORNELES',
        #'CRUZEIRO DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'CACEQUI-RS': 'EVERTON MARQUES DORNELES',
        'DILERMANDO DE AGUIAR-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ITAARA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'JAGUARI-RS': 'EVERTON MARQUES DORNELES',
        'MATA-RS': 'EVERTON MARQUES DORNELES',
        'NOVA ESPERANCA DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'SANTA MARIA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SAO MARTINHO DA SERRA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SAO PEDRO DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SAO SEPE-RS': 'EVERTON MARQUES DORNELES',
        'SAO VICENTE DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'TOROPI-RS': 'ILDOMAR DA FONTE CARVALHO',
        'VILA NOVA DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'AGUDO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'DONA FRANCISCA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'FAXINAL DO SOTURNO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'FORMIGUEIRO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'IVORA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'NOVA PALMA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'RESTINGA SECA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SAO JOAO DO POLESINE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SILVEIRA MARTINS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ARROIO DO TIGRE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CANDELARIA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ESTRELA VELHA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'GRAMADO XAVIER-RS': 'ILDOMAR DA FONTE CARVALHO',
        'HERVEIRAS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'IBARAMA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'LAGOA BONITA DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'MATO LEITAO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PASSA-SETE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SANTA CRUZ DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'SEGREDO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SINIMBU-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SOBRADINHO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'VALE DO SOL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'VENANCIO AIRES-RS': 'ILDOMAR DA FONTE CARVALHO',
        'VERA CRUZ-RS': 'EVERTON MARQUES DORNELES',
        'CACHOEIRA DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'CERRO BRANCO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'NOVO CABRAIS-RS': 'EVERTON MARQUES DORNELES',
        'PANTANO GRANDE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PARAISO DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'PASSO DO SOBRADO-RS': 'EVERTON MARQUES DORNELES',
        'RIO PARDO-RS': 'EVERTON MARQUES DORNELES',
        'ARAMBARE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'BARRA DO RIBEIRO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CAMAQUA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CERRO GRANDE DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CHUVISCA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'DOM FELICIANO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SENTINELA DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'TAPES-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ALEGRETE-RS': 'EVERTON MARQUES DORNELES',
        'BARRA DO QUARAI-RS': 'EVERTON MARQUES DORNELES',
        'GARRUCHOS-RS': 'EVERTON MARQUES DORNELES',
        'ITAQUI-RS': 'EVERTON MARQUES DORNELES',
        'MACAMBARA-RS': 'EVERTON MARQUES DORNELES',
        'MANOEL VIANA-RS': 'EVERTON MARQUES DORNELES',
        'QUARAI-RS': 'EVERTON MARQUES DORNELES',
        'SAO BORJA-RS': 'EVERTON MARQUES DORNELES',
        'SAO FRANCISCO DE ASSIS-RS': 'EVERTON MARQUES DORNELES',
        'URUGUAIANA-RS': 'EVERTON MARQUES DORNELES',
        'ROSARIO DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'SANTA MARGARIDA DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'SANTANA DO LIVRAMENTO-RS': 'EVERTON MARQUES DORNELES',
        'SAO GABRIEL-RS': 'EVERTON MARQUES DORNELES',
        'ACEGUA-RS': 'EVERTON MARQUES DORNELES',
        'BAGE-RS': 'EVERTON MARQUES DORNELES',
        'DOM PEDRITO-RS': 'EVERTON MARQUES DORNELES',
        'HULHA NEGRA-RS': 'EVERTON MARQUES DORNELES',
        'LAVRAS DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'AMARAL FERRADOR-RS': 'EVERTON MARQUES DORNELES',
        'CACAPAVA DO SUL-RS': 'EVERTON MARQUES DORNELES',
        'CANDIOTA-RS': 'EVERTON MARQUES DORNELES',
        'ENCRUZILHADA DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PINHEIRO MACHADO-RS': 'EVERTON MARQUES DORNELES',
        'PIRATINI-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SANTANA DA BOA VISTA-RS': 'EVERTON MARQUES DORNELES',
        'ARROIO DO PADRE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CANGUCU-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CAPAO DO LEAO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CERRITO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CRISTAL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'MORRO REDONDO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PEDRO OSORIO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PELOTAS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SAO LOURENCO DO SUL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'TURUCU-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ARROIO GRANDE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'HERVAL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'JAGUARAO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PEDRAS ALTAS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'CHUI-RS': 'ILDOMAR DA FONTE CARVALHO',
        'RIO GRANDE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SANTA VITORIA DO PALMAR-RS': 'ILDOMAR DA FONTE CARVALHO',
        'SAO JOSE DO NORTE-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PROGRESSO-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ANTA GORDA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'ILOPOLIS-RS': 'ILDOMAR DA FONTE CARVALHO',
        'MARIANA PIMENTEL-RS': 'ILDOMAR DA FONTE CARVALHO',
        'PUTINGA-RS': 'ILDOMAR DA FONTE CARVALHO',
        'TREINTA Y TRES-EX': 'ILDOMAR DA FONTE CARVALHO',
        # Cidades adicionadas (não estavam na tabela original)
        #'MOSTARDAS-RS': 'ILDOMAR DA FONTE CARVALHO',
        #'SANTO ANTONIO DA PATRULHA-RS': 'ILDOMAR DA FONTE CARVALHO',
        #'ALMIRANTE TAMANDARE-RS': 'EVERTON MARQUES DORNELES',
    }
    # Normaliza as chaves removendo acentos para match robusto com nomes do banco
    _CIDADE_AGRO_REP = {_norm_cidade(k): v for k, v in _CIDADE_AGRO_REP_RAW.items()}

    # Aplica XLOOKUP: Representante Agro = lookup por CIDADE_FATURAMENTO (excl YARA)
    df_agro_no_yara = df_agro[~_mask_yara_agro].copy()
    df_agro_no_yara['_rep_agro'] = (
        df_agro_no_yara['CIDADE_FATURAMENTO']
        .apply(lambda c: _CIDADE_AGRO_REP.get(_norm_cidade(c), ''))
    )

    # Total agro excl YARA (base para Ildomar/Everton)
    venda_agro_total = df_agro_no_yara['VALOR_PRODUTO'].sum()
    # Total agro geral incl YARA (base para Vergilino e parcela residual de Ildomar/Everton)
    venda_agro_total_geral = df_agro['VALOR_PRODUTO'].sum()

    _agro_debug = {}
    for nome_agro in ('ILDOMAR DA FONTE CARVALHO', 'EVERTON MARQUES DORNELES'):
        mask_rep = df_agro_no_yara['_rep_agro'] == nome_agro
        total_vendedor = df_agro_no_yara[mask_rep]['VALOR_PRODUTO'].sum()
        _agro_debug[f'{nome_agro}_total'] = round(float(total_vendedor), 2)

        # comissao = total_vendedor * 0.8% + (total_agro_geral - total_vendedor) * 0.1%
        #          = total_vendedor * 0.7% + total_agro_geral * 0.1%
        # Nota: $B$54 da planilha é o total agro GERAL (incl. YARA), não apenas excl. YARA
        comissao_var = total_vendedor * 0.007 + venda_agro_total_geral * 0.001
        resultado[nome_agro] = {
            'comissao': round(comissao_var + 8225, 2),
            'comissao_variavel': round(float(comissao_var), 2),
            'total_vendedor': round(float(total_vendedor), 2),
            'fixo': 8225,
            'tipo': 'Vendedor Externo Agronegócio'
        }

    # ---- 3. Vergilino Antonio Dutra ----
    _agro_debug['vergilino_base'] = round(float(venda_agro_total_geral), 2)

    resultado['VERGILINO ANTONIO DUTRA'] = {
        'comissao': round(venda_agro_total_geral * 0.0015 + 5747.50, 2),
        'comissao_variavel': round(float(venda_agro_total_geral * 0.0015), 2),
        'fixo': 5747.50,
        'tipo': 'Representante Externo Agronegócio'
    }

    # ---- Debug agro totais para comparação com planilha ----
    _agro_debug['cotrijal_total'] = round(float(df_agro[_mask_cotrijal_agro]['VALOR_PRODUTO'].sum()), 2)
    _agro_debug['yara_total']     = round(float(df_agro[_mask_yara_agro]['VALOR_PRODUTO'].sum()), 2)
    _agro_debug['oxidos_total']   = round(float(df_agro_oxido['VALOR_PRODUTO'].sum()), 2)
    _agro_debug['agro_total_excl_yara'] = round(float(venda_agro_total), 2)
    _agro_debug['agro_total_geral'] = round(float(venda_agro_total_geral), 2)
    # Todos os representantes presentes no agro (excl YARA e COTRIJAL) com totais
    _agro_debug['todos_reps_agro'] = (
        df_agro[~_mask_yara_agro & ~_mask_cotrijal_agro]
        .groupby('REPRESENTANTE')['VALOR_PRODUTO'].sum().round(2).to_dict()
    )
    # Vendas agro com REPRESENTANTE_MASTER preenchido: quem são os masters e sub-reps
    _agro_debug['agro_com_master_por_master'] = (
        df_agro[df_agro['REPRESENTANTE_MASTER'] != ''][~_mask_yara_agro]
        .groupby(['REPRESENTANTE_MASTER', 'REPRESENTANTE'])['VALOR_PRODUTO']
        .sum().round(2).reset_index()
        .rename(columns={'REPRESENTANTE_MASTER': 'master', 'REPRESENTANTE': 'sub_rep', 'VALOR_PRODUTO': 'valor'})
        .to_dict(orient='records')
    )
    # Cidades não mapeadas (para identificar lacunas no mapeamento)
    _agro_debug['cidades_nao_mapeadas'] = (
        df_agro_no_yara[df_agro_no_yara['_rep_agro'] == '']
        .groupby('CIDADE_FATURAMENTO')['VALOR_PRODUTO'].sum().round(2)
        .sort_values(ascending=False).head(20).to_dict()
    )
    # Total agro vendas diretas: REPRESENTANTE_MASTER vazio (sem estrutura master/sub-rep)
    _total_agro_vendas_diretas = df_agro[df_agro['REPRESENTANTE_MASTER'] == '']['VALOR_PRODUTO'].sum()
    _agro_debug['total_agro_geral'] = round(float(venda_agro_total_geral), 2)
    _agro_debug['total_agro_vendas_diretas'] = round(float(_total_agro_vendas_diretas), 2)

    # ---- Debug de diferenças vs planilha ----
    # 1) Breakdown agro por EMPRESAFILIAL → ajuda identificar se alguma filial entra/sai
    _agro_debug['agro_total_por_filial'] = (
        df_agro.groupby('EMPRESAFILIAL')['VALOR_PRODUTO'].sum().round(2).to_dict()
    )
    # 2) Breakdown agro por EMPRESAFILIAL excl YARA
    _agro_debug['agro_sem_yara_por_filial'] = (
        df_agro[~_mask_yara_agro].groupby('EMPRESAFILIAL')['VALOR_PRODUTO'].sum().round(2).to_dict()
    )
    # 3) Valor exato de ALMIRANTE TAMANDARE-RS no agro (Everton overshoot)
    _almirante = df_agro_no_yara[
        df_agro_no_yara['CIDADE_FATURAMENTO'].str.upper().str.contains('ALMIRANTE', na=False)
    ][['CIDADE_FATURAMENTO', 'CLIENTE_NOME', 'REPRESENTANTE', 'VALOR_PRODUTO']]
    _agro_debug['almirante_tamandare_detalhes'] = _almirante.to_dict(orient='records')
    _agro_debug['almirante_tamandare_total'] = round(float(_almirante['VALOR_PRODUTO'].sum()), 2)
    # 4) Cidades Ildomar com valor — mostra tudo mapeado e não-mapeado para Ildomar
    _agro_debug['ildomar_cidades_mapeadas'] = (
        df_agro_no_yara[df_agro_no_yara['_rep_agro'] == 'ILDOMAR DA FONTE CARVALHO']
        .groupby('CIDADE_FATURAMENTO')['VALOR_PRODUTO'].sum().round(2)
        .sort_values(ascending=False).to_dict()
    )
    # 4b) Cidades Everton com valor — espelho do Ildomar para comparar com a planilha
    _agro_debug['everton_cidades_mapeadas'] = (
        df_agro_no_yara[df_agro_no_yara['_rep_agro'] == 'EVERTON MARQUES DORNELES']
        .groupby('CIDADE_FATURAMENTO')['VALOR_PRODUTO'].sum().round(2)
        .sort_values(ascending=False).to_dict()
    )
    # 4c) Cotrijal por território — verifica se Cotrijal distorce o total de algum rep
    _mask_cotrijal_no_yara = df_agro_no_yara['CLIENTE_NOME'].str.contains('COTRIJAL', na=False)
    _agro_debug['cotrijal_everton'] = round(
        float(df_agro_no_yara[_mask_cotrijal_no_yara & (df_agro_no_yara['_rep_agro'] == 'EVERTON MARQUES DORNELES')]['VALOR_PRODUTO'].sum()), 2
    )
    _agro_debug['cotrijal_ildomar'] = round(
        float(df_agro_no_yara[_mask_cotrijal_no_yara & (df_agro_no_yara['_rep_agro'] == 'ILDOMAR DA FONTE CARVALHO')]['VALOR_PRODUTO'].sum()), 2
    )
    _agro_debug['everton_total_sem_cotrijal'] = round(
        float(df_agro_no_yara[~_mask_cotrijal_no_yara & (df_agro_no_yara['_rep_agro'] == 'EVERTON MARQUES DORNELES')]['VALOR_PRODUTO'].sum()), 2
    )
    # 5) Todas as cidades não mapeadas em RS (sem corte de valor) — para fechar gap vs planilha
    _df_nao_map = df_agro_no_yara[df_agro_no_yara['_rep_agro'] == '']
    _agro_debug['cidades_nao_mapeadas_gt100'] = (
        _df_nao_map
        .groupby('CIDADE_FATURAMENTO')['VALOR_PRODUTO'].sum().round(2)
        .pipe(lambda s: s[s > 100])
        .sort_values(ascending=False).to_dict()
    )
    _agro_debug['cidades_nao_mapeadas_rs_todas'] = (
        _df_nao_map[_df_nao_map['CIDADE_FATURAMENTO'].str.endswith('-RS', na=False)]
        .groupby('CIDADE_FATURAMENTO')['VALOR_PRODUTO'].sum().round(2)
        .sort_values(ascending=False).to_dict()
    )
    _agro_debug['cidades_nao_mapeadas_rs_total'] = round(
        float(_df_nao_map[_df_nao_map['CIDADE_FATURAMENTO'].str.endswith('-RS', na=False)]['VALOR_PRODUTO'].sum()), 2
    )
    # 5b) Cidades não mapeadas FORA do RS (SC, EX, etc.) — para identificar cidades de outros estados não listadas
    _mask_nao_rs = ~_df_nao_map['CIDADE_FATURAMENTO'].str.endswith('-RS', na=False)
    _agro_debug['cidades_nao_mapeadas_nao_rs'] = (
        _df_nao_map[_mask_nao_rs]
        .groupby('CIDADE_FATURAMENTO')['VALOR_PRODUTO'].sum().round(2)
        .sort_values(ascending=False).to_dict()
    )
    _agro_debug['cidades_nao_mapeadas_nao_rs_total'] = round(
        float(_df_nao_map[_mask_nao_rs]['VALOR_PRODUTO'].sum()), 2
    )
    _agro_debug['cidades_nao_mapeadas_total_geral'] = round(
        float(_df_nao_map['VALOR_PRODUTO'].sum()), 2
    )
    # 5c) Totais por estado nas cidades não mapeadas — localiza rapidamente onde está o gap
    _estado_nao_map = _df_nao_map['CIDADE_FATURAMENTO'].str.extract(r'-([A-Z]{2,3})$', expand=False).fillna('SEM_UF')
    _agro_debug['cidades_nao_mapeadas_por_estado'] = (
        _df_nao_map.assign(_uf=_estado_nao_map)
        .groupby('_uf')['VALOR_PRODUTO'].sum().round(2)
        .sort_values(ascending=False).to_dict()
    )
    # 5d) Detalhamento notas do Everton por CIDADE_FATURAMENTO + REPRESENTANTE (inclui negativos)
    _agro_debug['everton_detalhamento_notas'] = (
        df_agro_no_yara[df_agro_no_yara['_rep_agro'] == 'EVERTON MARQUES DORNELES']
        [['CIDADE_FATURAMENTO', 'REPRESENTANTE', 'NOTA_FISCAL', 'VALOR_PRODUTO']]
        .groupby(['CIDADE_FATURAMENTO', 'REPRESENTANTE'])['VALOR_PRODUTO']
        .agg(['sum', 'count']).round(2)
        .sort_values('sum', ascending=False)
        .reset_index()
        .rename(columns={'sum': 'total', 'count': 'qtd_notas'})
        .to_dict(orient='records')
    )
    # 6) Agro total por SEGMENTO_CLIENTE → útil para ver se planilha filtra algum segmento
    _agro_debug['agro_total_por_segmento_cliente'] = (
        df_agro.groupby('SEGMENTO_CLIENTE')['VALOR_PRODUTO'].sum().round(2)
        .sort_values(ascending=False).to_dict()
    )

    # ---- Debug gap vs planilha (planilha exclui YARA e chega em 4.489.962,40) ----
    # Hipótese: YARA tem devoluções (valor negativo) que puxam o total para baixo
    # 7) YARA agro: breakdown por NATUREZA_OPERACAO (vendas vs devoluções)
    _agro_debug['yara_agro_por_natureza'] = (
        df_agro[_mask_yara_agro]
        .groupby('NATUREZA_OPERACAO')['VALOR_PRODUTO'].sum().round(2)
        .sort_values(ascending=False).to_dict()
    )
    _agro_debug['yara_agro_total_liquido'] = round(float(df_agro[_mask_yara_agro]['VALOR_PRODUTO'].sum()), 2)
    _agro_debug['yara_agro_clientes'] = (
        df_agro[_mask_yara_agro]
        .groupby(['CLIENTE_NOME', 'NATUREZA_OPERACAO'])['VALOR_PRODUTO'].sum().round(2)
        .reset_index().sort_values('VALOR_PRODUTO', ascending=False)
        .to_dict(orient='records')
    )
    # 8) Agro excl YARA por NATUREZA_OPERACAO (devoluções podem explicar parte do gap)
    _agro_debug['agro_sem_yara_por_natureza'] = (
        df_agro[~_mask_yara_agro]
        .groupby('NATUREZA_OPERACAO')['VALOR_PRODUTO'].sum().round(2)
        .sort_values(ascending=False).to_dict()
    )
    _agro_debug['agro_total_excl_yara_calculado'] = round(float(df_agro[~_mask_yara_agro]['VALOR_PRODUTO'].sum()), 2)
    # Gap esperado vs planilha: planilha=4489962.40, nosso excl YARA=agro_total_excl_yara_calculado
    _agro_debug['gap_vs_planilha_excl_yara'] = round(4489962.40 - float(df_agro[~_mask_yara_agro]['VALOR_PRODUTO'].sum()), 2)

    resultado['_agro_debug'] = _agro_debug

    # ---- Debug: Somas por estado (CC e Agro) ----
    def _soma_por_estado(dataframe):
        estado = dataframe['CIDADE_FATURAMENTO'].str.extract(r'-([A-Z]{2,3})$', expand=False)
        return (
            dataframe.assign(_estado=estado)
            .groupby('_estado')['VALOR_PRODUTO'].sum().round(2)
            .sort_values(ascending=False).to_dict()
        )

    _mask_yara_cc = df_cc['CLIENTE_NOME'].str.contains('YARA', na=False)
    _debug_estados = {
        'cc_por_estado': _soma_por_estado(df_cc),
        'cc_sem_yara_por_estado': _soma_por_estado(df_cc[~_mask_yara_cc]),
        'cc_yara_por_estado': _soma_por_estado(df_cc[_mask_yara_cc]),
        'agro_por_estado': _soma_por_estado(df_agro),
        'agro_sem_yara_por_estado': _soma_por_estado(df_agro[~_mask_yara_agro]),
        'total_por_estado': _soma_por_estado(df),
    }

    # ---- Resumo consolidado: total por vendedor (agrupa regiões) + total geral ----
    import re as _re
    # Mapeia nomes abreviados/alternativos para o nome canônico
    _ALIASES = {
        'DANIEL M MOREIRA':   'DANIEL MARQUES MOREIRA',
        'GUILHERME F ILHA':   'GUILHERME FREITAS ILHA',
        'JONATHAN S BUENO':   'JONATHAN SOARES BUENO',
    }

    def _nome_base(nome):
        """Remove sufixos de região entre parênteses, depois aplica alias."""
        sem_regiao = _re.sub(r'\s*\(.*?\)\s*$', '', nome).strip()
        return _ALIASES.get(sem_regiao, sem_regiao)

    _chaves_debug = {k for k in resultado if k.startswith('_')}
    _resumo = {}
    for nome, dados in resultado.items():
        if nome in _chaves_debug:
            continue
        if not isinstance(dados, dict) or 'comissao' not in dados:
            continue
        base = _nome_base(nome)
        _resumo[base] = round(_resumo.get(base, 0.0) + float(dados['comissao']), 2)

    _total_geral = round(sum(_resumo.values()), 2)

    return JsonResponse({
        'comissoes': resultado,
        'resumo_por_vendedor': dict(sorted(_resumo.items())),
        'total_geral': _total_geral,
        'base_vendas_cc': base_vendas,
        'debug_estados': _debug_estados,
        'total_agro_incl_yara': round(float(venda_agro_total_geral), 2),
        'total_agro_excl_yara': round(float(df_agro[~_mask_yara_agro]['VALOR_PRODUTO'].sum()), 2),
        'total_agro_vendas_diretas': round(float(_total_agro_vendas_diretas), 2),
        'yara_agro_liquido': round(float(df_agro[_mask_yara_agro]['VALOR_PRODUTO'].sum()), 2),
    }, safe=False)