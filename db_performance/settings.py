from datetime import timedelta
from pathlib import Path
import os
from celery.schedules import crontab
from dotenv import load_dotenv



# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CHARSET = 'utf-8'

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-duqfuj4z2nqmikw@@_cffl4&)c-$qo)t#^cg(!=(c6%-p)1)tu'
#Simple JWT SECRET_KEY
SECRET_KEY_JWT = 'lkshdgkhjgfçhsdçgjkhskjdfghlshjgçlfs'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']
CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True

#AUTH_USER_MODEL = 'management.CustomUser'
# Application definition

load_dotenv()
#VARIAVEIS DE AMBIENTE DA OPENAI
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
AZURE_OPENAI_ENDPOINT = os.environ.get('AZURE_OPENAI_ENDPOINT')
AZURE_OPENAI_DEPLOYMENT = os.environ.get('AZURE_OPENAI_DEPLOYMENT')
AZURE_OPENAI_API_VERSION = os.environ.get('AZURE_OPENAI_API_VERSION')
# Verifique se as variáveis existem antes de usar
if not OPENAI_API_KEY or not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_DEPLOYMENT or not AZURE_OPENAI_API_VERSION:
    raise ValueError("Variáveis de ambiente do Azure OpenAI não configuradas.")

CELERY_RESULT_BACKEND = 'django-db'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_extensions',
    'rolepermissions',
    'autenticacoes',
    "rest_framework",
    "corsheaders",
    'simple_history',
    'django_filters',
    'avaliacoes.management',
    'rest_framework_simplejwt',
    'django_celery_beat',
    'django_celery_results',
    'notifications',
    'avaliacoes.datacalc',
    'bisGerenciais.dashboardOperacoes.cal',
    'bisGerenciais.dashboardOperacoes.home',
    'bisGerenciais.dashboardOperacoes.britagem',
    'bisGerenciais.dashboardOperacoes.rebritagem',
    'bisGerenciais.dashboardOperacoes.calcario',
    'bisGerenciais.dashboardOperacoes.fertilizante',
    'bisGerenciais.dashboardOperacoes.argamassa',
    'baseOrcamentaria.orcamento',
    'baseOrcamentaria.realizado',
    'baseOrcamentaria.dre',
    'baseOrcamentaria.grupoitens',
    'baseOrcamentaria.custoproducao',
    'baseOrcamentaria.curva',
    'baseOrcamentaria.ppr',
    'controleQualidade.ensaio',
    'controleQualidade.calculosEnsaio',
    'controleQualidade.plano',
    'controleQualidade.ordem',
    'controleQualidade.amostra',
    'controleQualidade.analise',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "corsheaders.middleware.CorsMiddleware",
]

ROOT_URLCONF = 'db_performance.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'db_performance.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
#autenticações
DATABASES = {
#    'sga': {
#         'ENGINE': 'mssql',
#         'NAME': 'DB',
#         'USER': 'DBCONSULTA',
#         'PASSWORD': 'DB@@2023**',
#         'HOST': '45.6.118.50',
#         'PORT': '',
#         'OPTIONS': {
#             'driver': 'ODBC Driver 17 for SQL Server',
#         }
#     },

    'default':{
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'db_performance',
        'USER':'grupodb',
        'PASSWORD': '!@#123qweQWE',
        'HOST': '172.50.10.79',
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',  # para MySQL
        },
    }

    #Dev Enviroment
    # 'default':{
    #     'ENGINE': 'django.db.backends.mysql',
    #     'NAME': 'db_performance',
    #     'USER':'root',
    #     'PASSWORD': '!@#123qweQWE',
    #     'HOST': 'localhost',
    #     'PORT': '3306',
    #     'OPTIONS': {
    #         'charset': 'utf8mb4',  # para MySQL
    #     },
    # }
}


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'America/Sao_Paulo'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/



# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=120),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "BLACKLIST_AFTER_ROTATION": False,
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
 
}
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        #'rest_framework.authentication.SessionAuthentication',
        #'rest_framework.authentication.BasicAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
       # 'rest_framework.permissions.IsAdminUser',  # Pode ser modificado para 'AllowAny' se necessário
    ),
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend'
    ]
    
}

MEDIA_ROOT = os.path.join(BASE_DIR,'media')
MEDIA_URL = '/media/'
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
#opara desenvolvimento
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]


FRONTEND_URL = 'http://172.50.10.79:80'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'  # Altere isso de acordo com o seu cliente de e-mail
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'grupodagobertobarcellos@gmail.com'  # Seu endereço de e-mail
EMAIL_HOST_PASSWORD = 'zrwehfczwugpsssp'  # Sua senha de e-mail



CELERY_BROKER_URL = 'redis://172.50.10.79:6379/0'
CELERY_RESULT_BACKEND = 'redis://172.50.10.79:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'


CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]


