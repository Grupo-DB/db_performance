from rest_framework import serializers
from django.contrib.auth.models import User
from .models import KanbanBoard, KanbanColumn, KanbanTask, KanbanAnexo

class UserMinSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']


class KanbanBoardSerializer(serializers.ModelSerializer):
    criado_por = UserMinSerializer(read_only=True)
    membros = UserMinSerializer(many=True, read_only=True)

    class Meta:
        model = KanbanBoard
        fields = ['id', 'nome', 'criado_por', 'membros', 'criado_em']
        read_only_fields = ['criado_por', 'criado_em']


class KanbanAnexoSerializer(serializers.ModelSerializer):
    arquivo = serializers.FileField(use_url=True)

    class Meta:
        model  = KanbanAnexo
        fields = ['id', 'nome', 'arquivo', 'tamanho', 'criado_em']
        read_only_fields = ['id', 'nome', 'tamanho', 'criado_em']

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
    anexos = KanbanAnexoSerializer(many=True, read_only=True)
    origem_whatsapp = serializers.SerializerMethodField()

    class Meta:
        model = KanbanTask
        fields = [
            'id', 'coluna_id', 'dono', 'responsavel', 'responsavel_id',
            'titulo', 'descricao', 'prioridade', 'tags', 'ordem',
            'data_inicio', 'prazo', 'concluido_em','anexos',
            'esta_atrasada', 'criado_em', 'atualizado_em','recorrente', 'recorrencia',
            'conversa_whatsapp', 'origem_whatsapp', 'notificar_whatsapp',
        ]
        read_only_fields = ['dono', 'ordem', 'criado_em', 'atualizado_em']

    def get_origem_whatsapp(self, obj):
        """Contato de origem, para o cartão mostrar de onde a tarefa veio."""
        conversa = obj.conversa_whatsapp
        if not conversa:
            return None
        return {
            'conversa_id': conversa.id,
            'contato_nome': conversa.contato_nome,
            'contato_telefone': conversa.contato_telefone,
        }

    def get_esta_atrasada(self, obj):
        from django.utils import timezone
        if obj.prazo and not obj.concluido_em:
            return obj.prazo < timezone.now().date()
        return False

    def validate_notificar_whatsapp(self, ligado):
        """
        Sem conversa de origem não há para quem avisar — ligar a chave criaria uma
        tarefa que promete uma mensagem que nunca sai.

        `conversa_whatsapp` não é editável pela tela, então o valor válido é
        sempre o que já está gravado (nulo em tarefa criada direto no quadro).
        """
        if ligado and not (self.instance and self.instance.conversa_whatsapp_id):
            raise serializers.ValidationError(
                'Só é possível avisar pelo WhatsApp em tarefa criada a partir de uma conversa.'
            )
        return ligado

    def validate_coluna_id(self, coluna):
        request = self.context['request']
        board = coluna.quadro
        # garante que o usuário é membro ou criador do board da coluna
        if request.user != board.criado_por and not board.membros.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("Você não é membro deste quadro.")
        return coluna


class KanbanColumnSerializer(serializers.ModelSerializer):
    tasks = KanbanTaskSerializer(many=True, read_only=True)
    quadro_id = serializers.PrimaryKeyRelatedField(
        queryset=KanbanBoard.objects.all(), source='quadro', write_only=True
    )

    class Meta:
        model = KanbanColumn
        fields = ['id', 'quadro_id', 'titulo', 'cor', 'ordem', 'is_concluida', 'tasks', 'criado_em']
        read_only_fields = ['criado_em', 'is_concluida']

    def validate_quadro_id(self, board):
        request = self.context['request']
        if request.user != board.criado_por and not board.membros.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("Você não é membro deste quadro.")
        return board



