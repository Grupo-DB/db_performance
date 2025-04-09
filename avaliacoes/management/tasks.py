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

caminho_logo = "media/logotelalogin.png" 

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

    avaliados_sem_avaliacao = avaliador.avaliados.filter(
        ~Q(avaliacoes_avaliado__periodo=trimestre_atual)
    ).distinct()

    notificacoes_enviadas = 0
    for avaliado in avaliados_sem_avaliacao:
        if not Avaliacao.objects.filter(avaliador=avaliador, avaliado=avaliado, periodo=trimestre_atual).exists():
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
        periodo_atual = Periodo.objects.filter(dataInicio__lte=now, dataFim__gte=now).latest('dataFim')
        #periodo_atual = Periodo.objects.filter(dataInicio__lte=now, dataFim__gte=now).first()
    except Periodo.DoesNotExist:
        print("Nenhum período de avaliação ativo encontrado para a data atual.")
        return

    # Buscar avaliados sem avaliação neste trimestre
    avaliados_sem_avaliacao = Avaliado.objects.exclude(
        avaliacoes_avaliado__periodo=trimestre_atual
    ).distinct()

    # Buscar os avaliadores desses avaliados
    avaliadores_com_pendencias = Avaliador.objects.filter(
        avaliados__in=avaliados_sem_avaliacao
    ).distinct()

    if not avaliadores_com_pendencias.exists():
        print("Nenhum avaliador com pendências.")
        return

    # Construir relatório
    dados_relatorio = []
    for avaliador in avaliadores_com_pendencias:
        avaliados = avaliados_sem_avaliacao.filter(avaliadores=avaliador)
        nomes_avaliados = list(avaliados.values_list('nome', flat=True))
        if nomes_avaliados:
            dados_relatorio.append({
                'avaliador': avaliador.nome,
                'avaliados': nomes_avaliados
            })

    # Buscar e-mails do grupo RHGestor
    try:
        grupo_rh = Group.objects.get(name="RHGestorTeste")
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

    data_inicio_formatada = periodo_atual.dataInicio.strftime('%d-%m-%Y')
    data_fim_formatada = periodo_atual.dataFim.strftime('%d-%m-%Y')

    # Render HTML
    html_content = render_to_string('emails/relatorio_rh.html', {
        'dados_relatorio': dados_relatorio,
        #'trimestre': trimestre_atual,
        'data_inicio': data_inicio_formatada,
        'data_fim': data_fim_formatada,
    })
    text_content = strip_tags(html_content)

    email = EmailMultiAlternatives(
        subject,
        text_content,
        from_email='rh@dagobertobarcellos.com.br',
        to=emails_rh,
    )
    email.attach_alternative(html_content, "text/html")

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

    # Encontrar todos os avaliados que não foram avaliados no trimestre atual
    avaliados_sem_avaliacao = Avaliado.objects.filter(
        ~Q(avaliacoes_avaliado__periodo=trimestre_atual)
    ).distinct()

    # Encontrar os avaliadores desses avaliados
    avaliadores_sem_avaliacao = Avaliador.objects.filter(
        avaliados__in=avaliados_sem_avaliacao
    ).distinct()

    notificacoes_enviadas = 0
    # Enviar notificações para os avaliadores sem avaliações no trimestre atual
    for avaliador in avaliadores_sem_avaliacao:
        for avaliado in avaliador.avaliados.filter(id__in=avaliados_sem_avaliacao).all():
            # Verificar se o avaliado ainda não foi avaliado no período atual
            if not Avaliacao.objects.filter(avaliador=avaliador, avaliado=avaliado, periodo=trimestre_atual).exists():
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
    subject = 'RH Dagoberto Barcellos'
    now = timezone.now()
    trimestre_atual = obterTrimestre(now)

    try:
        periodo_atual = Periodo.objects.filter(dataInicio__lte=now, dataFim__gte=now).latest('dataFim')
        #periodo_atual = Periodo.objects.filter(dataInicio__lte=now, dataFim__gte=now).first()
    except Periodo.DoesNotExist:
        print("Nenhum período de avaliação ativo encontrado para a data atual.")
        return

    # Encontrar todos os avaliados sem avaliação no trimestre atual
    avaliados_sem_avaliacao = Avaliado.objects.exclude(
        avaliacoes_avaliado__periodo=trimestre_atual
    ).distinct()

    # Encontrar os avaliadores desses avaliados
    avaliadores_com_pendencias = Avaliador.objects.filter(
        avaliados__in=avaliados_sem_avaliacao
    ).distinct()

    if not avaliadores_com_pendencias.exists():
        print("Nenhum avaliador com pendências.")
        return

    for avaliador in avaliadores_com_pendencias:
        # Lista de avaliados desse avaliador com pendências
        nomes_avaliados = list(
            avaliados_sem_avaliacao.filter(avaliadores=avaliador)
            .values_list('nome', flat=True)
        )

        if not nomes_avaliados:
            continue

        data_inicio_formatada = periodo_atual.dataInicio.strftime('%d-%m-%Y')
        data_fim_formatada = periodo_atual.dataFim.strftime('%d-%m-%Y')

        # Render HTML com base no template
        html_content = render_to_string('emails/pendencia_avaliacao.html', {
            'avaliador': avaliador,
            'nomes_avaliados': nomes_avaliados,
            'data_inicio': data_inicio_formatada,
            'data_fim': data_fim_formatada,
        })
        text_content = strip_tags(html_content)

        # Cria o e-mail
        email = EmailMultiAlternatives(
            subject,
            text_content,
            from_email='rh@dagobertobarcellos.com.br',  # ou settings.DEFAULT_FROM_EMAIL
            to=[avaliador.email],
        )
        email.attach_alternative(html_content, "text/html")

        # Gera o PDF para esse avaliador
        pdf_buffer = gerar_pdf_avaliados(avaliador.nome, nomes_avaliados, caminho_logo, trimestre_atual)
        email.attach(f"Avaliacoes_Pendentes_{avaliador.nome}.pdf", pdf_buffer.read(), 'application/pdf')

        try:
            email.send()
            print(f"Email enviado para {avaliador.email}")
        except Exception as e:
            print(f"Erro ao enviar email para {avaliador.email}: {e}")





