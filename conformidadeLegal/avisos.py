"""
O que precisa de atenção na conformidade — usado pelo painel (com filtros) e pelo
e-mail de avisos (tarefa diária `enviar_avisos`).

Prazos de antecedência vêm de ConfiguracaoAvisos (tela "Avisos e e-mails"):
verificação de requisito, prazo de plano, validade de licença e de documento de
terceiro. O e-mail vai em duas formas: cada responsável recebe só os requisitos e
planos dele; os destinatários da equipe recebem o resumo completo.
"""
import logging
import os
from datetime import date, timedelta
from email.mime.image import MIMEImage
from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.utils import timezone

from .models import ConfiguracaoAvisos, DocumentoTerceiro, Norma, PlanoAcao, Requisito, Terceiro

logger = logging.getLogger(__name__)

TIPOS_COM_VALIDADE = ('LICENCA', 'OUTORGA', 'TAC')
# Plano em aberto: nem concluído à mão nem com a tarefa do Kanban concluída.
PLANO_ABERTO = Q(concluido_em__isnull=True) & (Q(tarefa__isnull=True) | Q(tarefa__concluido_em__isnull=True))

FILTROS = ('tema', 'responsavel', 'unidade', 'norma', 'terceiro')


def ler_filtros(params) -> dict:
    """Filtros do painel vindos da query string (só os conhecidos e preenchidos)."""
    return {k: params.get(k) for k in FILTROS if params.get(k) not in (None, '')}


def filtrar_requisitos(qs, filtros: dict, prefixo: str = ''):
    """Aplica os filtros a um queryset de Requisito (ou de algo ligado a ele, via `prefixo`)."""
    f = filtros or {}
    mapa = {'tema': 'tema', 'responsavel': 'responsavel', 'norma': 'norma', 'terceiro': 'terceiro'}
    for chave, campo in mapa.items():
        if f.get(chave):
            qs = qs.filter(**{f'{prefixo}{campo}': f[chave]})
    if f.get('unidade'):
        qs = qs.filter(**{f'{prefixo}unidade__iexact': f['unidade']})
    return qs


def requisitos_aplicaveis(filtros=None):
    return filtrar_requisitos(Requisito.objects.filter(ativo=True, aplicabilidade='APLICAVEL'), filtros)


def planos_abertos(filtros=None):
    """Planos em aberto dos requisitos filtrados. O responsável/terceiro do filtro vale para o do plano."""
    f = dict(filtros or {})
    qs = PlanoAcao.objects.filter(PLANO_ABERTO)
    responsavel, terceiro = f.pop('responsavel', None), f.pop('terceiro', None)
    if responsavel:
        qs = qs.filter(responsavel=responsavel)
    if terceiro:
        qs = qs.filter(terceiro=terceiro)
    return filtrar_requisitos(qs, f, prefixo='requisito__')


def pendencias(filtros=None, hoje=None) -> dict:
    """Listas do que pede atenção, já ordenadas — mesma regra no painel e no e-mail."""
    cfg = ConfiguracaoAvisos.atual()
    hoje = hoje or date.today()
    filtros = filtros or {}
    aplic = requisitos_aplicaveis(filtros)
    verificacoes = list(aplic.filter(proxima_verificacao__isnull=False,
                                     proxima_verificacao__lte=hoje + timedelta(days=cfg.dias_verificacao))
                        .select_related('norma', 'responsavel__colaborador').order_by('proxima_verificacao'))
    planos = list(planos_abertos(filtros).filter(prazo__isnull=False, prazo__lte=hoje + timedelta(days=cfg.dias_plano))
                  .select_related('requisito__norma', 'responsavel__colaborador', 'terceiro').order_by('prazo'))

    licencas = Norma.objects.filter(tipo__in=TIPOS_COM_VALIDADE, validade__isnull=False,
                                    validade__lte=hoje + timedelta(days=cfg.dias_licenca)).exclude(situacao='REVOGADA')
    if filtros.get('norma'):
        licencas = licencas.filter(pk=filtros['norma'])
    if filtros.get('tema'):
        licencas = licencas.filter(tema=filtros['tema'])

    documentos = []
    if not (filtros.get('responsavel') or filtros.get('norma') or filtros.get('tema') or filtros.get('unidade')):
        terceiros = Terceiro.objects.filter(ativo=True).prefetch_related('documentos')
        if filtros.get('terceiro'):
            terceiros = terceiros.filter(pk=filtros['terceiro'])
        for t in terceiros:
            for d in t.documentos_vigentes():
                if d.obrigatorio and d.situacao in ('VENCIDO', 'PENDENTE', 'A_VENCER'):
                    documentos.append(d)
        ordem = {'VENCIDO': 0, 'PENDENTE': 1, 'A_VENCER': 2}
        documentos.sort(key=lambda d: (ordem[d.situacao], d.dias_para_vencer if d.dias_para_vencer is not None else 0))

    return {'config': cfg, 'hoje': hoje, 'verificacoes': verificacoes, 'planos': planos,
            'licencas': list(licencas.order_by('validade')), 'documentos': documentos}


