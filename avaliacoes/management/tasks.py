import os
from email.mime.image import MIMEImage
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.contrib.auth.models import Group
from django.utils.html import strip_tags
from celery import shared_task
from django.db import IntegrityError
from django.utils import timezone
from django.contrib.auth.models import User
from avaliacoes.management.models import Avaliado, Avaliador, Avaliacao, Colaborador
from avaliacoes.datacalc.models import Periodo
from avaliacoes.management.utils import obterTrimestre, send_custom_email
from notifications.signals import notify
from django.db.models import Q
from . pdf_utils import gerar_pdf_avaliados
from .gerar_pdf_rh import gerar_pdf_rh
from .vinculos import avaliados_pendentes, avaliadores_com_pendencias

caminho_logo = "media/logotelalogin.png"


def _anexar_logo(email):
    """Anexa o logo do Grupo Dagoberto Barcellos inline (cid:logo_db), no mesmo padrão dos e-mails de pedidos."""
    logo_path = os.path.join(settings.MEDIA_ROOT, 'logoNovoDb.png')
    if not os.path.exists(logo_path):
        return
    with open(logo_path, 'rb') as f:
        logo = MIMEImage(f.read())
    logo.add_header('Content-ID', '<logo_db>')
    logo.add_header('Content-Disposition', 'inline', filename='logoNovoDb.png')
    email.attach(logo)

# Links dos botões: o login do ManagerDB devolve a pessoa a esta URL depois de entrar.
SITE = 'https://managerdb.com.br'
LINK_AVALIAR = f'{SITE}/avaliacoes/novaliacao'
LINK_PAINEL = f'{SITE}/avaliacoes/avaliacoes'


def _periodo_vigente():
    """O período que o RH definiu por último na tela (mesmo critério do GET /periodo), se hoje estiver dentro dele.

    Cada "Definir Período" grava uma linha nova e as antigas ficam. Filtrar as que cobrem hoje e pegar
    a de maior dataFim escolhia um período velho e mais longo (01/03 a 30/10) no lugar do atual (05/10 a 24/10).
    """
    periodo = Periodo.objects.latest('id')
    hoje = timezone.localdate()
    if not (periodo.dataInicio <= hoje <= periodo.dataFim):
        raise Periodo.DoesNotExist
    return periodo


def _contexto_prazo(periodo_atual, trimestre):
    """Datas do período em dd/mm/aaaa e o selo do prazo (cor muda quando aperta)."""
    hoje = timezone.localdate()
    restam = (periodo_atual.dataFim - hoje).days
    if restam < 0:
        texto, cor, fundo, borda = 'Prazo encerrado', '#c62828', '#fdecec', '#f6c9c9'
    elif restam == 0:
        texto, cor, fundo, borda = 'Termina hoje', '#c62828', '#fdecec', '#f6c9c9'
    elif restam <= 3:
        texto, cor, fundo, borda = f'Faltam {restam} dia{"s" if restam > 1 else ""}', '#d97706', '#fff7e6', '#ffe2a8'
    else:
        texto, cor, fundo, borda = f'Faltam {restam} dias', '#004EAE', '#f0f6ff', '#d6e5fb'
    return {
        'trimestre': trimestre,
        'data_inicio': periodo_atual.dataInicio.strftime('%d/%m/%Y'),
        'data_fim': periodo_atual.dataFim.strftime('%d/%m/%Y'),
        'prazo_texto': texto, 'prazo_cor': cor, 'prazo_fundo': fundo, 'prazo_borda': borda,
    }


def _pendentes_para_email(pendentes):
    """Nome, iniciais e "cargo · setor" de cada avaliado pendente, em ordem alfabética."""
    linhas = []
    for p in pendentes.select_related('cargo', 'ambiente').order_by('nome'):
        nome = (p.nome or '').title()
        detalhe = ' · '.join(x for x in [p.cargo.nome if p.cargo_id else '', p.ambiente.nome if p.ambiente_id else ''] if x)
        palavras = [w for w in nome.split() if w.lower() not in ('da', 'de', 'do', 'das', 'dos', 'e')]
        iniciais = (palavras[0][0] + palavras[-1][0]) if len(palavras) > 1 else nome[:2]
        linhas.append({'nome': nome, 'detalhe': detalhe, 'iniciais': iniciais.upper()})
    return linhas