@shared_task
def enviar_email_para_avaliador(avaliador_id):
    subject = 'RH Dagoberto Barcellos'
    now = timezone.now()
    trimestre_atual = obterTrimestre(now)

     # Obter o período atual com base na data atual
    try:
        periodo_atual = Periodo.objects.filter(dataInicio__lte=now, dataFim__gte=now).latest('dataFim')
        #periodo_atual = Periodo.objects.filter(dataInicio__lte=now, dataFim__gte=now).first()
    except Periodo.DoesNotExist:
        print("Nenhum período de avaliação ativo encontrado para a data atual.")
        return

    try:
        avaliador = Avaliador.objects.get(id=avaliador_id)
    except Avaliador.DoesNotExist:
        print(f"Avaliador com ID {avaliador_id} não encontrado.")
        return

    # Encontrar avaliados sem avaliação no período atual
    avaliados_sem_avaliacao = Avaliado.objects.filter(
        avaliadores=avaliador
    ).exclude(
        avaliacoes_avaliado__periodo=periodo_atual
    ).distinct()

    if not avaliados_sem_avaliacao.exists():
        print(f"Nenhum avaliado pendente para o avaliador {avaliador.nome}")
        return

    nomes_avaliados = [av.nome for av in avaliados_sem_avaliacao]

    data_inicio_formatada = periodo_atual.dataInicio.strftime('%d-%m-%Y')
    data_fim_formatada = periodo_atual.dataFim.strftime('%d-%m-%Y')

    # Renderizar HTML do e-mail com as datas de início e fim do período
    html_content = render_to_string('emails/pendencia_avaliacao.html', {
        'avaliador': avaliador,
        'nomes_avaliados': nomes_avaliados,
        'data_inicio': data_inicio_formatada,
        'data_fim': data_fim_formatada,
    })
    text_content = strip_tags(html_content)

    email = EmailMultiAlternatives(
        subject,
        text_content,
        from_email='rh@dagobertobarcellos.com.br',
        to=[avaliador.email],
    )
    email.attach_alternative(html_content, "text/html")

    # Gerar PDF dinâmico (supondo que você tenha uma função para isso)
    pdf_buffer = gerar_pdf_avaliados(avaliador.nome, nomes_avaliados,caminho_logo,trimestre_atual)
    email.attach(f"Avaliacoes_Pendentes_{avaliador.nome}.pdf", pdf_buffer.read(), 'application/pdf')

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

