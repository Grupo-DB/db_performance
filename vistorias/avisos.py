"""
E-mails de suspensão, liberação, cancelamento de NC crítica e rejeição de correção (9.2, 9.3, 13).

Cada e-mail vira um ``EmailVistoria`` (prova de envio e reenvio). O envio sai numa thread depois
do commit, para não segurar a resposta do celular em campo.

O e-mail de suspensão espera a confirmação do adesivo (ela aparece no e-mail, 6.2) por no máximo
``ESPERA_ADESIVO`` segundos — o critério de aceite exige o e-mail em até 5 minutos. O comando
``enviar_emails_vistorias`` (cron a cada minuto) cobre reinício do servidor no meio da espera.
"""
import logging
import os
import threading
from datetime import timedelta
from email.mime.image import MIMEImage
from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from .models import DestinatarioNotificacao, EmailVistoria, NCCritica, Resposta, Suspensao

logger = logging.getLogger(__name__)

ESPERA_ADESIVO = 150  # segundos
VERMELHO, VERDE, AZUL, CINZA = '#b3261e', '#1e7b34', '#1f4e8c', '#555'


def _link(caminho: str) -> str:
    return f"{getattr(settings, 'FRONTEND_URL', 'https://managerdb.com.br').rstrip('/')}{caminho}"


def _nome(u) -> str:
    if not u:
        return '—'
    return u.get_full_name() or u.username


def _quando(dt) -> str:
    return timezone.localtime(dt).strftime('%d/%m/%Y %H:%M') if dt else '—'


def destinatarios(s: Suspensao, papeis=('GEO', 'SESMT', 'PCM', 'OUTRO'), com_gerente: bool = True) -> list[str]:
    """Gerente responsável (do cadastro) + lista configurável da unidade e da lista geral (3.5)."""
    emails = []
    eq = s.equipamento
    if com_gerente and eq.gerente and eq.gerente.email:
        emails.append(eq.gerente.email)
    qs = DestinatarioNotificacao.objects.filter(ativo=True, papel__in=papeis).filter(
        unidade__isnull=True) | DestinatarioNotificacao.objects.filter(ativo=True, papel__in=papeis, unidade=eq.unidade_id)
    for d in qs:
        emails.append(d.email)
    vistos, saida = set(), []
    for e in emails:
        if e and e.lower() not in vistos:
            vistos.add(e.lower())
            saida.append(e)
    return saida


# ── Preparar (cria o registro dentro da transação) ─────────────────────────────
def _criar(tipo, s, assunto, para, resposta=None) -> EmailVistoria:
    return EmailVistoria.objects.create(tipo=tipo, suspensao=s, resposta=resposta, assunto=assunto[:200],
                                        destinatarios='; '.join(para))


def _assunto(prefixo: str, s: Suspensao) -> str:
    eq = s.equipamento
    return f'[{prefixo}] {eq.tag} — {eq.descricao} — {s.vistoria.setor.nome}'


def preparar_suspensao(s: Suspensao, r: Resposta):
    return _criar(EmailVistoria.SUSPENSAO, s, _assunto('OPERAÇÃO SUSPENSA', s), destinatarios(s), r), ESPERA_ADESIVO


def preparar_cancelamento(s: Suspensao, r: Resposta):
    return _criar(EmailVistoria.CANCELAMENTO, s, _assunto('NC CRÍTICA CANCELADA', s), destinatarios(s), r), 0


def preparar_liberacao(s: Suspensao):
    return _criar(EmailVistoria.LIBERACAO, s, _assunto('LIBERADO', s), destinatarios(s)), 0


def preparar_rejeicao(s: Suspensao, nc: NCCritica, usuario):
    para = destinatarios(s, papeis=('PCM',), com_gerente=False)
    if nc.corrigida_por and nc.corrigida_por.email:
        para.append(nc.corrigida_por.email)
    return _criar(EmailVistoria.REJEICAO, s, _assunto('CORREÇÃO REJEITADA', s), para, nc.resposta), 0


def agendar(preparado) -> None:
    email, atraso = preparado

    def depois():
        if atraso:
            t = threading.Timer(atraso, enviar, args=(email.pk,))
            t.daemon = True
            t.start()
        else:
            threading.Thread(target=enviar, args=(email.pk,), daemon=True).start()
    if getattr(settings, 'VISTORIAS_EMAIL_SINCRONO', False):
        transaction.on_commit(lambda: enviar(email.pk) if not atraso else None)
    else:
        transaction.on_commit(depois)


