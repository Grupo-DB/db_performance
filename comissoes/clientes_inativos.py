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
            (SELECT CIDNOME + '-' + ESTUF FROM CIDADE
                JOIN ESTADO ON ESTCOD = CIDEST WHERE CIDCOD = MAX(CLICIDADE)) CIDADE,
            MAX(CLIFONE)                          TELEFONE,
            (SELECT TOP 1 REPNOME FROM NOTAFISCAL X
                JOIN REPRESENTANTE ON REPCOD = X.NFREP
                WHERE X.NFCLI = NF.NFCLI AND X.NFSIT = 1
                ORDER BY X.NFDATA DESC)           REPRESENTANTE
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

    admin = _is_admin(request)
    if not admin and not representante:
        # Não-admin sem carteira informada: não expõe a base inteira.
        return Response({'clientes': [], 'total': 0, 'erro': 'Carteira (representante) não informada.'})

    hoje = timezone.localdate()
    janela_inicio = (hoje - dt.timedelta(days=janela_dias)).strftime('%Y-%m-%d')
    limite_inativo = hoje - dt.timedelta(days=dias_inatividade)

    df = _consulta_ultima_compra(janela_inicio)
    if df.empty:
        return Response({'clientes': [], 'total': 0, 'parametros': {
            'dias_inatividade': dias_inatividade, 'janela_dias': janela_dias}})

    df['ULTIMA_COMPRA'] = pd.to_datetime(df['ULTIMA_COMPRA']).dt.date
    df['REPRESENTANTE'] = df['REPRESENTANTE'].fillna('').astype(str).str.strip()

    # Filtro de carteira (server-side). Admin sem filtro vê tudo.
    if representante:
        alvo = representante.upper()
        df = df[df['REPRESENTANTE'].str.upper().str.contains(alvo, na=False)]

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
            'resolvido': resolvido,
            'ignorar': ignorar,
            'observacao': observacao,
            'resolvido_por': resolvido_por,
            'data_resolucao': data_resolucao.isoformat() if data_resolucao else None,
        })

    clientes.sort(key=lambda c: c['dias_sem_comprar'], reverse=True)

    return Response({
        'clientes': clientes,
        'total': len(clientes),
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