def _email_avaliador(avaliador, pendentes, periodo_atual, trimestre):
    """Monta (sem enviar) a cobrança de um avaliador: HTML, texto simples e PDF anexo."""
    lista = _pendentes_para_email(pendentes)
    ctx = _contexto_prazo(periodo_atual, trimestre)
    ctx.update({
        'avaliador': avaliador,
        'primeiro_nome': (avaliador.nome or '').split()[0].title() if avaliador.nome else '',
        'pendentes': lista,
        'total': len(lista),
        'link': LINK_AVALIAR,
    })
    html_content = render_to_string('emails/pendencia_avaliacao.html', ctx)
    texto = (
        f"Olá, {ctx['primeiro_nome']}.\n\n"
        f"Você tem {len(lista)} avaliação(ões) pendente(s) do {trimestre}.\n"
        f"Prazo: {ctx['data_inicio']} a {ctx['data_fim']} ({ctx['prazo_texto'].lower()}).\n\n"
        + '\n'.join(f"- {x['nome']}" + (f" ({x['detalhe']})" if x['detalhe'] else '') for x in lista)
        + f"\n\nAvaliar agora: {LINK_AVALIAR}\n\nRH Grupo Dagoberto Barcellos"
    )
    plural = 'avaliações pendentes' if len(lista) != 1 else 'avaliação pendente'
    assunto = f"[Avaliação de desempenho] Você tem {len(lista)} {plural} — prazo {ctx['data_fim']}"

    email = EmailMultiAlternatives(assunto, texto, from_email='rh@dagobertobarcellos.com.br', to=[avaliador.email])
    email.attach_alternative(html_content, "text/html")
    _anexar_logo(email)
    nomes = [x['nome'] for x in lista]
    pdf_buffer = gerar_pdf_avaliados(avaliador.nome, nomes, caminho_logo, trimestre)
    email.attach(f"Avaliacoes_Pendentes_{avaliador.nome}.pdf", pdf_buffer.read(), 'application/pdf')
    return email


@shared_task
def enviar_notificacoes(usuario_id):
    now = timezone.now()
    trimestre_atual = obterTrimestre(now)

    try:
        usuario = User.objects.get(id=usuario_id)
        avaliador = Avaliador.objects.get(user=usuario)
    except User.DoesNotExist:
        print("Usuário não encontrado.")
        return
    except Avaliador.DoesNotExist:
        print("Avaliador não encontrado.")
        return

    notificacoes_enviadas = 0
    for avaliado in avaliados_pendentes(avaliador, trimestre_atual):
        try:
            notify.send(
                sender=avaliador,
                recipient=usuario,
                verb='Nova notificação!!',
                description=f'Nova avaliação pendente no período atual para {avaliado.nome}'
            )
            notificacoes_enviadas += 1
        except IntegrityError as e:
            print(f"Erro ao enviar notificação: {str(e)}")

    print(f"Notificações enviadas para o usuário {usuario.username}: {notificacoes_enviadas}")


@shared_task
def notificar_rh_gestor():
    subject = 'RH Dagoberto Barcellos - Avaliações Pendentes'
    now = timezone.now()
    trimestre_atual = obterTrimestre(now)

    try:
        periodo_atual = _periodo_vigente()
    except Periodo.DoesNotExist:
        print("Nenhum período de avaliação ativo encontrado para a data atual.")
        return

    # Avaliadores com pendência no trimestre (individual + setor, ver vinculos.py)
    pendencias = avaliadores_com_pendencias(trimestre_atual)
    if not pendencias:
        print("Nenhum avaliador com pendências.")
        return

    # Construir relatório (mais pendências primeiro: é onde o RH precisa agir)
    dados_relatorio = sorted(
        (
            {'avaliador': (avaliador.nome or '').title(),
             'avaliados': [n.title() for n in pendentes.order_by('nome').values_list('nome', flat=True)]}
            for avaliador, pendentes in pendencias
        ),
        key=lambda x: (-len(x['avaliados']), x['avaliador']),
    )

    # Buscar e-mails do grupo RHGestor
    try:
        grupo_rh = Group.objects.get(name="RHGestor")
        usuarios_rh = grupo_rh.user_set.all()
        print(f"Usuários no grupo RHGestor: {[u.username for u in usuarios_rh]}")

        colaboradores_rh = Colaborador.objects.filter(user__in=usuarios_rh)
        print(f"Colaboradores vinculados: {[c.nome for c in colaboradores_rh]}")

        emails_rh = list(
            colaboradores_rh.exclude(email__isnull=True)
            .exclude(email='')
            .values_list('email', flat=True)
        )
        print(f"E-mails encontrados: {emails_rh}")

    except Group.DoesNotExist:
        print("Grupo RHGestor não encontrado.")
        return

    if not emails_rh:
        print("Nenhum e-mail válido encontrado no grupo RHGestor.")
        return

    ctx = _contexto_prazo(periodo_atual, trimestre_atual)
    total_colaboradores = sum(len(x['avaliados']) for x in dados_relatorio)
    ctx.update({
        'dados_relatorio': dados_relatorio,
        'total_avaliadores': len(dados_relatorio),
        'total_colaboradores': total_colaboradores,
        'link': LINK_PAINEL,
    })
    html_content = render_to_string('emails/relatorio_rh.html', ctx)
    text_content = (
        f"Avaliações pendentes — {trimestre_atual}\n"
        f"{len(dados_relatorio)} avaliador(es), {total_colaboradores} avaliação(ões) a fazer. "
        f"Prazo {ctx['data_inicio']} a {ctx['data_fim']} ({ctx['prazo_texto'].lower()}).\n\n"
        + '\n'.join(f"{x['avaliador']} ({len(x['avaliados'])}): {', '.join(x['avaliados'])}" for x in dados_relatorio)
        + f"\n\nPainel: {LINK_PAINEL}"
    )
    subject = (f"[Avaliação de desempenho] {len(dados_relatorio)} avaliador(es) com "
               f"{total_colaboradores} pendência(s) — {trimestre_atual}")

    email = EmailMultiAlternatives(
        subject,
        text_content,
        from_email='rh@dagobertobarcellos.com.br',
        to=emails_rh,
    )
    email.attach_alternative(html_content, "text/html")
    _anexar_logo(email)

    # Gera o PDF consolidado
    pdf_buffer = gerar_pdf_rh(dados_relatorio,caminho_logo, trimestre_atual)
    email.attach(f"Avaliacoes_Pendentes_RH.pdf", pdf_buffer.read(), 'application/pdf')

    try:
        email.send()
        print("E-mail enviado para RHGestor.")
    except Exception as e:
        print(f"Erro ao enviar e-mail para RHGestor: {e}")



