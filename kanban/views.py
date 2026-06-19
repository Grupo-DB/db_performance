from django.shortcuts import render, get_object_or_404
from django.db.models import Q
# Create your views here.
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.contrib.auth.models import User
from django.utils import timezone
from .models import KanbanBoard, KanbanColumn, KanbanTask, KanbanAnexo
from .serializer import (
    KanbanBoardSerializer, KanbanAnexoSerializer,
    KanbanColumnSerializer, KanbanTaskSerializer, UserMinSerializer,
)


class KanbanBoardViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = KanbanBoardSerializer

    def get_queryset(self):
        user = self.request.user
        return KanbanBoard.objects.filter(
            Q(criado_por=user) | Q(membros=user)
        ).distinct().prefetch_related('membros', 'colunas__tasks')

    def perform_create(self, serializer):
        board = serializer.save(criado_por=self.request.user)
        board.membros.add(self.request.user)
        KanbanColumn.objects.create(
            quadro=board,
            titulo='Concluídas',
            cor='#22c55e',
            ordem=9999,
            is_concluida=True,
        )

    @action(detail=True, methods=['post'], url_path='adicionar-membro')
    def adicionar_membro(self, request, pk=None):
        board = self.get_object()
        if board.criado_por != request.user:
            return Response({'detail': 'Apenas o criador pode gerenciar membros.'}, status=status.HTTP_403_FORBIDDEN)
        user_id = request.data.get('user_id')
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({'detail': 'Usuário não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        board.membros.add(user)
        return Response(KanbanBoardSerializer(board, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='remover-membro')
    def remover_membro(self, request, pk=None):
        board = self.get_object()
        if board.criado_por != request.user:
            return Response({'detail': 'Apenas o criador pode gerenciar membros.'}, status=status.HTTP_403_FORBIDDEN)
        user_id = request.data.get('user_id')
        if str(user_id) == str(board.criado_por.pk):
            return Response({'detail': 'O criador não pode ser removido.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({'detail': 'Usuário não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        board.membros.remove(user)
        return Response(KanbanBoardSerializer(board, context={'request': request}).data)


class KanbanColumnViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = KanbanColumnSerializer

    def get_queryset(self):
        user = self.request.user
        qs = KanbanColumn.objects.filter(
            Q(quadro__criado_por=user) | Q(quadro__membros=user)
        ).distinct().prefetch_related('tasks', 'tasks__responsavel', 'tasks__dono', 'tasks__anexos')
        quadro_id = self.request.query_params.get('quadro_id')
        if quadro_id:
            qs = qs.filter(quadro_id=quadro_id)
        return qs

    def perform_create(self, serializer):
        serializer.save()


class KanbanTaskViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = KanbanTaskSerializer

    def get_queryset(self):
        user = self.request.user
        return KanbanTask.objects.filter(
            Q(coluna__quadro__criado_por=user) |
            Q(coluna__quadro__membros=user) |
            Q(responsavel=user)
        ).distinct().select_related('dono', 'responsavel', 'coluna', 'coluna__quadro')

    def perform_create(self, serializer):
        serializer.save(dono=self.request.user)

    def perform_update(self, serializer):
        # dono nunca deve mudar após a criação
        serializer.save(dono=serializer.instance.dono)

    def update(self, request, *args, **kwargs):
        kwargs['partial'] = True  # aceita PATCH parcial
        task = self.get_object()

        # Responsável (não-dono) não pode alterar a coluna da tarefa
        if task.dono != request.user:
            data = request.data.copy()
            data.pop('coluna_id', None)
            serializer = self.get_serializer(task, data=data, partial=True)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            return Response(serializer.data)

        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=['patch'], url_path='mover')
    def mover_coluna(self, request, pk=None):
        """Move a tarefa para outra coluna (drag & drop)."""
        task = self.get_object()
        coluna_id = request.data.get('coluna_id')
        try:
            coluna = KanbanColumn.objects.get(pk=coluna_id)
            board = coluna.quadro
            if request.user != board.criado_por and not board.membros.filter(pk=request.user.pk).exists():
                raise KanbanColumn.DoesNotExist
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

        task.responsavel = User.objects.get(pk=responsavel_id) if responsavel_id else None
        task.save()
        return Response(KanbanTaskSerializer(task, context={'request': request}).data)
    
    @action(detail=True, methods=['patch'], url_path='concluir')
    def concluir(self, request, pk=None):
        """Marca a tarefa como concluída e move para a coluna Concluídas do board."""
        task = self.get_object()
        board = task.coluna.quadro

        coluna_concluida = board.colunas.filter(is_concluida=True).first()
        if not coluna_concluida:
            coluna_concluida = KanbanColumn.objects.create(
                quadro=board,
                titulo='Concluídas',
                cor='#22c55e',
                ordem=9999,
                is_concluida=True,
            )

        task.coluna = coluna_concluida
        task.concluido_em = timezone.now()
        task.save()
        return Response(KanbanTaskSerializer(task, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='reabrir')
    def reabrir(self, request, pk=None):
        """Remove conclusão e move a tarefa de volta para a coluna informada (ou a primeira do board)."""
        task = self.get_object()
        board = task.coluna.quadro

        coluna_id = request.data.get('coluna_id')
        if coluna_id:
            try:
                coluna = board.colunas.filter(is_concluida=False).get(pk=coluna_id)
            except KanbanColumn.DoesNotExist:
                return Response({'detail': 'Coluna inválida.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            coluna = board.colunas.filter(is_concluida=False).order_by('ordem', 'criado_em').first()
            if not coluna:
                return Response({'detail': 'Nenhuma coluna disponível no quadro.'}, status=status.HTTP_400_BAD_REQUEST)

        task.coluna = coluna
        task.concluido_em = None
        task.save()
        return Response(KanbanTaskSerializer(task, context={'request': request}).data)

    @action(detail=False, methods=['get'], url_path='recebidas')
    def recebidas(self, request):
        """Tarefas transferidas para o usuário atual (não são de quadros onde ele é criador)."""
        tasks = KanbanTask.objects.filter(
            responsavel=request.user
        ).exclude(
            Q(coluna__quadro__criado_por=request.user)
        ).select_related(
        'dono', 'responsavel', 'coluna'
        ).prefetch_related(
        'anexos',
        )
        return Response(KanbanTaskSerializer(tasks, many=True, context={'request': request}).data)
    
class KanbanAnexoViewSet(viewsets.ModelViewSet):
    serializer_class = KanbanAnexoSerializer
    parser_classes   = [MultiPartParser, FormParser]

    def get_queryset(self):
        return KanbanAnexo.objects.filter(
            tarefa_id=self.kwargs['tarefa_pk'],
        ).filter(
            Q(tarefa__coluna__quadro__criado_por=self.request.user) |
            Q(tarefa__coluna__quadro__membros=self.request.user)
        ).distinct()

    def perform_create(self, serializer):
        tarefa = get_object_or_404(KanbanTask, pk=self.kwargs['tarefa_pk'])
        board = tarefa.coluna.quadro
        if self.request.user != board.criado_por and not board.membros.filter(pk=self.request.user.pk).exists():
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Você não é membro deste quadro.")
        f = self.request.FILES.get('arquivo')
        serializer.save(
            tarefa=tarefa,
            nome=f.name if f else '',
            tamanho=f.size if f else None
        )

@api_view(['POST'])
def reordenar_listas(request):
    quadro_id = request.data.get('quadro_id')
    ordem = request.data.get('ordem', [])  # [{ id, ordem }]
    for item in ordem:
        KanbanColumn.objects.filter(pk=item['id'], quadro_id=quadro_id).update(ordem=item['ordem'])
    return Response({'ok': True})