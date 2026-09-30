"""Alertas de clientes inativos (não compram há X dias).

A inatividade é calculada em tempo real contra o ERP (última compra por cliente).
O estado da ação do usuário (resolvido / ignorar) é persistido em AlertaClienteInativo.
"""
import datetime as dt

import pandas as pd
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import AlertaClienteInativo
from .views import engine

# Grupos que enxergam a base inteira. Demais usuários só veem a própria carteira.
GRUPOS_ADMIN = {'Admin', 'Master', 'vendasGestao'}


def _is_admin(request) -> bool:
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=GRUPOS_ADMIN).exists()


# Gestores de um segmento: veem todas as carteiras, mas só do próprio segmento — é o que a
# tela de acompanhamento já libera para eles (decisão do usuário, 30/09/2026). Antes caíam
# no "carteira não informada" e a lista vinha sempre vazia.
GRUPOS_SEGMENTO = {'vendasConstCivil': 'CC', 'vendasAgro': 'AGRO'}


def _segmentos_gestor(request) -> set:
    """Segmentos que o usuário gere pelos grupos vendasConstCivil / vendasAgro."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return set()
    nomes = user.groups.filter(name__in=GRUPOS_SEGMENTO.keys()).values_list('name', flat=True)
    return {GRUPOS_SEGMENTO[n] for n in nomes}


def _consulta_ultima_compra(janela_inicio: str) -> pd.DataFrame:
    """Última compra válida por cliente, considerando notas a partir de `janela_inicio`.

    Usa os mesmos filtros de venda válida da query principal de comissões
    (NFSIT=1, GALMPRODVENDA='S', flags de natureza, série de acerto fora)."""
    sql = f"""
        SELECT
            NF.NFCLI                              CLIENTE_CODIGO,
            MAX(CLINOME)                          CLIENTE_NOME,
            MAX(CLICNPJCPF)                       CLIENTE_CNPJCPF,
            MAX(CAST(NFDATA AS DATE))             ULTIMA_COMPRA,
            COUNT(DISTINCT NF.NFCOD)              QTD_NOTAS,
            -- Quanto o cliente comprou na janela (valor do produto e toneladas), por segmento
            -- do produto — mesma regra de SEGMENTO_PRODUTO e VALOR_PRODUTO do cálculo.
            -- Última compra e notas POR SEGMENTO: com o filtro de segmento, a inatividade é
            -- a do segmento (quem parou de comprar CC mas segue no calcário conta em CC).
            MAX(CASE WHEN ESTQGALM IN (1974, 1587, 1828) THEN NULL ELSE CAST(NFDATA AS DATE) END) ULTIMA_CC,
            MAX(CASE WHEN ESTQGALM IN (1974, 1587, 1828) THEN CAST(NFDATA AS DATE) END) ULTIMA_AGRO,
            COUNT(DISTINCT CASE WHEN ESTQGALM IN (1974, 1587, 1828) THEN NULL ELSE NF.NFCOD END) QTD_NOTAS_CC,
            COUNT(DISTINCT CASE WHEN ESTQGALM IN (1974, 1587, 1828) THEN NF.NFCOD END) QTD_NOTAS_AGRO,
            SUM(CASE WHEN ESTQGALM IN (1974, 1587, 1828) THEN 0 ELSE INFTOTAL END) VALOR_CC,
            SUM(CASE WHEN ESTQGALM IN (1974, 1587, 1828) THEN INFTOTAL ELSE 0 END) VALOR_AGRO,
            SUM(CASE WHEN ESTQGALM IN (1974, 1587, 1828) THEN 0
                     ELSE INFQUANT * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END / 1000.0 END) TN_CC,
            SUM(CASE WHEN ESTQGALM IN (1974, 1587, 1828)
                     THEN INFQUANT * CASE WHEN ESTQPESO > 0 THEN ESTQPESO ELSE 1 END / 1000.0 ELSE 0 END) TN_AGRO,
            (SELECT CIDNOME + '-' + ESTUF FROM CIDADE
                JOIN ESTADO ON ESTCOD = CIDEST WHERE CIDCOD = MAX(CLICIDADE)) CIDADE,
            MAX(COALESCE(NULLIF(LTRIM(RTRIM(CLITELEFONE)), ''),
                         NULLIF(LTRIM(RTRIM(CLICELULAR)), ''),
                         NULLIF(LTRIM(RTRIM(CLIWHATSAPP)), ''))) TELEFONE,
            (SELECT TOP 1 REPNOME FROM NOTAFISCAL X
                JOIN REPRESENTANTE ON REPCOD = X.NFREP
                WHERE X.NFCLI = NF.NFCLI AND X.NFSIT = 1
                ORDER BY X.NFDATA DESC)           REPRESENTANTE,
            -- Representante da última nota de cada segmento (a do Agro não serve para CC).
            (SELECT TOP 1 REPNOME FROM NOTAFISCAL X
                JOIN REPRESENTANTE ON REPCOD = X.NFREP
                JOIN ITEMNOTAFISCAL XI ON XI.INFNFCOD = X.NFCOD
                JOIN ESTOQUE XE ON XE.ESTQCOD = XI.INFESTQ
                WHERE X.NFCLI = NF.NFCLI AND X.NFSIT = 1 AND XE.ESTQGALM NOT IN (1974, 1587, 1828)
                ORDER BY X.NFDATA DESC)           REPRESENTANTE_CC,
            (SELECT TOP 1 REPNOME FROM NOTAFISCAL X
                JOIN REPRESENTANTE ON REPCOD = X.NFREP
                JOIN ITEMNOTAFISCAL XI ON XI.INFNFCOD = X.NFCOD
                JOIN ESTOQUE XE ON XE.ESTQCOD = XI.INFESTQ
                WHERE X.NFCLI = NF.NFCLI AND X.NFSIT = 1 AND XE.ESTQGALM IN (1974, 1587, 1828)
                ORDER BY X.NFDATA DESC)           REPRESENTANTE_AGRO
        FROM NOTAFISCAL NF
            JOIN CLIENTE ON CLICOD = NFCLI
            JOIN ITEMNOTAFISCAL INF ON INFNFCOD = NFCOD
            JOIN NATUREZAOPERACAO ON NOPCOD = INFNOP
            JOIN ESTOQUE ESTQ ON ESTQCOD = INFESTQ
            JOIN GRUPOALMOXARIFADO ON GALMCOD = ESTQGALM
        WHERE NFSIT = 1
            AND GALMPRODVENDA = 'S'
            AND (SUBSTRING(NOPFLAGNF, 1, 1) = 'S' AND SUBSTRING(NOPFLAGNF, 25, 1) = 'N')
            AND NFSNF NOT IN (8)
            AND CAST(NFDATA AS DATE) >= '{janela_inicio}'
        GROUP BY NF.NFCLI
    """
    df = pd.read_sql(sql, engine)
    return df


def _agrupar_por_cnpj(clientes):
    """Junta as unidades do mesmo CNPJ raiz num item só. Última compra = a mais recente
    das unidades; valor e notas somam; nome, cidade, telefone e representante vêm da
    unidade que mais comprou. Resolvido/ignorado só quando TODAS as unidades estão."""
    grupos = {}
    for c in clientes:
        grupos.setdefault(c['grupo_cnpj'] or c['cliente_codigo'], []).append(c)
    saida = []
    for unidades in grupos.values():
        if len(unidades) == 1:
            saida.append(unidades[0])
            continue
        unidades.sort(key=lambda u: u['valor_janela'], reverse=True)
        base = dict(unidades[0])
        mais_recente = max(unidades, key=lambda u: u['ultima_compra'])
        cidades = []
        for u in unidades:
            if u['cidade'] and u['cidade'] not in cidades:
                cidades.append(u['cidade'])
        base.update({
            'codigos': [u['cliente_codigo'] for u in unidades],
            'unidades': len(unidades),
            'cidade': cidades[0] if cidades else base['cidade'],
            'outras_cidades': cidades[1:],
            'ultima_compra': mais_recente['ultima_compra'],
            'dias_sem_comprar': mais_recente['dias_sem_comprar'],
            'qtd_notas_periodo': sum(u['qtd_notas_periodo'] for u in unidades),
            'valor_janela': round(sum(u['valor_janela'] for u in unidades), 2),
            'tn_janela': round(sum(u['tn_janela'] for u in unidades), 3),
            'telefone': next((u['telefone'] for u in unidades if u['telefone']), ''),
            'resolvido': all(u['resolvido'] for u in unidades),
            'ignorar': all(u['ignorar'] for u in unidades),
            'observacao': next((u['observacao'] for u in unidades if u['observacao']), ''),
        })
        saida.append(base)
    return saida


@csrf_exempt
@api_view(['GET', 'POST'])
def clientes_inativos(request):
    """Lista clientes cuja última compra passou do limite de inatividade.

    Params (query string ou body):
      - dias_inatividade (int, default 90): dias sem comprar p/ virar alerta.
      - janela_dias (int, default 365): só considera quem comprou nesse período (foi cliente ativo).
      - representante (str, opcional): filtra a carteira. Obrigatório p/ não-admin.
      - incluir_resolvidos (bool, default false): inclui os já marcados como resolvidos.
      - incluir_ignorados (bool, default false): inclui os marcados como 'não alertar mais'.
      - segmento (str, opcional: 'CC' | 'AGRO'): inatividade DO SEGMENTO — última compra,
        notas, representante, valor e toneladas só desse segmento. Quem parou de comprar CC
        mas segue comprando calcário aparece em CC.
      - ordenar (str, default 'dias'): 'dias' (mais tempo sem comprar primeiro) ou 'valor'
        (quem mais comprava na janela primeiro).
      - agrupar_cnpj (bool, default false): junta as unidades pela raiz do CNPJ (8 dígitos).
        O grupo só é inativo se TODAS as unidades estão inativas; devolve `codigos`.
      - pagina (int, default 1): página da listagem (1-based).
      - por_pagina (int, default 24, máx 200): itens por página; 0 = sem paginar.
    """
    dados = request.data if request.method == 'POST' else request.query_params

    def _int(nome, padrao):
        try:
            return int(dados.get(nome, padrao))
        except (TypeError, ValueError):
            return padrao

    def _bool(nome):
        return str(dados.get(nome, '')).lower() in ('1', 'true', 'sim', 'yes')

    dias_inatividade = max(1, _int('dias_inatividade', 90))
    janela_dias = max(dias_inatividade, _int('janela_dias', 365))
    representante = (dados.get('representante') or '').strip()
    incluir_resolvidos = _bool('incluir_resolvidos')
    incluir_ignorados = _bool('incluir_ignorados')
    segmento = (dados.get('segmento') or '').strip().upper()
    segmento = segmento if segmento in ('CC', 'AGRO') else ''
    ordenar = (dados.get('ordenar') or 'dias').strip().lower()
    agrupar_cnpj = _bool('agrupar_cnpj')
    pagina = max(1, _int('pagina', 1))
    # por_pagina = 0 devolve tudo (usado por exportações); acima disso, teto de 200.
    por_pagina = _int('por_pagina', 24)
    por_pagina = 0 if por_pagina <= 0 else min(por_pagina, 200)

    def _vazio(erro=None):
        corpo = {
            'clientes': [], 'total': 0, 'total_pendentes': 0,
            'pagina': 1, 'por_pagina': por_pagina, 'total_paginas': 0,
        }
        if erro:
            corpo['erro'] = erro
        return corpo

    admin = _is_admin(request)
    if not admin and not representante:
        # Não-admin sem carteira informada: não expõe a base inteira.
        segs = _segmentos_gestor(request)
        if not segs:
            return Response(_vazio('Carteira (representante) não informada.'))
        # Gestor de segmento: base inteira, presa ao(s) segmento(s) dele.
        if segmento and segmento not in segs:
            return Response(_vazio('Segmento fora do seu acesso.'))
        if not segmento and len(segs) == 1:
            segmento = next(iter(segs))

    hoje = timezone.localdate()
    janela_inicio = (hoje - dt.timedelta(days=janela_dias)).strftime('%Y-%m-%d')
    limite_inativo = hoje - dt.timedelta(days=dias_inatividade)

    df = _consulta_ultima_compra(janela_inicio)
    if df.empty:
        return Response(dict(_vazio(), parametros={
            'dias_inatividade': dias_inatividade, 'janela_dias': janela_dias}))

    if segmento:
        # Tudo do segmento: última compra, notas e representante. Quem nunca comprou do
        # segmento na janela sai (ULTIMA_<seg> nulo).
        df = df[df[f'ULTIMA_{segmento}'].notna()].copy()
        df['ULTIMA_COMPRA'] = df[f'ULTIMA_{segmento}']
        df['QTD_NOTAS'] = df[f'QTD_NOTAS_{segmento}']
        df['REPRESENTANTE'] = df[f'REPRESENTANTE_{segmento}'].where(
            df[f'REPRESENTANTE_{segmento}'].notna(), df['REPRESENTANTE'])
    df['ULTIMA_COMPRA'] = pd.to_datetime(df['ULTIMA_COMPRA']).dt.date
    df['REPRESENTANTE'] = df['REPRESENTANTE'].fillna('').astype(str).str.strip()

    # Filtro de carteira (server-side). Admin sem filtro vê tudo.
    if representante:
        alvo = representante.upper()
        df = df[df['REPRESENTANTE'].str.upper().str.contains(alvo, na=False)]

    for _c in ('VALOR_CC', 'VALOR_AGRO', 'TN_CC', 'TN_AGRO'):
        df[_c] = pd.to_numeric(df[_c], errors='coerce').fillna(0.0)
    df['VALOR_JANELA'] = df[f'VALOR_{segmento}'] if segmento else df['VALOR_CC'] + df['VALOR_AGRO']
    df['TN_JANELA'] = df[f'TN_{segmento}'] if segmento else df['TN_CC'] + df['TN_AGRO']

    # Raiz do CNPJ (8 dígitos) para agrupar as unidades; CPF/sem documento fica pelo código.
    _doc = df['CLIENTE_CNPJCPF'].fillna('').astype(str).str.replace(r'\D', '', regex=True)
    df['GRUPO_CNPJ'] = 'cnpj:' + _doc.str[:8]
    df.loc[_doc.str.len() != 14, 'GRUPO_CNPJ'] = 'cli:' + df['CLIENTE_CODIGO'].astype(str)
    if agrupar_cnpj:
        # Grupo ativo se QUALQUER unidade comprou depois do limite: some da lista inteiro.
        ultima_grupo = df.groupby('GRUPO_CNPJ')['ULTIMA_COMPRA'].transform('max')
        df = df[ultima_grupo <= limite_inativo]
    else:
        # Só os inativos (última compra <= hoje - dias_inatividade).
        df = df[df['ULTIMA_COMPRA'] <= limite_inativo]

    # Estado persistido por cliente.
    estados = {a.cliente_codigo: a for a in AlertaClienteInativo.objects.all()}

    clientes = []
    for _, row in df.iterrows():
        codigo = str(row['CLIENTE_CODIGO'])
        ultima = row['ULTIMA_COMPRA']
        estado = estados.get(codigo)

        resolvido = False
        ignorar = False
        observacao = ''
        resolvido_por = ''
        data_resolucao = None

        if estado:
            ignorar = estado.ignorar
            observacao = estado.observacao or ''
            # Reabre automaticamente se comprou depois de resolvido.
            if estado.resolvido:
                comprou_depois = (
                    estado.ultima_compra_ao_resolver is not None
                    and ultima > estado.ultima_compra_ao_resolver
                )
                if comprou_depois:
                    estado.resolvido = False
                    estado.data_resolucao = None
                    estado.save(update_fields=['resolvido', 'data_resolucao', 'atualizado_em'])
                else:
                    resolvido = True
                    resolvido_por = estado.resolvido_por or ''
                    data_resolucao = estado.data_resolucao

        if ignorar and not incluir_ignorados:
            continue
        if resolvido and not incluir_resolvidos:
            continue

        clientes.append({
            'cliente_codigo': codigo,
            'cliente_nome': row.get('CLIENTE_NOME') or '',
            'cnpj_cpf': row.get('CLIENTE_CNPJCPF') or '',
            'cidade': row.get('CIDADE') or '',
            'telefone': (str(row.get('TELEFONE')) if row.get('TELEFONE') else ''),
            'representante': row.get('REPRESENTANTE') or '',
            'ultima_compra': ultima.strftime('%Y-%m-%d'),
            'dias_sem_comprar': (hoje - ultima).days,
            'qtd_notas_periodo': int(row.get('QTD_NOTAS') or 0),
            'valor_janela': round(float(row.get('VALOR_JANELA') or 0), 2),
            'tn_janela': round(float(row.get('TN_JANELA') or 0), 3),
            'grupo_cnpj': row.get('GRUPO_CNPJ') or '',
            'resolvido': resolvido,
            'ignorar': ignorar,
            'observacao': observacao,
            'resolvido_por': resolvido_por,
            'data_resolucao': data_resolucao.isoformat() if data_resolucao else None,
        })

    if agrupar_cnpj:
        clientes = _agrupar_por_cnpj(clientes)
    for c in clientes:
        c.setdefault('codigos', [c['cliente_codigo']])
        c.setdefault('unidades', 1)
        c.setdefault('outras_cidades', [])

    if ordenar == 'valor':
        clientes.sort(key=lambda c: (c['valor_janela'], c['dias_sem_comprar']), reverse=True)
    else:
        clientes.sort(key=lambda c: c['dias_sem_comprar'], reverse=True)

    total = len(clientes)
    # Escala das barras do front: o maior da lista inteira, para a página 2 não parecer a 1.
    maior_valor = max((c['valor_janela'] for c in clientes), default=0)
    maior_dias = max((c['dias_sem_comprar'] for c in clientes), default=0)
    # Pendentes = o que ainda exige ação, contado sobre o conjunto inteiro (não só a página).
    total_pendentes = sum(1 for c in clientes if not c['resolvido'] and not c['ignorar'])

    if por_pagina:
        total_paginas = (total + por_pagina - 1) // por_pagina
        pagina = min(pagina, total_paginas) if total_paginas else 1
        inicio = (pagina - 1) * por_pagina
        clientes = clientes[inicio:inicio + por_pagina]
    else:
        total_paginas = 1 if total else 0
        pagina = 1

    return Response({
        'clientes': clientes,
        'total': total,
        'total_pendentes': total_pendentes,
        'pagina': pagina,
        'por_pagina': por_pagina,
        'total_paginas': total_paginas,
        'maior_valor': maior_valor,
        'maior_dias': maior_dias,
        'parametros': {
            'dias_inatividade': dias_inatividade,
            'janela_dias': janela_dias,
            'representante': representante or None,
            'admin': admin,
        },
    })


@csrf_exempt
@api_view(['POST'])
def marcar_alerta_cliente(request):
    """Atualiza o estado do alerta de um cliente.

    Body: { cliente_codigo, acao: 'resolver'|'ignorar'|'reabrir', cliente_nome?,
            ultima_compra? (YYYY-MM-DD), observacao? }"""
    d = request.data
    codigo = str(d.get('cliente_codigo') or '').strip()
    acao = (d.get('acao') or '').strip().lower()
    if not codigo or acao not in ('resolver', 'ignorar', 'reabrir'):
        return Response({'erro': 'cliente_codigo e acao (resolver|ignorar|reabrir) são obrigatórios.'}, status=400)

    user = getattr(request, 'user', None)
    nome_user = ''
    if user and user.is_authenticated:
        nome_user = user.get_full_name() or user.get_username()

    alerta, _ = AlertaClienteInativo.objects.get_or_create(cliente_codigo=codigo)
    if d.get('cliente_nome'):
        alerta.cliente_nome = d.get('cliente_nome')
    if d.get('observacao') is not None:
        alerta.observacao = d.get('observacao') or ''

    if acao == 'resolver':
        alerta.resolvido = True
        alerta.resolvido_por = nome_user
        alerta.data_resolucao = timezone.now()
        ultima = d.get('ultima_compra')
        if ultima:
            try:
                alerta.ultima_compra_ao_resolver = dt.datetime.strptime(ultima, '%Y-%m-%d').date()
            except ValueError:
                pass
    elif acao == 'ignorar':
        alerta.ignorar = True
        alerta.resolvido_por = nome_user
        alerta.data_resolucao = timezone.now()
    elif acao == 'reabrir':
        alerta.resolvido = False
        alerta.ignorar = False
        alerta.data_resolucao = None

    alerta.save()
    return Response({
        'ok': True,
        'cliente_codigo': codigo,
        'resolvido': alerta.resolvido,
        'ignorar': alerta.ignorar,
    })
