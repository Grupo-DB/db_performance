"""Avisos de vencimento de documentos.

Percorre os tipos que têm data de término e avisa por e-mail e pelo sino quando
o documento entra na janela de aviso. Roda pelo comando
``manage.py avisar_vencimentos``, que é idempotente: o modelo ``AvisoVencimento``
guarda cada degrau já enviado, então rodar duas vezes no mesmo dia não duplica
nada.

Degraus (em dias restantes): a janela do próprio documento — ``prazo_aviso``, no
contrato — e depois 30, 15, 7, 1, 0 (vence hoje) e -1 (venceu). Só são usados os
degraus que cabem dentro da janela: com ``prazo_aviso = 5`` os avisos saem em 5,
1 e 0 dias, nunca em 30.
"""

from datetime import date

from django.conf import settings
from django.contrib.contenttypes.models import ContentType

from gestaoDocumentos.aprovacoes import (
    AZUL, LARANJA, VERMELHO, _enviar, _montar_html, email_usuario, nome_usuario,
)
from gestaoDocumentos.models import (
    Alvara, AvisoVencimento, Contrato, DocumentoNotificacao, ProcessoExterno,
    Procuracao, Seguro, Veiculo,
)

# Janela usada pelos tipos que não têm campo próprio de prazo de aviso.
DIAS_PADRAO = 30

# Degraus fixos, do mais distante ao mais próximo.
MARCOS_PADRAO = [30, 15, 7, 1, 0]

# -1 é o aviso de "já venceu", enviado uma única vez.
MARCO_VENCIDO = -1


def _titulo_contrato(d):
    return d.contratado or d.objeto_contrato or f'Contrato {d.numero or d.id}'


def _titulo_seguro(d):
    apolice = f' — apólice {d.numero_apolice}' if d.numero_apolice else ''
    return f'{d.seguradora or "Seguro"}{apolice}'


def _titulo_alvara(d):
    return f'{d.tipo_alvara or "Alvará"} — {d.empresa_titular or d.numero_alvara or d.id}'


def _titulo_procuracao(d):
    return f'Procuração de {d.outorgante or "—"} para {d.outorgado or "—"}'


def _titulo_veiculo(d):
    return f'{d.tipo_documento or "Documento"} — {d.placa or d.modelo_veiculo or d.id}'


def _titulo_processo(d):
    return f'Processo {d.numero or d.id} — {d.parte_contraria or d.objeto_processo or ""}'.strip(' —')


# Cada entrada diz onde está a data e como o documento se chama no aviso.
TIPOS = [
    {'modelo': Contrato,       'rotulo': 'Contrato',        'campo_data': 'data_fim',        'campo_dias': 'prazo_aviso', 'titulo': _titulo_contrato},
    {'modelo': Seguro,         'rotulo': 'Seguro',          'campo_data': 'data_fim',        'campo_dias': 'prazo_aviso', 'titulo': _titulo_seguro},
    {'modelo': Alvara,         'rotulo': 'Alvará',          'campo_data': 'data_fim',        'campo_dias': None,          'titulo': _titulo_alvara},
    {'modelo': Procuracao,     'rotulo': 'Procuração',      'campo_data': 'data_fim',        'campo_dias': None,          'titulo': _titulo_procuracao},
    {'modelo': Veiculo,        'rotulo': 'Veículo',         'campo_data': 'data_vencimento', 'campo_dias': None,          'titulo': _titulo_veiculo},
    {'modelo': ProcessoExterno,'rotulo': 'Processo Externo','campo_data': 'data_fim',        'campo_dias': None,          'titulo': _titulo_processo},
]


def marcos_da_janela(janela):
    """Degraus válidos para uma janela, do mais distante ao mais próximo."""
    janela = max(int(janela or DIAS_PADRAO), 0)
    return sorted({janela} | {m for m in MARCOS_PADRAO if m < janela}, reverse=True)


def marco_atual(dias_restantes, janela):
    """Degrau em que o documento está hoje, ou None se ainda está longe demais.

    Se o comando ficar dias sem rodar, o documento cai direto no degrau certo em
    vez de disparar todos os anteriores de uma vez.
    """
    if dias_restantes < 0:
        return MARCO_VENCIDO
    candidatos = [m for m in marcos_da_janela(janela) if m >= dias_restantes]
    return min(candidatos) if candidatos else None


# ── Destinatários ───────────────────────────────────────────────────────────

def _colaborador_por_nome(nome):
    """Casa o texto livre de `responsavel_interno` com um Colaborador cadastrado."""
    if not nome or not str(nome).strip():
        return None
    from avaliacoes.management.models import Colaborador
    return Colaborador.objects.filter(nome__iexact=str(nome).strip()).first()


def usuarios_gestores():
    """Quem recebe o aviso de um documento sem responsável identificado.

    Membros ativos do grupo ``settings.GRUPO_AVISO_DOCUMENTOS``; sem o grupo, ou
    com ele vazio, os superusuários ativos.
    """
    from django.contrib.auth.models import User

    nome_grupo = getattr(settings, 'GRUPO_AVISO_DOCUMENTOS', None)
    if nome_grupo:
        membros = list(User.objects.filter(groups__name=nome_grupo, is_active=True).distinct())
        if membros:
            return membros
    return list(User.objects.filter(is_superuser=True, is_active=True))


