from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

# Define o módulo de configurações padrão do Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'db_performance.settings')

app = Celery('db_performance',  broker='amqp://guest@localhost//')

# Lê as configurações do Django no namespace CELERY
app.config_from_object('django.conf:settings', namespace='CELERY')

# Descobre e carrega automaticamente tarefas dos módulos 'tasks.py'
app.autodiscover_tasks(['db_performance.management'])

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

