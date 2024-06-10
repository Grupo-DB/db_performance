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