# @shared_task
# def enviar_emails():
#     subject = ('RH Dagoberto Barcellos')
#     message = ('Avaliações ainda pendentes no período atual')

#     if not subject or not message:
#         print("Erro ao enviar email")

#     now = timezone.now()
#     trimestre_atual = obterTrimestre(now)  # Supondo que obterTrimestre() retorna o trimestre atual

#     # Encontrar todos os avaliados sem avaliação no trimestre atual
#     avaliados_sem_avaliacao = Avaliado.objects.exclude(
#         avaliacoes_avaliado__periodo=trimestre_atual
#     ).distinct()

#     # Encontrar os avaliadores desses avaliados
#     avaliadores_sem_avaliacao = Avaliador.objects.filter(
#         avaliados__in=avaliados_sem_avaliacao
#     ).distinct()

#     if not avaliadores_sem_avaliacao.exists():
#         print("Erro ao enviar email")

#     for avaliador in avaliadores_sem_avaliacao:
#         # Filtrar os avaliados pertencentes ao avaliador atual
#         avaliados_do_avaliador = avaliados_sem_avaliacao.filter(avaliadores=avaliador)

#         # Construir o corpo do email incluindo os avaliados sem avaliação para o avaliador atual
#         email_body = f"{message}\n\nAvaliados sem avaliação no trimestre atual:\n"
#         for avaliado in avaliados_do_avaliador:
#             email_body += f"- {avaliado.nome}\n"

#         try:
#             send_custom_email(subject, email_body, [avaliador.email])
#         except Exception as e:
#             print("Erro ao enviar email")

#     print("Email enviado com sucesso!")

@shared_task
def enviar_notificacoes_para_todos_avaliadores():
    now = timezone.now()
    trimestre_atual = obterTrimestre(now)

    notificacoes_enviadas = 0
    # Enviar notificações para os avaliadores com pendência no trimestre atual
    for avaliador, pendentes in avaliadores_com_pendencias(trimestre_atual):
        for avaliado in pendentes:
            # Verificar se o avaliador tem um usuário associado antes de enviar a notificação
            if avaliador.user:
                try:
                    notify.send(
                        sender=avaliador,
                        recipient=avaliador.user,
                        verb='Nova notificação!!',
                        description=f'Nova avaliação pendente no período atual para {avaliado.nome}'
                    )
                    notificacoes_enviadas += 1
                except IntegrityError as e:
                    # Log do erro e continue
                    print(f"Erro ao enviar notificação: {str(e)}")    

@shared_task
def enviar_emails_completos_para_todos_avaliadores():
    now = timezone.now()
    trimestre_atual = obterTrimestre(now)

    try:
        periodo_atual = _periodo_vigente()
    except Periodo.DoesNotExist:
        print("Nenhum período de avaliação ativo encontrado para a data atual.")
        return

    pendencias = avaliadores_com_pendencias(trimestre_atual)
    if not pendencias:
        print("Nenhum avaliador com pendências.")
        return

    for avaliador, pendentes in pendencias:
        if not avaliador.email or not pendentes.exists():
            continue
        email = _email_avaliador(avaliador, pendentes, periodo_atual, trimestre_atual)

        try:
            email.send()
            print(f"Email enviado para {avaliador.email}")
        except Exception as e:
            print(f"Erro ao enviar email para {avaliador.email}: {e}")





