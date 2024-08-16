# from celery import shared_task
# from django.core.mail import send_mail
# from django.utils import timezone
# from management.models import Avaliador, Avaliado, Avaliacao, Colaborador
# from rest_framework.response import Response
# from management.utils import obterTrimestre,send_custom_email
# from rest_framework import status
# from django.db.models import Q
# from notifications.signals import notify
# from rest_framework.response import Response
# from datetime import timedelta
# from django.contrib.auth.models import User,Group

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

#     # Retornar uma mensagem simples que pode ser serializada como JSON
#     return f"Notificações enviadas: {notificacoes_enviadas}"

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

# @shared_task
# def enviar_notificacoes_experiencia():
#         # Calcular a data limite para contratos de experiência (90 dias)
#         data_limite = timezone.now() - timedelta(days=90)

#         # Encontrar colaboradores com contrato de experiência próximo do término
#         colaboradores_experiencia = Colaborador.objects.filter(
#             tipocontrato='experiencia',
#             data_admissao__lte=data_limite
#         )

#         if not colaboradores_experiencia.exists():
#             return Response({"error": "Nenhum colaborador encontrado com contrato de experiência próximo ao término"}, status=status.HTTP_404_NOT_FOUND)

#         grupos = Group.objects.filter(name__in=['RHGestor', 'Admin'])
#         usuarios_grupo = Colaborador.objects.filter(user__groups__in=grupos).distinct()

#         if not usuarios_grupo.exists():
#             return Response({"error": "Nenhum usuário encontrado nos grupos RHGestor ou Admin"}, status=status.HTTP_404_NOT_FOUND)

#         # Enviar notificações para os usuários do grupo RHGestor e Admin
#         for colaborador in colaboradores_experiencia:
#             for usuario in usuarios_grupo:
#                 notify.send(
#                     sender=colaborador,  # Quem envia a notificação (o usuário autenticado)
#                     recipient=usuario.user,  # Usuário que receberá a notificação
#                     verb='Contrato de Experiência Próximo ao Término',  # Verbo da notificação
#                     description=f'O colaborador {colaborador.nome} está com o contrato de experiência próximo ao término. Data de Admissão: {colaborador.data_admissao}'  # Descrição da notificação
#                 )

#         print("Email enviado com sucesso!")


# @shared_task
# def verificar_media_avaliacoes():
#         # Obter todos os avaliados
#         todos_avaliados = Avaliado.objects.all()  # Altere conforme sua lógica de filtragem

#         # Obter usuários dos grupos RHGestor e Admin
#         grupos = Group.objects.filter(name__in=['RHGestor', 'Admin'])
#         usuarios_grupo = Colaborador.objects.filter(user__groups__in=grupos).distinct()

#         resultados = []
#         avaliados_piora = []

#         for avaliado in todos_avaliados:
#             avaliacoes = Avaliacao.objects.filter(avaliado=avaliado).order_by('-create_at')[:2]

#             if len(avaliacoes) < 2:
#                 continue  # Se não houver pelo menos duas avaliações, não há o que comparar

#             ultimas_avaliacoes = list(avaliacoes)
#             ultima_avaliacao = ultimas_avaliacoes[0]
#             avaliacao_anterior = ultimas_avaliacoes[1]

#             # Carregar perguntas e respostas
#             if isinstance(ultima_avaliacao.perguntasRespostas, str):
#                 perguntas_respostas_ultima = json.loads(ultima_avaliacao.perguntasRespostas)
#             else:
#                 perguntas_respostas_ultima = ultima_avaliacao.perguntasRespostas

#             if isinstance(avaliacao_anterior.perguntasRespostas, str):
#                 perguntas_respostas_anterior = json.loads(avaliacao_anterior.perguntasRespostas)
#             else:
#                 perguntas_respostas_anterior = avaliacao_anterior.perguntasRespostas

#             # Calcular médias
#             media_ultima = calcular_media_perguntas_respostas([perguntas_respostas_ultima])
#             media_anterior = calcular_media_perguntas_respostas([perguntas_respostas_anterior])

#             # Adicionar resultado à lista de resultados
#             resultados.append({
#                 'avaliado': avaliado.nome,
#                 'media_ultima': media_ultima,
#                 'media_anterior': media_anterior,
#                 'diferenca': media_ultima - media_anterior
#             })

#             # Verificar se a nota caiu mais de um ponto
#             if (media_ultima - media_anterior) < -1:
#                 avaliados_piora.append({
#                     'avaliado': avaliado.nome,
#                     'media_ultima': media_ultima,
#                     'media_anterior': media_anterior,
#                     'diferenca': media_ultima - media_anterior
#                 })

#         # Enviar notificações se houver algum avaliado com piora na nota
#         if avaliados_piora:
#             for usuario in usuarios_grupo:
#                 for item in avaliados_piora:
#                     notify.send(
#                         sender=usuario,  # Quem envia a notificação (o usuário autenticado)
#                         recipient=usuario.user,  # Usuário que receberá a notificação
#                         verb='Nota das avaliações caíram mais de um ponto',  # Verbo da notificação
#                         description=f"{item['avaliado']}: caiu de {item['media_anterior']:.1f} para {item['media_ultima']:.1f}, diferença: {item['diferenca']:.1f}"  # Descrição da notificação
#                     )

#         print("Email enviado com sucesso!")

# ##############################################-------------EMAILS--------------------------#######################



# @shared_task
# def verificar_contratos_experiencia_email():
#     # Calcular a data limite para contratos de experiência (90 dias)
#     data_limite = timezone.now() - timedelta(days=90)

