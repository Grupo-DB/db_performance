from rest_framework import serializers
from django.contrib.auth.models import User

from .models import Fila, Conversa, Mensagem, MensagemAnexo, WhatsAppNotificacao


class UserMinSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']


class FilaSerializer(serializers.ModelSerializer):
    membros = UserMinSerializer(many=True, read_only=True)
    membros_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='membros', write_only=True,
        many=True, required=False,
    )

    class Meta:
        model = Fila
        fields = [
            'id', 'nome', 'descricao', 'ativa', 'ordem', 'palavras_chave',
            'is_padrao', 'membros', 'membros_ids', 'criado_por', 'criado_em',
        ]
        read_only_fields = ['criado_por', 'criado_em']


class MensagemAnexoSerializer(serializers.ModelSerializer):
    class Meta:
        model = MensagemAnexo
        fields = ['id', 'arquivo', 'nome_original', 'tamanho', 'mime_type', 'criado_em']
        read_only_fields = ['nome_original', 'tamanho', 'mime_type', 'criado_em']


class MensagemSerializer(serializers.ModelSerializer):
    autor = UserMinSerializer(read_only=True)
    anexos = MensagemAnexoSerializer(many=True, read_only=True)
    anexo = serializers.FileField(write_only=True, required=False)

    class Meta:
        model = Mensagem
        fields = [
            'id', 'conversa', 'direcao', 'tipo', 'texto', 'autor', 'anexos', 'anexo',
            'wa_message_id', 'status_entrega', 'erro_detalhe', 'created_at',
        ]
        read_only_fields = [
            'conversa', 'direcao', 'tipo', 'wa_message_id', 'status_entrega', 'erro_detalhe', 'created_at', 'autor',
        ]


class ConversaListSerializer(serializers.ModelSerializer):
    fila = FilaSerializer(read_only=True)
    responsavel = UserMinSerializer(read_only=True)
    ultima_mensagem_texto = serializers.SerializerMethodField()

    class Meta:
        model = Conversa
        fields = [
            'id', 'contato_telefone', 'contato_nome', 'fila', 'responsavel',
            'status', 'estado_menu', 'ultima_mensagem_em', 'ultima_mensagem_texto', 'created_at',
        ]

    def get_ultima_mensagem_texto(self, obj):
        ultima = obj.mensagens.order_by('-created_at').first()
        return ultima.texto if ultima else ''


class ConversaDetailSerializer(serializers.ModelSerializer):
    fila = FilaSerializer(read_only=True)
    responsavel = UserMinSerializer(read_only=True)
    mensagens = MensagemSerializer(many=True, read_only=True)
    dentro_da_janela_24h = serializers.BooleanField(read_only=True)

    class Meta:
        model = Conversa
        fields = [
            'id', 'contato_telefone', 'contato_nome', 'fila', 'responsavel',
            'status', 'estado_menu', 'ultima_mensagem_em', 'ultima_mensagem_cliente_em',
            'dentro_da_janela_24h', 'mensagens', 'created_at',
        ]


class WhatsAppNotificacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = WhatsAppNotificacao
        fields = ['id', 'conversa', 'tipo', 'mensagem', 'lido', 'created_at']