@shared_task
def enviar_email_para_avaliador(avaliador_id):
    now = timezone.now()
    trimestre_atual = obterTrimestre(now)

     # Obter o período atual com base na data atual
    try:
        periodo_atual = _periodo_vigente()
    except Periodo.DoesNotExist:
        print("Nenhum período de avaliação ativo encontrado para a data atual.")
        return

    try:
        avaliador = Avaliador.objects.get(id=avaliador_id)
    except Avaliador.DoesNotExist:
        print(f"Avaliador com ID {avaliador_id} não encontrado.")
        return

    # Encontrar avaliados sem avaliação no período atual
    avaliados_sem_avaliacao = avaliados_pendentes(avaliador, trimestre_atual)

    if not avaliados_sem_avaliacao.exists():
        print(f"Nenhum avaliado pendente para o avaliador {avaliador.nome}")
        return

    if not avaliador.email:
        print(f"Avaliador {avaliador.nome} sem e-mail cadastrado.")
        return
    email = _email_avaliador(avaliador, avaliados_sem_avaliacao, periodo_atual, trimestre_atual)

    try:
        email.send()
        print(f"Email enviado para {avaliador.email}")
    except Exception as e:
        print(f"Erro ao enviar email: {e}")


# from django.utils import timezone
# from django.db.models import Q
# from django.db import IntegrityError
# from django.contrib.auth.models import User
# from avaliacoes.management.models import Avaliacao, Avaliado, Avaliador
# from avaliacoes.management.utils import obterTrimestre
# from celery import shared_task
# from notifications.signals import notify

# @shared_task
# def enviar_notificacao_para_usuario_especifico(usuario_id):
#     try:
#         trimestre_atual = obterTrimestre(timezone.now())

#         usuario = User.objects.get(id=usuario_id)
#         avaliador = Avaliador.objects.get(user=usuario)

#         avaliados_sem_avaliacao = avaliador.avaliados.filter(
#             ~Q(avaliacoes_avaliado__periodo=trimestre_atual)
#         ).distinct()

#         notificacoes_enviadas = 0

#         for avaliado in avaliados_sem_avaliacao:
#             if not Avaliacao.objects.filter(avaliador=avaliador, avaliado=avaliado, periodo=trimestre_atual).exists():
#                 try:
#                     notify.send(
#                         sender=avaliador,
#                         recipient=usuario,
#                         verb='Nova notificação!!',
#                         description=f'Nova avaliação pendente no período atual para {avaliado.nome}'
#                     )
#                     notificacoes_enviadas += 1
#                 except IntegrityError as e:
#                     print(f"Erro ao enviar notificação: {str(e)}")

#         return f"Notificações enviadas para o usuário {usuario.username}: {notificacoes_enviadas}"
    
#     except User.DoesNotExist:
#         return "Usuário não encontrado."
#     except Avaliador.DoesNotExist:
#         return "Avaliador associado ao usuário não encontrado."
#     except Exception as e:
#         return f"Erro ao enviar notificações: {str(e)}"
    
# @shared_task
# def enviar_notificacoes():
#     now = timezone.now()
#     trimestre_atual = obterTrimestre(now)

#     # Encontrar todos os avaliados que não foram avaliados no trimestre atual
#     avaliados_sem_avaliacao = Avaliado.objects.filter(
#         ~Q(avaliacoes_avaliado__periodo=trimestre_atual)
#     ).distinct()

#     # Encontrar os avaliadores desses avaliados
#     avaliadores_sem_avaliacao = Avaliador.objects.filter(
#         avaliados__in=avaliados_sem_avaliacao
#     ).distinct()

#     notificacoes_enviadas = 0
#     # Enviar notificações para os avaliadores sem avaliações no trimestre atual
#     for avaliador in avaliadores_sem_avaliacao:
#         for avaliado in avaliador.avaliados.filter(id__in=avaliados_sem_avaliacao).all():
#             # Verificar se o avaliado ainda não foi avaliado no período atual
#             if not Avaliacao.objects.filter(avaliador=avaliador, avaliado=avaliado, periodo=trimestre_atual).exists():
#                 # Verificar se o avaliador tem um usuário associado antes de enviar a notificação
#                 if avaliador.user:
#                     try:
#                         notify.send(
#                             sender=avaliador,
#                             recipient=avaliador.user,
#                             verb='Nova notificação!!',
#                             description=f'Nova avaliação pendente no período atual para {avaliado.nome}'
#                         )
#                         notificacoes_enviadas += 1
#                     except IntegrityError as e:
#                         # Log do erro e continue
#                         print(f"Erro ao enviar notificação: {str(e)}")    

