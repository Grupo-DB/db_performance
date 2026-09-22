"""Fluxo de aprovação de contratos: notificações no sino e e-mail com link.

Dois modos, escolhidos no cadastro do contrato:

* ``PARALELO``   — todos os aprovadores são acionados de uma vez; o contrato
  só é aprovado quando o último deles decide.
* ``SEQUENCIAL`` — só o aprovador de menor ``ordem`` é acionado; o seguinte é
  avisado quando o anterior aprova.

Em qualquer um dos modos uma reprovação encerra o fluxo na hora.

O e-mail leva um link que abre a tela de Gestão de Documentos já no drawer de
aprovação do contrato — o destinatário passa pelo login normal do ManagerDB.
"""

import os
import threading
from email.mime.image import MIMEImage

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import connections
from django.utils import timezone

from gestaoDocumentos.models import AprovacaoContrato, DocumentoNotificacao

# Identidade visual (mesma paleta dos e-mails de pedido do catálogo)
AZUL     = '#004EAE'
LARANJA  = '#FFB100'
VERDE    = '#00B036'
VERMELHO = '#D93025'
CIANO    = '#00CFDD'


class ErroAprovacao(Exception):
    """Regra de negócio violada — vira 400 na view."""


# ── Identificação de pessoas ────────────────────────────────────────────────

def nome_usuario(user):
    """Nome de exibição: prefere o cadastro de Colaborador, cai no User."""
    if user is None:
        return '—'
    colaborador = getattr(user, 'colaborador', None)
    if colaborador and colaborador.nome:
        return colaborador.nome
    return user.get_full_name() or user.username


def email_usuario(user):
    """E-mail de contato: prefere o do Colaborador, cai no do User."""
    if user is None:
        return None
    colaborador = getattr(user, 'colaborador', None)
    if colaborador and colaborador.email:
        return colaborador.email
    return user.email or None


def _identificacao(contrato):
    partes = [p for p in [contrato.numero, contrato.objeto_contrato] if p]
    return ' — '.join(partes) if partes else f'Contrato #{contrato.id}'


def _link(contrato):
    base = str(settings.FRONTEND_URL).rstrip('/')
    return f'{base}/gestaoDocumentos/gestaoDocumentos?aprovacao={contrato.id}'


# ── Início e andamento do fluxo ─────────────────────────────────────────────

def iniciar_fluxo(contrato, aprovadores_ids, modo):
    """Cria as linhas de aprovação e aciona quem deve decidir agora.

    ``aprovadores_ids`` é a lista de ids de ``User`` na ordem escolhida na tela;
    a ordem só tem efeito prático no modo sequencial.
    """
    ids = []
    for valor in aprovadores_ids:
        try:
            uid = int(valor)
        except (TypeError, ValueError):
            continue
        if uid not in ids:
            ids.append(uid)
    if not ids:
        return []

    modo = 'SEQUENCIAL' if str(modo).upper() == 'SEQUENCIAL' else 'PARALELO'

    aprovacoes = [
        AprovacaoContrato.objects.create(contrato=contrato, aprovador_id=uid, ordem=posicao)
        for posicao, uid in enumerate(ids, start=1)
    ]

    contrato.modo_aprovacao = modo
    contrato.situacao_aprovacao = 'PENDENTE'
    contrato.save(update_fields=['modo_aprovacao', 'situacao_aprovacao'])

    acionar = aprovacoes if modo == 'PARALELO' else aprovacoes[:1]
    _acionar(contrato, acionar)
    return aprovacoes


