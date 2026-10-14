import re
from rest_framework import serializers
from .models import Reserva, Objeto

class ObjetoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Objeto
        fields = ['id', 'nome', 'tipo', 'descricao', 'placa']

class ReservaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reserva
        fields = [
            'id', 
            'objeto', 
            'data_inicio', 
            'hora_inicio', 
            'data_fim', 
            'hora_fim', 
            'tempo_total',
            'responsavel', 
            'observacoes',
            'cor'
        ]

    def validate_cor(self, value):
        if not value:
            return None
        value = value.strip().upper()
        if not re.fullmatch(r'#[0-9A-F]{6}', value):
            raise serializers.ValidationError('Cor inválida: use #RRGGBB.')
        return value  