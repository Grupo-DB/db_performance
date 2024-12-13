from django.db import models
from django.contrib.auth.models import Group, Permission
from django.dispatch import receiver
from django.db.models.signals import pre_save

class Realizado(models.Model):
    id = models.AutoField(primary_key=True)
    empresa = models.CharField(max_length=255, blank=True, null=True)
    

# Create your models here.
