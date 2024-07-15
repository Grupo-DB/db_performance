from django.core.mail import send_mail,EmailMessage
from django.conf import settings


def send_custom_email(subject, message, recipient_list):
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        recipient_list,
        fail_silently=False,
    )

def obterTrimestre(data):
    mes = data.month
    ano = data.year
    if mes in [1, 2, 3]:
        return f'Quarto Trimestre de {ano - 1}'
    elif mes in [4, 5, 6]:
        return f'Primeiro Trimestre de {ano}'
    elif mes in [7, 8, 9]:
        return f'Segundo Trimestre de {ano}'
    elif mes in [10, 11, 12]:
        return f'Terceiro Trimestre de {ano}'    