# ── E-mail ────────────────────────────────────────────────────────────────
AZUL = '#1d4f91'


def _dias(d, hoje):
    n = (d - hoje).days
    if n < 0:
        return f'venceu há {-n} dia{"s" if n < -1 else ""}', '#c62828'
    if n == 0:
        return 'vence hoje', '#c62828'
    return f'vence em {n} dia{"s" if n > 1 else ""}', '#b26a00' if n <= 15 else '#555'


def _secao(titulo, linhas):
    if not linhas:
        return '', '', 0
    html_linhas = ''.join(
        f'<tr><td style="padding:8px 0;border-bottom:1px solid #eef2f6;font-size:14px;color:#222">{escape(t)}'
        f'<div style="font-size:12px;color:#888">{escape(sub)}</div></td>'
        f'<td style="padding:8px 0 8px 12px;border-bottom:1px solid #eef2f6;font-size:13px;white-space:nowrap;'
        f'color:{cor};text-align:right;font-weight:600">{escape(prazo)}</td></tr>'
        for t, sub, prazo, cor in linhas)
    html = (f'<h3 style="margin:22px 0 6px;font-size:15px;color:{AZUL}">{escape(titulo)} ({len(linhas)})</h3>'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0">{html_linhas}</table>')
    texto = f'\n{titulo} ({len(linhas)})\n' + '\n'.join(f'- {t} ({sub}) — {prazo}' for t, sub, prazo, _ in linhas)
    return html, texto, len(linhas)


def montar_email(p: dict, nome: str, completo: bool) -> tuple[str, str, int] | None:
    """(html, texto, total de itens) ou None se não há nada a avisar."""
    hoje = p['hoje']
    secoes = []
    linhas = []
    for r in p['verificacoes']:
        prazo, cor = _dias(r.proxima_verificacao, hoje)
        ref = f' — {r.referencia}' if r.referencia else ''
        linhas.append((r.descricao[:160], f'{r.norma.identificacao}{ref}', prazo, cor))
    secoes.append(_secao('Verificações de requisitos', linhas))
    linhas = []
    for pl in p['planos']:
        prazo, cor = _dias(pl.prazo, hoje)
        extra = f' · {pl.terceiro}' if pl.terceiro_id else ''
        linhas.append((pl.descricao[:160], f'{pl.requisito.norma.identificacao}{extra}', prazo, cor))
    secoes.append(_secao('Planos de ação', linhas))
    if completo:
        linhas = []
        for n in p['licencas']:
            prazo, cor = _dias(n.validade, hoje)
            linhas.append((n.identificacao, n.ementa[:120], prazo, cor))
        secoes.append(_secao('Licenças, outorgas e TACs', linhas))
        linhas = []
        for d in p['documentos']:
            if d.situacao == 'PENDENTE':
                prazo, cor = 'falta enviar', '#c62828'
            else:
                prazo, cor = _dias(d.validade, hoje)
            linhas.append((str(d.terceiro), d.get_tipo_display() + (f' — {d.descricao}' if d.descricao else ''), prazo, cor))
        secoes.append(_secao('Documentos de terceiros', linhas))

    total = sum(s[2] for s in secoes)
    if not total:
        return None
    link = f"{getattr(settings, 'FRONTEND_URL', 'https://managerdb.com.br').rstrip('/')}/conformidade/painel"
    cfg = p['config']
    intro = (f'Olá, {escape(nome)}. Estes itens da Conformidade Legal pedem atenção '
             f'(verificações com até {cfg.dias_verificacao} dias, planos com até {cfg.dias_plano} dias'
             + (f', licenças com até {cfg.dias_licenca} dias e documentos de terceiros com até {cfg.dias_documento} dias'
                if completo else '') + ' de antecedência).')
    html = f"""<!doctype html><html><body style="margin:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f6f9;padding:24px 0"><tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" border="0" style="max-width:640px;width:100%">
  <tr><td style="background:#fff;border-radius:12px 12px 0 0;padding:20px 28px;border-bottom:4px solid {AZUL}">
    <img src="cid:logo_db" alt="Grupo Dagoberto Barcellos" height="56" style="display:block;border:0">
  </td></tr>
  <tr><td style="background:#fff;padding:22px 28px 8px">
    <h1 style="margin:0 0 8px;font-size:20px;color:#1a1a1a">Conformidade Legal — avisos</h1>
    <p style="margin:0;font-size:14px;color:#555;line-height:1.5">{intro}</p>
    {''.join(s[0] for s in secoes)}
  </td></tr>
  <tr><td style="background:#fff;padding:18px 28px 26px" align="center">
    <a href="{link}" style="display:inline-block;background:{AZUL};color:#fff;text-decoration:none;padding:12px 26px;border-radius:8px;font-size:14px;font-weight:700">Abrir o painel</a>
  </td></tr>
  <tr><td style="background:{AZUL};border-radius:0 0 12px 12px;padding:14px 28px;text-align:center;color:rgba(255,255,255,.75);font-size:11px">
    E-mail automático do ManagerDB. Os prazos e quem recebe são ajustados em Conformidade → Painel → Avisos e e-mails.
  </td></tr>
</table></td></tr></table></body></html>"""
    texto = f'Olá, {nome}.\nItens da Conformidade Legal que pedem atenção:\n' + ''.join(s[1] for s in secoes) + f'\n\nPainel: {link}\n'
    return html, texto, total


def enviar_email(destinatario: str, assunto: str, html: str, texto: str) -> None:
    msg = EmailMultiAlternatives(subject=assunto, body=texto, to=[destinatario])
    msg.mixed_subtype = 'related'
    msg.attach_alternative(html, 'text/html')
    logo = os.path.join(settings.MEDIA_ROOT, 'logoNovoDb.png')
    if os.path.exists(logo):
        with open(logo, 'rb') as f:
            img = MIMEImage(f.read())
        img.add_header('Content-ID', '<logo_db>')
        img.add_header('Content-Disposition', 'inline', filename='logo.png')
        msg.attach(img)
    msg.send()


def destinatarios(cfg: ConfiguracaoAvisos) -> list[tuple[str, str, dict, bool]]:
    """(e-mail, nome, filtros, completo) de cada mensagem a mandar hoje."""
    from .serializers import nome_usuario
    lista = [(e, 'equipe', {}, True) for e in cfg.lista_destinatarios()]
    ja = {e.lower() for e, *_ in lista}
    if cfg.email_responsaveis:
        from django.contrib.auth.models import User
        ids = set(Requisito.objects.filter(ativo=True, aplicabilidade='APLICAVEL', responsavel__isnull=False)
                  .values_list('responsavel', flat=True))
        ids |= set(PlanoAcao.objects.filter(PLANO_ABERTO, responsavel__isnull=False).values_list('responsavel', flat=True))
        for u in User.objects.filter(pk__in=ids, is_active=True).exclude(email=''):
            if u.email.lower() in ja:
                continue  # já recebe o resumo completo
            lista.append((u.email, nome_usuario(u), {'responsavel': u.pk}, False))
    return lista


def dia_de_enviar(cfg: ConfiguracaoAvisos, agora=None) -> bool:
    agora = timezone.localtime(agora or timezone.now())
    if agora.weekday() > 4:
        return False
    if cfg.ultimo_envio and timezone.localtime(cfg.ultimo_envio).date() == agora.date():
        return False
    return cfg.email_frequencia == 'DIARIA' or agora.weekday() == cfg.email_dia_semana


def enviar_avisos(forcar=False, so_para: str | None = None) -> dict:
    """
    Manda os e-mails do dia. `forcar` ignora frequência e "já enviado hoje";
    `so_para` manda o resumo completo só para esse endereço (teste da tela) e não
    marca o envio.
    """
    cfg = ConfiguracaoAvisos.atual()
    if so_para:
        p = pendencias()
        msg = montar_email(p, 'teste', True)
        if not msg:
            return {'enviados': 0, 'sem_pendencias': 1, 'erros': []}
        enviar_email(so_para, f'[ManagerDB] Conformidade — {msg[2]} item(ns) pedem atenção (teste)', msg[0], msg[1])
        return {'enviados': 1, 'sem_pendencias': 0, 'erros': []}
    if not cfg.email_ativo or (not forcar and not dia_de_enviar(cfg)):
        return {'enviados': 0, 'sem_pendencias': 0, 'erros': [], 'pulado': True}

    enviados, vazios, erros = 0, 0, []
    for email, nome, filtros, completo in destinatarios(cfg):
        msg = montar_email(pendencias(filtros), nome, completo)
        if not msg:
            vazios += 1
            continue
        try:
            enviar_email(email, f'[ManagerDB] Conformidade — {msg[2]} item(ns) pedem atenção', msg[0], msg[1])
            enviados += 1
        except Exception as e:  # noqa: BLE001 — um endereço ruim não derruba os outros
            logger.warning('Aviso de conformidade para %s falhou: %s', email, e)
            erros.append(f'{email}: {e}'[:200])
    cfg.ultimo_envio = timezone.now()
    cfg.ultimo_envio_resumo = (f'{enviados} e-mail(s) enviado(s), {vazios} sem pendência'
                               + (f', {len(erros)} com erro' if erros else ''))[:255]
    cfg.save(update_fields=['ultimo_envio', 'ultimo_envio_resumo'])
    return {'enviados': enviados, 'sem_pendencias': vazios, 'erros': erros}
