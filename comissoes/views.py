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
    AND CAST(NFDATA AS DATE) BETWEEN '{dataInicio}' AND '{dataFim}'
    AND GALMPRODVENDA = 'S'
    AND (SUBSTRING(NOPFLAGNF, 1, 1) = 'S' 
            AND SUBSTRING(NOPFLAGNF, 25, 1) = 'N') --Flag Operação Finan. 'S' e Não Rep. Receita 'N'
    AND NFSNF NOT IN (8) -- Serie Acerto

    ORDER BY 2, 3, 4
                                """, engine)
    
    valor = consulta_vendas['VALOR_TOTAL'].sum()
    
    response_data = {
        'valor_total': valor
    }
    return JsonResponse(response_data, safe=False)