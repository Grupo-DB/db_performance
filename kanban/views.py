from django.shortcuts import render
from django.db.models import Q
# Create your views here.
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.utils import timezone
from .models import KanbanColumn, KanbanTask
from .serializer import KanbanColumnSerializer, KanbanTaskSerializer, UserMinSerializer


class KanbanColumnViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = KanbanColumnSerializer

    # def get_queryset(self):
    #     return KanbanColumn.objects.filter(usuario=self.request.user).prefetch_related('tasks')

    def get_queryset(self):
        return KanbanColumn.objects.filter(
            usuario=self.request.user
        ).prefetch_related('tasks__responsavel', 'tasks__dono')

    def perform_create(self, serializer):
        serializer.save(usuario=self.request.user)


class KanbanTaskViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = KanbanTaskSerializer

    def get_queryset(self):
        user = self.request.user
        return KanbanTask.objects.filter(
            Q(coluna__usuario=user) | Q(responsavel=user)
        ).select_related('dono', 'responsavel', 'coluna')

    def perform_create(self, serializer):
        serializer.save(dono=self.request.user)

    @action(detail=True, methods=['patch'], url_path='mover')
    def mover_coluna(self, request, pk=None):
        """Move a tarefa para outra coluna (drag & drop)."""
        task = self.get_object()
        coluna_id = request.data.get('coluna_id')
        try:
            coluna = KanbanColumn.objects.get(pk=coluna_id, usuario=request.user)
        except KanbanColumn.DoesNotExist:
            return Response({'detail': 'Coluna inválida.'}, status=status.HTTP_400_BAD_REQUEST)

        task.coluna = coluna
        # marca concluído_em se moveu para coluna cujo título contém "conclui"
        if 'conclui' in coluna.titulo.lower() and not task.concluido_em:
            task.concluido_em = timezone.now()
        elif 'conclui' not in coluna.titulo.lower():
            task.concluido_em = None
        task.save()
        return Response(KanbanTaskSerializer(task, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='transferir')
    def transferir(self, request, pk=None):
        """Transfere a responsabilidade da tarefa para outro usuário."""
        task = self.get_object()
        responsavel_id = request.data.get('responsavel_id')
        try:
            responsavel = User.objects.get(pk=responsavel_id)
        except User.DoesNotExist:
            return Response({'detail': 'Usuário não encontrado.'}, status=status.HTTP_400_BAD_REQUEST)

        #task.responsavel = responsavel
        task.responsavel = User.objects.get(pk=responsavel_id) if responsavel_id else None
        task.save()
        return Response(KanbanTaskSerializer(task, context={'request': request}).data)
    
    @action(detail=False, methods=['get'], url_path='recebidas')
    def recebidas(self, request):
        """Tarefas transferidas para o usuário atual (não são de suas próprias colunas)."""
        tasks = KanbanTask.objects.filter(
            responsavel=request.user
        ).exclude(
            coluna__usuario=request.user
        ).select_related('dono', 'responsavel', 'coluna')
        return Response(KanbanTaskSerializer(tasks, many=True, context={'request': request}).data)