def atualizar_adesivo_pendente(s: Suspensao) -> None:
    """Adesivo informado: manda já os e-mails de suspensão que estavam esperando por ele."""
    pendentes = list(s.emails.filter(tipo=EmailVistoria.SUSPENSAO, enviado_em__isnull=True).values_list('pk', flat=True))
    for pk in pendentes:
        if getattr(settings, 'VISTORIAS_EMAIL_SINCRONO', False):
            transaction.on_commit(lambda pk=pk: enviar(pk))
        else:
            transaction.on_commit(lambda pk=pk: threading.Thread(target=enviar, args=(pk,), daemon=True).start())


# ── Corpo ──────────────────────────────────────────────────────────────────────
def _linha(rotulo, valor):
    return (f'<tr><td style="padding:4px 12px 4px 0;color:{CINZA};font-size:13px;vertical-align:top;white-space:nowrap">{escape(rotulo)}</td>'
            f'<td style="padding:4px 0;font-size:14px;color:#1a1a1a">{valor}</td></tr>')


def _adesivo_txt(s: Suspensao) -> str:
    if s.adesivo == Suspensao.ADESIVO_AFIXADO:
        return f'afixado pelo avaliador em {_quando(s.adesivo_em)}'
    if s.adesivo == Suspensao.ADESIVO_NAO:
        return f'NÃO afixado ({_quando(s.adesivo_em)}) — motivo: {s.adesivo_justificativa}'
    return 'ainda não confirmado pelo avaliador'


def montar(email: EmailVistoria) -> tuple[str, str]:
    s = email.suspensao
    eq = s.equipamento
    v = s.vistoria
    r = email.resposta
    link = _link(f'/vistorias/suspensoes?id={s.pk}')
    linhas = [_linha('Equipamento', f'<b>{escape(eq.tag)}</b> · {escape(eq.descricao)} · Unidade {escape(v.unidade.sigla)} · Setor {escape(v.setor.nome)}')]
    if email.tipo == EmailVistoria.SUSPENSAO:
        cor, titulo = VERMELHO, f'A OPERAÇÃO DO EQUIPAMENTO {eq.tag} ESTÁ SUSPENSA'
        fotos = r.evidencias.count() if r else 0
        linhas += [
            _linha('Não conformidade', f'{escape(r.codigo)} — {escape(r.descricao)} (crítica)<br><i>{escape(r.descricao_problema)}</i>'),
            _linha('Registrada por', f'{escape(_nome(v.avaliador))} em {_quando(r.critica_confirmada_em)} · acompanhante '
                                     f'{escape(v.acompanhante_nome or "—")}{" (" + escape(v.acompanhante_cargo) + ")" if v.acompanhante_cargo else ""}'),
            _linha('Adesivo de operação suspensa', escape(_adesivo_txt(s))),
            _linha('Evidências', f'{fotos} arquivo(s) — <a href="{link}">abrir no sistema</a>'),
        ]
        rodape = ('Este aviso não substitui o bloqueio físico do equipamento. A liberação somente ocorrerá após correção '
                  'registrada pelo PCM e validação do SESMT ou do Gerente Executivo Operacional.')
    elif email.tipo == EmailVistoria.LIBERACAO:
        cor, titulo = VERDE, f'EQUIPAMENTO {eq.tag} LIBERADO PARA OPERAÇÃO'
        ncs = ''.join(f'<li>{escape(nc.resposta.codigo)} — {escape(nc.resposta.descricao)}: {escape(nc.correcao)}</li>'
                      for nc in s.ncs.filter(status=NCCritica.VALIDADA).select_related('resposta'))
        linhas += [
            _linha('Suspenso desde', _quando(s.iniciada_em)),
            _linha('Correções validadas', f'<ul style="margin:0;padding-left:18px">{ncs}</ul>'),
            _linha('Liberado por', f'{escape(_nome(s.liberada_por))} em {_quando(s.liberada_em)}'),
        ]
        if s.liberacao_observacao:
            linhas.append(_linha('Observação', escape(s.liberacao_observacao)))
        rodape = 'Retire o adesivo de OPERAÇÃO SUSPENSA do equipamento.'
    elif email.tipo == EmailVistoria.CANCELAMENTO:
        cor, titulo = AZUL, f'NC CRÍTICA CANCELADA — {eq.tag}'
        situacao = 'continua SUSPENSO por outra NC crítica' if s.aberta else 'não está mais suspenso por esta NC'
        linhas += [
            _linha('Não conformidade', f'{escape(r.codigo)} — {escape(r.descricao)}'),
            _linha('Cancelada por', f'{escape(_nome(r.cancelada_por))} em {_quando(r.cancelada_em)}'),
            _linha('Justificativa', escape(r.cancelamento_justificativa)),
            _linha('Situação', f'O equipamento {situacao}.'),
        ]
        rodape = 'Se o adesivo foi afixado só por esta NC, ele pode ser retirado.' if not s.aberta else ''
    else:
        cor, titulo = VERMELHO, f'CORREÇÃO REJEITADA — {eq.tag} CONTINUA SUSPENSO'
        nc = getattr(r, 'nc_critica', None)
        linhas += [
            _linha('Não conformidade', f'{escape(r.codigo)} — {escape(r.descricao)}'),
            _linha('Motivo da rejeição', f'<b>{escape(nc.rejeicao if nc else "")}</b>'),
        ]
        rodape = 'Registre uma nova correção com a comprovação no sistema.'

    html = f"""<!DOCTYPE html><html><body style="margin:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f6f9;padding:24px 0"><tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" border="0" style="max-width:640px;width:100%">
  <tr><td style="background:#fff;border-radius:12px 12px 0 0;padding:18px 28px;border-bottom:4px solid {cor}">
    <img src="cid:logo_db" alt="Grupo Dagoberto Barcellos" height="52" style="display:block;border:0"></td></tr>
  <tr><td style="background:{cor};padding:16px 28px;color:#fff;font-size:18px;font-weight:700;letter-spacing:.3px">{escape(titulo)}</td></tr>
  <tr><td style="background:#fff;padding:18px 28px"><table cellpadding="0" cellspacing="0" border="0">{''.join(linhas)}</table>
    {f'<p style="margin:16px 0 0;font-size:13px;color:{CINZA};line-height:1.5">{escape(rodape)}</p>' if rodape else ''}</td></tr>
  <tr><td style="background:#fff;padding:6px 28px 24px" align="center">
    <a href="{link}" style="display:inline-block;background:{cor};color:#fff;text-decoration:none;padding:11px 24px;border-radius:8px;font-size:14px;font-weight:700">Abrir no sistema</a></td></tr>
  <tr><td style="background:#2b2b2b;border-radius:0 0 12px 12px;padding:12px 28px;text-align:center;color:rgba(255,255,255,.7);font-size:11px">
    E-mail automático do ManagerDB — Vistorias de equipamentos. Destinatários configurados em Vistorias → Cadastros → Notificações.</td></tr>
</table></td></tr></table></body></html>"""
    texto = titulo + '\n\n' + '\n'.join(
        l.replace('</td><td', ': </td><td') for l in linhas)
    import re
    texto = re.sub(r'<[^>]+>', '', texto) + f'\n\n{rodape}\n\nAbrir no sistema: {link}\n'
    return html, texto


