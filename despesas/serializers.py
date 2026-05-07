from rest_framework import serializers
from .models import Despesa, DocumentoAnexo

class DocumentoAnexoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoAnexo
        fields = ['id', 'arquivo', 'nome_original', 'created_at', 'created_by']

class DespesaSerializer(serializers.ModelSerializer):
    anexos = DocumentoAnexoSerializer(many=True, read_only=True)
    class Meta:
        model = Despesa
        fields = [
            'id', 
            'colaborador', 
            'tipo', 
            'data', 
            'valor', 
            'anexo',
            'anexos', 
            'created_at', 
            'lancada', 
            'reembolsavel'
        ]