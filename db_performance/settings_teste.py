"""
Settings mínimos para rodar os testes do app `whatsapp` sem encostar no banco de
produção.

O `settings.py` do projeto aponta para o MySQL de produção; `manage.py test` com
ele criaria um `test_db_manager` LÁ. Por isso os testes rodam assim:

    python manage.py test whatsapp.tests --settings=db_performance.settings_teste

Só entram os apps de que o `whatsapp` depende — o resto do projeto não precisa
subir para exercitar as regras de visibilidade.
"""
SECRET_KEY = 'apenas-para-teste'
DEBUG = False

# `kanban` entra porque `ConversaDetailSerializer` conta as tarefas abertas a
# partir do atendimento (`conversa.tarefas_kanban`): sem o app, qualquer teste que
# passe pelo serializer quebra com AttributeError. Ele só depende de `auth`.
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'whatsapp',
    'kanban',
]

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}

# As migrations do projeto são gitignored: as tabelas de teste saem direto dos
# modelos, que é o que interessa aqui.
MIGRATION_MODULES = {'whatsapp': None, 'kanban': None, 'auth': None, 'contenttypes': None}

USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'