#     # Encontrar colaboradores com contrato de experiência próximo do término
#     colaboradores_experiencia = Colaborador.objects.filter(
#         tipocontrato='experiencia',
#         data_admissao__lte=data_limite
#     )

#     if not colaboradores_experiencia.exists():
#         return

#     grupos = Group.objects.filter(name__in=['RHGestor', 'Admin'])
#     usuarios_grupo = Colaborador.objects.filter(user__groups__in=grupos).distinct()

#     # Construir a lista de destinatários
#     recipient_list = [colaborador.email for colaborador in usuarios_grupo]

#     # Verificar se há destinatários
#     if not recipient_list:
#         return

#     # Construir o corpo do email incluindo os colaboradores com contrato de experiência próximo do término
#     subject = "Contratos de Experiência Próximos ao Término"
#     message = "Os seguintes colaboradores estão com o contrato de experiência próximo ao término:\n\n"
#     for colaborador in colaboradores_experiencia:
#         message += f"- {colaborador.nome}, Data de Admissão: {colaborador.data_admissao}\n"
#         try:
#             send_custom_email(subject, message, recipient_list)
#             print("Email enviado com sucesso!")
#         except Exception as e:
#             print("Erro ao enviar email")



# def calcular_media_perguntas_respostas(perguntasRespostas):
#     soma_respostas = 0
#     total_perguntas = 0

#     for perguntas_respostas in perguntasRespostas:
#         for pergunta, resposta in perguntas_respostas.items():
#             if isinstance(resposta, dict):
#                 # Se resposta for um dicionário, precisamos desaninhá-lo
#                 for sub_pergunta, sub_resposta in resposta.items():
#                     try:
#                         resposta_num = float(sub_resposta)  # Converte a sub-resposta para um número
#                         soma_respostas += resposta_num
#                         total_perguntas += 1
#                     except ValueError:
#                         # Se não puder converter, pula a sub-resposta
#                         continue
#             else:
#                 try:
#                     resposta_num = float(resposta)  # Converte a resposta para um número
#                     soma_respostas += resposta_num
#                     total_perguntas += 1
#                 except ValueError:
#                     # Se não puder converter, pula a resposta
#                     continue

#     if total_perguntas == 0:
#         return 0

#     return soma_respostas / total_perguntas



# @shared_task
# def verificar_media_avaliacoes_email():
#     # Obter todos os avaliados
#     todos_avaliados = Avaliado.objects.all()  # Altere conforme sua lógica de filtragem

#     # Obter usuários dos grupos RHGestor e Admin
#     grupos = Group.objects.filter(name__in=['RHGestor', 'Admin'])
#     usuarios_grupo = Colaborador.objects.filter(user__groups__in=grupos).distinct()

#     # Construir a lista de destinatários
#     recipient_list = [colaborador.email for colaborador in usuarios_grupo]

#     resultados = []
#     avaliados_piora = []

#     for avaliado in todos_avaliados:
#         avaliacoes = Avaliacao.objects.filter(avaliado=avaliado).order_by('-create_at')[:2]

#         if len(avaliacoes) < 2:
#             continue  # Se não houver pelo menos duas avaliações, não há o que comparar

#         ultimas_avaliacoes = list(avaliacoes)
#         ultima_avaliacao = ultimas_avaliacoes[0]
#         avaliacao_anterior = ultimas_avaliacoes[1]

#         # Carregar perguntas e respostas
#         if isinstance(ultima_avaliacao.perguntasRespostas, str):
#             perguntas_respostas_ultima = json.loads(ultima_avaliacao.perguntasRespostas)
#         else:
#             perguntas_respostas_ultima = ultima_avaliacao.perguntasRespostas

#         if isinstance(avaliacao_anterior.perguntasRespostas, str):
#             perguntas_respostas_anterior = json.loads(avaliacao_anterior.perguntasRespostas)
#         else:
#             perguntas_respostas_anterior = avaliacao_anterior.perguntasRespostas

#         # Calcular médias
#         media_ultima = calcular_media_perguntas_respostas([perguntas_respostas_ultima])
#         media_anterior = calcular_media_perguntas_respostas([perguntas_respostas_anterior])

#         # Adicionar resultado à lista de resultados
#         resultados.append({
#             'avaliado': avaliado.nome,
#             'media_ultima': media_ultima,
#             'media_anterior': media_anterior,
#             'diferenca': media_ultima - media_anterior
#         })

#         # Verificar se a nota caiu mais de um ponto
#         if (media_ultima - media_anterior) < -1:
#             avaliados_piora.append({
#                 'avaliado': avaliado.nome,
#                 'media_ultima': media_ultima,
#                 'media_anterior': media_anterior,
#                 'diferenca': media_ultima - media_anterior
#             })

#     # Enviar email se houver algum avaliado com piora na nota
#     if avaliados_piora:
#         subject = "Nota das avaliações caíram mais de um ponto"
#         message = "Os seguintes avaliados tiveram uma queda de mais de um ponto na última avaliação:\n\n"
#         for item in avaliados_piora:
#             message += f"{item['avaliado']}: caiu de {item['media_anterior']:.1f} para {item['media_ultima']:.1f}, diferença: {item['diferenca']:.1f}\n"

#         try:
#             send_custom_email(subject, message, recipient_list)
#             print("Email enviado com sucesso!")
#         except Exception as e:
#             print(f"Erro ao enviar email: {e}")