def destinatarios_do_documento(documento):
    """Quem recebe o aviso: (lista de Users, lista de e-mails).

    Ordem de busca: quem cadastrou (só contratos têm `criado_por`), o
    responsável interno casado pelo nome, e a lista fixa de
    ``settings.EMAILS_AVISO_DOCUMENTOS``.
    """
    usuarios, emails = [], []

    criador = getattr(documento, 'criado_por', None)
    if criador is not None:
        usuarios.append(criador)

    colaborador = _colaborador_por_nome(getattr(documento, 'responsavel_interno', None))
    if colaborador is not None:
        if colaborador.user_id and all(u.id != colaborador.user_id for u in usuarios):
            usuarios.append(colaborador.user)
        elif colaborador.email:
            emails.append(colaborador.email)

    # Documento sem ninguém no sistema — os cadastrados antes de `criado_por`
    # existir, ou com Responsável Interno que não casa com Colaborador — vai para
    # quem cuida do módulo, senão o sino nunca mostraria o vencimento.
    if not usuarios:
        usuarios.extend(usuarios_gestores())

    emails.extend(getattr(settings, 'EMAILS_AVISO_DOCUMENTOS', []) or [])
    emails.extend(e for e in (email_usuario(u) for u in usuarios) if e)

    # Sem ninguém identificado o aviso morreria em silêncio: a lista fixa é o
    # último recurso e por isso vale a pena checá-la no deploy.
    return usuarios, sorted(set(emails))


# ── Varredura ───────────────────────────────────────────────────────────────

def documentos_a_avisar(hoje=None):
    """Lista o que está em algum degrau hoje e ainda não foi avisado nele."""
    hoje = hoje or date.today()
    pendentes = []

    for config in TIPOS:
        modelo = config['modelo']
        ct = ContentType.objects.get_for_model(modelo)
        campo_data = config['campo_data']

        já_avisados = {
            (a.object_id, a.marco)
            for a in AvisoVencimento.objects.filter(content_type=ct)
        }

        for documento in modelo.objects.filter(**{f'{campo_data}__isnull': False}):
            vencimento = getattr(documento, campo_data)
            dias = (vencimento - hoje).days
            janela = getattr(documento, config['campo_dias'], None) if config['campo_dias'] else None
            marco = marco_atual(dias, janela)
            if marco is None or (documento.id, marco) in já_avisados:
                continue
            pendentes.append({
                'documento': documento,
                'config': config,
                'content_type': ct,
                'dias': dias,
                'marco': marco,
                'vencimento': vencimento,
            })

    return pendentes


def avisar(pendencia, simular=False):
    """Manda o aviso de um documento e registra o degrau. Devolve os e-mails."""
    documento = pendencia['documento']
    config = pendencia['config']
    dias = pendencia['dias']

    usuarios, emails = destinatarios_do_documento(documento)
    titulo_doc = config['titulo'](documento)

    if dias < 0:
        tipo_notificacao, cor = 'VENCIDO', VERMELHO
        chamada = f'venceu há {abs(dias)} dia(s)'
        assunto = f'[Vencido] {config["rotulo"]}: {titulo_doc}'
    elif dias == 0:
        tipo_notificacao, cor = 'VENCIMENTO_HOJE', LARANJA
        chamada = 'vence hoje'
        assunto = f'[Vence hoje] {config["rotulo"]}: {titulo_doc}'
    else:
        tipo_notificacao, cor = 'VENCIMENTO_PROXIMO', AZUL
        chamada = f'vence em {dias} dia(s)'
        assunto = f'[Vence em {dias} dias] {config["rotulo"]}: {titulo_doc}'

    mensagem = f'{config["rotulo"]} "{titulo_doc}" {chamada}.'

    if simular:
        return emails

    # Sino — só para quem tem usuário no sistema.
    for usuario in usuarios:
        DocumentoNotificacao.objects.create(
            contrato=documento if isinstance(documento, Contrato) else None,
            content_type=pendencia['content_type'],
            object_id=documento.id,
            documento_tipo=config['rotulo'],
            usuario_notificado=usuario,
            tipo=tipo_notificacao,
            mensagem=mensagem,
        )

    if emails:
        linhas = [
            ('Documento', titulo_doc),
            ('Tipo', config['rotulo']),
            ('Vencimento', pendencia['vencimento'].strftime('%d/%m/%Y')),
            ('Situação', chamada.capitalize()),
            ('Responsável interno', getattr(documento, 'responsavel_interno', None) or '—'),
            ('Cadastrado por', getattr(documento, 'created_by', None)
                or nome_usuario(getattr(documento, 'criado_por', None))),
        ]
        base = str(settings.FRONTEND_URL).rstrip('/')
        corpo_html = _montar_html(
            titulo=f'{config["rotulo"]} {chamada}',
            cor_titulo=cor,
            subtitulo=titulo_doc,
            linhas=linhas,
            cta_texto='Abrir no ManagerDB',
            cta_url=f'{base}/gestaoDocumentos/gestaoDocumentos',
            rodape='Aviso automático de vencimento da Gestão de Documentos.',
        )
        corpo_txt = (
            f'{mensagem}\nVencimento: {pendencia["vencimento"].strftime("%d/%m/%Y")}\n\n'
            f'Abrir no ManagerDB: {base}/gestaoDocumentos/gestaoDocumentos\n'
        )
        _enviar(assunto, corpo_txt, corpo_html, emails)

    AvisoVencimento.objects.create(
        content_type=pendencia['content_type'],
        object_id=documento.id,
        marco=pendencia['marco'],
        data_vencimento=pendencia['vencimento'],
        destinatarios=', '.join(emails) or None,
    )
    return emails