def registrar_decisao(contrato, user, aprovado, parecer=''):
    """Grava a decisão de um aprovador e faz o fluxo andar."""
    aprovacao = contrato.aprovacoes.filter(aprovador=user).first()
    if aprovacao is None:
        raise ErroAprovacao('Você não está na lista de aprovadores deste contrato.')
    if contrato.situacao_aprovacao != 'PENDENTE':
        raise ErroAprovacao('O fluxo de aprovação deste contrato já foi encerrado.')
    if aprovacao.situacao != 'PENDENTE':
        raise ErroAprovacao('Você já registrou a sua decisão neste contrato.')

    if contrato.modo_aprovacao == 'SEQUENCIAL':
        vez = contrato.aprovacoes.filter(situacao='PENDENTE').order_by('ordem', 'id').first()
        if vez and vez.pk != aprovacao.pk:
            raise ErroAprovacao(
                f'Ainda não é a sua vez: o contrato aguarda {nome_usuario(vez.aprovador)}.'
            )

    aprovacao.situacao = 'APROVADO' if aprovado else 'REPROVADO'
    aprovacao.parecer = (parecer or '').strip() or None
    aprovacao.decidido_em = timezone.now()
    aprovacao.save(update_fields=['situacao', 'parecer', 'decidido_em'])

    if not aprovado:
        contrato.situacao_aprovacao = 'REPROVADO'
        contrato.save(update_fields=['situacao_aprovacao'])
        _avisar_desfecho(contrato, aprovacao, aprovado=False)
        return contrato

    restantes = list(contrato.aprovacoes.filter(situacao='PENDENTE').order_by('ordem', 'id'))
    if not restantes:
        contrato.situacao_aprovacao = 'APROVADO'
        contrato.save(update_fields=['situacao_aprovacao'])
        _avisar_desfecho(contrato, aprovacao, aprovado=True)
        return contrato

    if contrato.modo_aprovacao == 'SEQUENCIAL':
        _acionar(contrato, restantes[:1])

    # Aprovação parcial: o autor acompanha pelo sino, sem e-mail a cada passo.
    _notificar(
        contrato,
        contrato.criado_por,
        'APROVACAO_APROVADA',
        f'{nome_usuario(user)} aprovou {_identificacao(contrato)}. '
        f'Faltam {len(restantes)} aprovação(ões).',
    )
    return contrato


def pendentes_de(user):
    """Aprovações que dependem de ``user`` agora (respeita a vez no sequencial)."""
    minhas = (
        AprovacaoContrato.objects
        .filter(aprovador=user, situacao='PENDENTE', contrato__situacao_aprovacao='PENDENTE')
        .select_related('contrato')
    )
    pendentes = []
    for aprovacao in minhas:
        contrato = aprovacao.contrato
        if contrato.modo_aprovacao == 'SEQUENCIAL':
            vez = contrato.aprovacoes.filter(situacao='PENDENTE').order_by('ordem', 'id').first()
            if vez and vez.pk != aprovacao.pk:
                continue
        pendentes.append(aprovacao)
    return pendentes


# ── Notificações ────────────────────────────────────────────────────────────

def _notificar(contrato, user, tipo, mensagem):
    if user is None:
        return
    DocumentoNotificacao.objects.create(
        contrato=contrato, usuario_notificado=user, tipo=tipo, mensagem=mensagem,
    )


def _acionar(contrato, aprovacoes):
    """Marca como notificadas, grava o aviso no sino e dispara os e-mails."""
    if not aprovacoes:
        return
    agora = timezone.now()
    for aprovacao in aprovacoes:
        aprovacao.notificado_em = agora
        aprovacao.save(update_fields=['notificado_em'])
        _notificar(
            contrato, aprovacao.aprovador, 'APROVACAO_SOLICITADA',
            f'Sua aprovação foi solicitada em {_identificacao(contrato)}.',
        )
    _em_segundo_plano(_enviar_emails_solicitacao, contrato.id, [a.id for a in aprovacoes])


def _avisar_desfecho(contrato, aprovacao, aprovado):
    if aprovado:
        tipo = 'APROVACAO_CONCLUIDA'
        mensagem = f'{_identificacao(contrato)} foi aprovado por todos os aprovadores.'
    else:
        tipo = 'APROVACAO_REPROVADA'
        mensagem = (
            f'{_identificacao(contrato)} foi reprovado por '
            f'{nome_usuario(aprovacao.aprovador)}.'
        )

    avisados = set()
    for destinatario in [contrato.criado_por] + [a.aprovador for a in contrato.aprovacoes.all()]:
        if destinatario is None or destinatario.id in avisados:
            continue
        avisados.add(destinatario.id)
        _notificar(contrato, destinatario, tipo, mensagem)

    _em_segundo_plano(_enviar_email_desfecho, contrato.id, aprovacao.id, aprovado)


def _em_segundo_plano(funcao, *args):
    """Roda fora do request para o e-mail não segurar a resposta da API."""
    def alvo():
        try:
            funcao(*args)
        except Exception:  # um e-mail que falha não pode derrubar o fluxo
            import traceback
            traceback.print_exc()
        finally:
            connections.close_all()

    threading.Thread(target=alvo, daemon=True).start()


# ── E-mails ─────────────────────────────────────────────────────────────────

