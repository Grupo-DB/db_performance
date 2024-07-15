cd /opt/manager/db_performance

# Ativar o ambiente virtual
source venv/bin/activate

# Iniciar seu projeto Python
python3 manage.py runserver 0.0.0.0:8008

# Iniciar o Celery Worker em background
celery -A db_performance worker -l info &

# Iniciar o Celery Beat em background
celery -A db_performance beat -l info &
