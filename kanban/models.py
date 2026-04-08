# Create your models here.
from django.db import models
from django.contrib.auth.models import User

class KanbanColumn(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='kanban_columns')
    titulo = models.CharField(max_length=100)
    cor = models.CharField(max_length=20, default='#6366f1')
    ordem = models.PositiveIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['ordem', 'criado_em']

    def __str__(self):
        return f"{self.usuario.username} - {self.titulo}"


class KanbanTask(models.Model):
    PRIORIDADE_CHOICES = [
        ('baixa', 'Baixa'),
        ('media', 'Média'),
        ('alta', 'Alta'),
    ]

    coluna = models.ForeignKey(KanbanColumn, on_delete=models.CASCADE, related_name='tasks')
    dono = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tasks_criadas')
    responsavel = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tasks_responsavel'
    )  # permite transferência para outro usuário
    titulo = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    prioridade = models.CharField(max_length=10, choices=PRIORIDADE_CHOICES, default='media')
    tags = models.JSONField(default=list, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    prazo = models.DateField(null=True, blank=True)
    concluido_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['criado_em']

    def __str__(self):
        return self.titulo