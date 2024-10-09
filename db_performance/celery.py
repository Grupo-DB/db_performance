# celery.py na raiz do projeto, ao lado de manage.py
from __future__ import absolute_import, unicode_literals
#from management.tasks import enviar_emails
import os
from django.conf import settings
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready
from django.db.models import Q

# Definir o módulo de configuração do Django para o Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'db_performance.settings')

app = Celery('db_performance')

# Usar uma string aqui significa que o worker não precisará serializar
# a configuração do objeto para arquivos quando usá-la.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Descobrir automaticamente tarefas do seu projeto.
#app.autodiscover_tasks()
app.autodiscover_tasks(['db_performance', 'management'])
#app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


app.autodiscover_tasks(lambda: [n.name for n in app.get_app_configs()])

app.conf.beat_schedule = {
        'enviar-notificacoes-cada-5-minutos': {
        'task':'db_performance.tasks.enviar_notificacoes',
        'schedule': crontab(hour=0, minute=5),
    },    
#     'enviar-emails-cada-5-minutos': {
#         'task': 'db_performance.tasks.enviar_emails',
#         'schedule': crontab(hour=0, minute=0),
#     },
#     'enviar-media-avaliações': {
#         'task': 'db_performance.tasks.verificar_media_avaliacoes',
#         'schedule': crontab(month_of_year='1,4,7,10', day_of_month=28,hour=0, minute=0),
#     },
#      'enviar_notificacoes_experiencia': {
#         'task': 'db_performance.tasks.enviar_notificacoes_experiencia',
#         'schedule': crontab(hour=0, minute=0, day_of_week='monday'),
#     },
#     'verificar_media_avaliacoes_email': {
#         'task': 'db_performance.tasks.verificar_media_avaliacoes_email',
#         'schedule': crontab(month_of_year='1,4,7,10', day_of_month=28,hour=0, minute=0),
#     }, 
#     'verificar_contratos_experiencia_email': {
#         'task': 'db_performance.tasks.verificar_contratos_experiencia_email',
#         'schedule': crontab(hour=0, minute=0, day_of_week='monday'),
#     },
# }

}   