def _montar_html(titulo, cor_titulo, subtitulo, linhas, cta_texto, cta_url, rodape):
    """Monta o corpo HTML no mesmo padrão dos e-mails de pedido do catálogo."""
    linhas_html = ''.join(
        f"<tr>"
        f"<td style='padding:5px;color:#888;width:150px;white-space:nowrap;font-size:14px'>{rotulo}</td>"
        f"<td style='padding:5px;color:#111;font-size:14px'>{valor}</td>"
        f"</tr>"
        for rotulo, valor in linhas
    )

    botao = ''
    if cta_texto and cta_url:
        botao = f"""
  <tr>
    <td style="background:#fff;padding:8px 32px 32px" align="center">
      <a href="{cta_url}"
         style="display:inline-block;background:{AZUL};color:#fff;text-decoration:none;
                padding:14px 34px;border-radius:8px;font-size:15px;font-weight:700">
        {cta_texto}
      </a>
      <p style="margin:14px 0 0;font-size:12px;color:#aaa">
        Se o botão não funcionar, copie este endereço no navegador:<br>
        <span style="color:{AZUL}">{cta_url}</span>
      </p>
    </td>
  </tr>"""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef2f7;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#eef2f7;padding:32px 16px">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%">

  <tr>
    <td style="padding:0;line-height:0;font-size:0;border-radius:12px 12px 0 0;overflow:hidden">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td width="33%" style="background:{AZUL};height:6px">&nbsp;</td>
        <td width="33%" style="background:{LARANJA};height:6px">&nbsp;</td>
        <td width="34%" style="background:{VERDE};height:6px">&nbsp;</td>
      </tr></table>
    </td>
  </tr>

  <tr>
    <td style="background:#ffffff;padding:20px 32px;border-left:1px solid #e8eef5;border-right:1px solid #e8eef5">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="vertical-align:middle">
          <img src="cid:logo_db" alt="Grupo Dagoberto Barcellos" height="72" style="display:block;border:0">
        </td>
        <td align="right" style="vertical-align:middle">
          <p style="margin:0;color:{AZUL};font-size:11px;letter-spacing:1px;text-transform:uppercase;font-weight:700">Sistema ManagerDB</p>
        </td>
      </tr></table>
    </td>
  </tr>

  <tr><td style="padding:0;line-height:0;font-size:0">
    <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td style="background:{AZUL};height:4px">&nbsp;</td>
    </tr></table>
  </td></tr>

  <tr>
    <td style="background:#fff;padding:28px 32px 12px">
      <h1 style="margin:0 0 6px;font-size:22px;font-weight:700;color:{cor_titulo}">{titulo}</h1>
      <p style="margin:0;font-size:14px;color:#888">{subtitulo}</p>
    </td>
  </tr>

  <tr>
    <td style="background:#fff;padding:12px 32px 24px">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="background:#f0f7ff;border-radius:8px;border-left:4px solid {CIANO}">
        <tr><td style="padding:14px 18px">
          <table width="100%" cellpadding="0" cellspacing="0" border="0">{linhas_html}</table>
        </td></tr>
      </table>
    </td>
  </tr>
{botao}
  <tr>
    <td style="background:{AZUL};border-radius:0 0 12px 12px;padding:16px 32px;text-align:center">
      <p style="margin:0;color:rgba(255,255,255,0.75);font-size:12px">{rodape}</p>
      <p style="margin:6px 0 0;color:rgba(255,255,255,0.5);font-size:11px;letter-spacing:0.3px">
        Email automático gerado pelo sistema ManagerDB &mdash; Grupo Dagoberto Barcellos
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _enviar(assunto, corpo_txt, corpo_html, destinatarios):
    destinatarios = [d for d in destinatarios if d]
    if not destinatarios:
        return

    msg = EmailMultiAlternatives(subject=assunto, body=corpo_txt, to=destinatarios)
    msg.mixed_subtype = 'related'
    msg.attach_alternative(corpo_html, 'text/html')

    logo_path = os.path.join(settings.MEDIA_ROOT, 'logoNovoDb.png')
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as arquivo:
            logo = MIMEImage(arquivo.read())
        logo.add_header('Content-ID', '<logo_db>')
        logo.add_header('Content-Disposition', 'inline', filename='logoNovoDb.png')
        msg.attach(logo)

    msg.send(fail_silently=False)


