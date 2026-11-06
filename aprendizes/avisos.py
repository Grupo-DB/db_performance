"""Avisos por e-mail do período de experiência (contrato 30 + 60) — 06/11/2026.

Roda pelo comando ``manage.py avisar_experiencia``, uma vez por dia (cron). O sino do
sistema é calculado no navegador (``experiencia-vencimento-alerts.service.ts``) com as
mesmas regras; aqui é só o e-mail.

Degraus por etapa pendente (1º vencimento = 30º dia; prorrogação = 90º dia):
  7  → "vence em N dias" (qualquer dia entre 7 e 1 antes; se o cron ficar parado, cai aqui uma vez)
  0  → "vence hoje"
 -1  → "venceu e a etapa segue pendente" (só até 30 dias depois — a planilha antiga deixou
       pendências de meses atrás, e elas não devem disparar e-mail no primeiro dia de uso)

Idempotência: cada degrau enviado vira um ``gestaoDocumentos.AvisoVencimento`` apontando
para a ``Etapa`` (é genérico por content type), então não precisa de migration nova e
rodar duas vezes no dia não reenvia.

Um e-mail por execução, com a lista inteira — o RH recebe um resumo do dia, não um
e-mail por pessoa.
"""
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from gestaoDocumentos.aprovacoes import AZUL, LARANJA, VERMELHO, _enviar, _montar_html, email_usuario
from gestaoDocumentos.models import AvisoVencimento

from .models import Acompanhamento, Etapa

DIAS_ANTES = 7
DIAS_DEPOIS = 30
MARCO_PROXIMO, MARCO_HOJE, MARCO_VENCIDO = 7, 0, -1

# Quem recebe: os membros ativos deste grupo + a lista fixa do settings.
GRUPO_AVISO = 'RHGestor'


def marco_do_dia(dias):
    if dias < -DIAS_DEPOIS or dias > DIAS_ANTES:
        return None
    if dias < 0:
        return MARCO_VENCIDO
    return MARCO_HOJE if dias == 0 else MARCO_PROXIMO


def etapas_a_avisar(hoje=None):
    """Etapas pendentes que estão num degrau hoje e ainda não foram avisadas nele."""
    hoje = hoje or date.today()
    ct = ContentType.objects.get_for_model(Etapa)
    etapas = (
        Etapa.objects.select_related('acompanhamento')
        .filter(
            situacao=Etapa.PENDENTE,
            tipo__in=[Etapa.PRIMEIRO_VENCIMENTO, Etapa.PRORROGACAO],
            acompanhamento__situacao=Acompanhamento.EM_ANDAMENTO,
            vencimento__gte=hoje - timedelta(days=DIAS_DEPOIS),
            vencimento__lte=hoje + timedelta(days=DIAS_ANTES),
        )
        .order_by('vencimento', 'acompanhamento__nome')
    )
    ja = set(
        AvisoVencimento.objects.filter(content_type=ct, object_id__in=[e.id for e in etapas])
        .values_list('object_id', 'marco')
    )
    pendentes = []
    for e in etapas:
        dias = (e.vencimento - hoje).days
        marco = marco_do_dia(dias)
        if marco is not None and (e.id, marco) not in ja:
            pendentes.append({'etapa': e, 'dias': dias, 'marco': marco, 'content_type': ct})
    return pendentes


def destinatarios():
    usuarios = User.objects.filter(groups__name=GRUPO_AVISO, is_active=True).distinct()
    emails = [email_usuario(u) for u in usuarios]
    emails += list(getattr(settings, 'EMAILS_AVISO_EXPERIENCIA', []) or [])
    return sorted({e.strip() for e in emails if e and e.strip()})


def _periodo(etapa):
    return '1º período (30 dias)' if etapa.tipo == Etapa.PRIMEIRO_VENCIMENTO else 'Fim da experiência (90 dias)'


def _situacao(p):
    dias = p['dias']
    if dias < 0:
        return f'venceu há {abs(dias)} dia(s) — etapa ainda pendente'
    if dias == 0:
        return 'vence hoje'
    return f'vence em {dias} dia(s)'


def avisar(pendentes, simular=False):
    """Manda UM e-mail com todos os pendentes e registra os degraus. Devolve os e-mails."""
    if not pendentes:
        return []
    emails = destinatarios()
    if simular or not emails:
        # Sem destinatário não registra: quando a lista for configurada, o aviso sai.
        return emails

    vencidos = sum(1 for p in pendentes if p['dias'] < 0)
    hoje = sum(1 for p in pendentes if p['dias'] == 0)
    if vencidos:
        cor, titulo = VERMELHO, 'Período de experiência: há etapas vencidas'
    elif hoje:
        cor, titulo = LARANJA, 'Período de experiência: vencimentos hoje'
    else:
        cor, titulo = AZUL, 'Período de experiência: vencimentos próximos'

    linhas = []
    for p in pendentes:
        e = p['etapa']
        a = e.acompanhamento
        quem = a.nome + (f' — {a.setor}' if a.setor else '')
        linhas.append((
            e.vencimento.strftime('%d/%m/%Y'),
            f'<b>{quem}</b><br>{_periodo(e)} · {_situacao(p)}',
        ))

    base = str(settings.FRONTEND_URL).rstrip('/')
    link = f'{base}/avaliacoes/acompanhamento-experiencia'
    corpo_html = _montar_html(
        titulo=titulo,
        cor_titulo=cor,
        subtitulo=f'{len(pendentes)} colaborador(es) para avaliar e decidir',
        linhas=linhas,
        cta_texto='Abrir o Acompanhamento',
        cta_url=link,
        rodape='Aviso automático do Acompanhamento Período de Experiência. '
               'O aviso para quando a etapa é marcada como concluída, dispensada ou desligada.',
    )
    corpo_txt = '\n'.join(
        [titulo, ''] + [
            f'{p["etapa"].vencimento.strftime("%d/%m/%Y")} — {p["etapa"].acompanhamento.nome}: '
            f'{_periodo(p["etapa"])}, {_situacao(p)}'
            for p in pendentes
        ] + ['', f'Abrir no ManagerDB: {link}']
    )
    assunto = f'[Experiência] {len(pendentes)} vencimento(s) — {titulo.split(": ", 1)[1]}'
    _enviar(assunto, corpo_txt, corpo_html, emails)

    destino = ', '.join(emails)
    for p in pendentes:
        AvisoVencimento.objects.get_or_create(
            content_type=p['content_type'], object_id=p['etapa'].id, marco=p['marco'],
            defaults={'data_vencimento': p['etapa'].vencimento, 'destinatarios': destino},
        )
    return emails
