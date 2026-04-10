from rest_framework import serializers
from django.contrib.auth.models import User
from .models import KanbanColumn, KanbanTask, KanbanAnexo

class UserMinSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']


class KanbanTaskSerializer(serializers.ModelSerializer):
    dono = UserMinSerializer(read_only=True)
    responsavel = UserMinSerializer(read_only=True)
    responsavel_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='responsavel',
        write_only=True, required=False, allow_null=True
    )
    coluna_id = serializers.PrimaryKeyRelatedField(
        queryset=KanbanColumn.objects.all(), source='coluna', write_only=True
    )
    esta_atrasada = serializers.SerializerMethodField()

    class Meta:
        model = KanbanTask
        fields = [
            'id', 'coluna_id', 'dono', 'responsavel', 'responsavel_id',
            'titulo', 'descricao', 'prioridade', 'tags',
            'data_inicio', 'prazo', 'concluido_em',
            'esta_atrasada', 'criado_em', 'atualizado_em','recorrente', 'recorrencia',
            'anexos',
        ]
        read_only_fields = ['dono', 'criado_em', 'atualizado_em']

    def get_esta_atrasada(self, obj):
        from django.utils import timezone
        if obj.prazo and not obj.concluido_em:
            return obj.prazo < timezone.now().date()
        return False

    def validate_coluna_id(self, coluna):
        request = self.context['request']
        # garante que a coluna pertence ao usuário logado
        if coluna.usuario != request.user:
            raise serializers.ValidationError("Coluna não pertence ao usuário.")
        return coluna


class KanbanColumnSerializer(serializers.ModelSerializer):
    tasks = KanbanTaskSerializer(many=True, read_only=True)

    class Meta:
        model = KanbanColumn
        fields = ['id', 'titulo', 'cor', 'ordem', 'tasks', 'criado_em']
        read_only_fields = ['criado_em']


class KanbanAnexoSerializer(serializers.ModelSerializer):
    arquivo = serializers.FileField(use_url=True)

    class Meta:
        model  = KanbanAnexo
        fields = ['id', 'nome', 'arquivo', 'tamanho', 'criado_em']
        read_only_fields = ['id', 'nome', 'tamanho', 'criado_em']