def enviar(email_id: int) -> bool:
    """Reivindica o registro (evita envio duplo entre timer, adesivo e cron) e envia."""
    agora = timezone.now()
    if not EmailVistoria.objects.filter(pk=email_id, enviado_em__isnull=True).update(enviado_em=agora):
        return False
    email = EmailVistoria.objects.select_related('suspensao__equipamento', 'suspensao__vistoria__setor',
                                                 'suspensao__vistoria__unidade', 'resposta').get(pk=email_id)
    para = [e.strip() for e in email.destinatarios.split(';') if e.strip()]
    try:
        if not para:
            raise RuntimeError('Nenhum destinatário cadastrado (Cadastros → Notificações).')
        html, texto = montar(email)
        msg = EmailMultiAlternatives(subject=email.assunto, body=texto, to=para)
        msg.mixed_subtype = 'related'
        msg.attach_alternative(html, 'text/html')
        logo = os.path.join(settings.MEDIA_ROOT, 'logoNovoDb.png')
        if os.path.exists(logo):
            with open(logo, 'rb') as f:
                img = MIMEImage(f.read())
            img.add_header('Content-ID', '<logo_db>')
            img.add_header('Content-Disposition', 'inline', filename='logo.png')
            msg.attach(img)
        msg.send(fail_silently=False)
        EmailVistoria.objects.filter(pk=email_id).update(tentativas=email.tentativas + 1, erro='')
        return True
    except Exception as exc:  # noqa: BLE001 — fica registrado e o cron tenta de novo
        logger.exception('vistorias: e-mail %s falhou', email_id)
        EmailVistoria.objects.filter(pk=email_id).update(enviado_em=None, tentativas=email.tentativas + 1, erro=str(exc)[:2000])
        return False


def enviar_pendentes(max_tentativas: int = 6) -> int:
    """Para o cron: suspensão esperando o adesivo há mais que a espera, ou qualquer outro que falhou."""
    limite = timezone.now() - timedelta(seconds=ESPERA_ADESIVO)
    ids = list(EmailVistoria.objects.filter(enviado_em__isnull=True, tentativas__lt=max_tentativas, criado_em__lte=limite)
               .values_list('pk', flat=True)) + list(
        EmailVistoria.objects.filter(enviado_em__isnull=True, tentativas__lt=max_tentativas)
        .exclude(tipo=EmailVistoria.SUSPENSAO).values_list('pk', flat=True))
    return sum(1 for pk in dict.fromkeys(ids) if enviar(pk))
