from django.db import models

# Create your models here.
class Periodo(models.Model):
    dataInicio = models.DateField()
    dataFim = models.DateField()

    def __str__(self):
        return f"Periodo from {self.dataInicio} to {self.dataFim}"