def _dados_contrato(contrato):
    valor = f'R$ {float(contrato.valor_contrato):,.2f}' if contrato.valor_contrato is not None else '—'
    valor = valor.replace(',', 'X').replace('.', ',').replace('X', '.')
    return [
        ('Contrato', contrato.numero or f'#{contrato.id}'),
        ('Objeto', contrato.objeto_contrato or '—'),
        ('Contratado', contrato.contratado or '—'),
        ('Contratante', contrato.contratante or '—'),
        ('Valor', valor),
        ('Vigência', contrato.vigencia or '—'),
        ('Cadastrado por', contrato.created_by or nome_usuario(contrato.criado_por)),
    ]


def _enviar_emails_solicitacao(contrato_id, aprovacao_ids):
    from gestaoDocumentos.models import Contrato

    contrato = Contrato.objects.filter(id=contrato_id).first()
    if contrato is None:
        return
    link = _link(contrato)
    total = contrato.aprovacoes.count()
    sequencial = contrato.modo_aprovacao == 'SEQUENCIAL'

    for aprovacao in AprovacaoContrato.objects.filter(id__in=aprovacao_ids).select_related('aprovador'):
        destino = email_usuario(aprovacao.aprovador)
        if not destino:
            continue

        if sequencial:
            posicao = f'Você é o aprovador {aprovacao.ordem} de {total} (fluxo sequencial).'
        else:
            posicao = f'O contrato aguarda a aprovação de {total} pessoa(s), em paralelo.'

        linhas = _dados_contrato(contrato) + [('Fluxo', posicao)]
        corpo_html = _montar_html(
            titulo='Contrato aguardando sua aprovação',
            cor_titulo=AZUL,
            subtitulo=f'Olá, {nome_usuario(aprovacao.aprovador)}.',
            linhas=linhas,
            cta_texto='Aprovar no ManagerDB',
            cta_url=link,
            rodape='O link abre a tela de Gestão de Documentos; use o seu login habitual.',
        )
        corpo_txt = (
            f'Olá, {nome_usuario(aprovacao.aprovador)}.\n\n'
            f'O contrato "{_identificacao(contrato)}" aguarda a sua aprovação.\n'
            f'{posicao}\n\n'
            f'Aprove pelo ManagerDB: {link}\n'
        )
        _enviar(
            assunto=f'[Aprovação] {_identificacao(contrato)}',
            corpo_txt=corpo_txt,
            corpo_html=corpo_html,
            destinatarios=[destino],
        )


def _enviar_email_desfecho(contrato_id, aprovacao_id, aprovado):
    from gestaoDocumentos.models import Contrato

    contrato = Contrato.objects.filter(id=contrato_id).first()
    aprovacao = AprovacaoContrato.objects.filter(id=aprovacao_id).select_related('aprovador').first()
    if contrato is None or aprovacao is None:
        return

    decisor = nome_usuario(aprovacao.aprovador)
    if aprovado:
        titulo, cor = 'Contrato aprovado', VERDE
        subtitulo = 'Todos os aprovadores registraram a aprovação.'
    else:
        titulo, cor = 'Contrato reprovado', VERMELHO
        subtitulo = f'Reprovado por {decisor}.'

    historico = [
        (
            nome_usuario(a.aprovador),
            f"{a.get_situacao_display()}"
            + (f" — {a.parecer}" if a.parecer else '')
            + (f" ({a.decidido_em.strftime('%d/%m/%Y %H:%M')})" if a.decidido_em else ''),
        )
        for a in contrato.aprovacoes.select_related('aprovador')
    ]

    corpo_html = _montar_html(
        titulo=titulo,
        cor_titulo=cor,
        subtitulo=subtitulo,
        linhas=_dados_contrato(contrato) + historico,
        cta_texto='Ver no ManagerDB',
        cta_url=_link(contrato),
        rodape='Aviso enviado a quem cadastrou o contrato e aos aprovadores.',
    )
    corpo_txt = (
        f'{titulo}: {_identificacao(contrato)}\n{subtitulo}\n\n'
        + '\n'.join(f'  - {nome}: {detalhe}' for nome, detalhe in historico)
        + f'\n\nVer no ManagerDB: {_link(contrato)}\n'
    )

    destinatarios = {email_usuario(contrato.criado_por)}
    destinatarios.update(email_usuario(a.aprovador) for a in contrato.aprovacoes.select_related('aprovador'))
    _enviar(
        assunto=f'[{"Aprovado" if aprovado else "Reprovado"}] {_identificacao(contrato)}',
        corpo_txt=corpo_txt,
        corpo_html=corpo_html,
        destinatarios=sorted(d for d in destinatarios if d),
    )
