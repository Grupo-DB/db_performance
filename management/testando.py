import os
import django

# Configurar o Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'db_performance.settings')
django.setup()

from management.tasks import send_emails_task

send_emails_task()



