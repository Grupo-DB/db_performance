# tasks.py
#from celery import Celery
from . views import send_email_view2
from celery import shared_task
from notifications.signals import notify
from django.contrib.auth.models import User
from management.models import Avaliacao

@shared_task
def send_emails_task():
    from django.test import RequestFactory
    factory = RequestFactory()
    request = factory.post('http://localhost:8000/management/email/', {
        'subject': 'Avaliação de Funcionários Pendentes!',
        'message': 'Você possui avaliações de funcionários pendentes. Restam 5 dias para realiza-las!'
    })
    send_email_view2(request)

# @app.task(run_every=crontab(minute=0, hour=0))  # Executa a cada dia à meia-noite
# def send_emails_task():
#     from django.test import RequestFactory
#     factory = RequestFactory()
#     request = factory.post('http://localhost:8000/management/email/', {
#         'subject': 'Assunto Automático',
#         'message': 'Mensagem Automática'
#     })
#     send_email_view2(request)

# @shared_task
# def enviar_notificacoes():
#     # Filtra os avaliadores e avaliados que precisam de notificações
#     avaliadores = User.objects.filter(groups__name='Avaliador')
#     avaliados_sem_avaliacoes = Avaliacao.objects.filter(avaliador__in=avaliadores, status='pendente')

#     for avaliacao in avaliados_sem_avaliacoes:
#         avaliador = avaliacao.avaliador
#         avaliado = avaliacao.avaliado

#         # Enviar notificação
#         notify.send(
#             sender=avaliado,
#             recipient=avaliador,
#             verb='Você tem uma nova avaliação pendente para',
#             description=f'{avaliado.username}'
#         )