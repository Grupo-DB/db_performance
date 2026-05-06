from rest_framework import serializers
from .models import Reserva, Objeto

class ObjetoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Objeto
        fields = ['id', 'nome', 'tipo', 'descricao', 'placa']

class ReservaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reserva
        fields = ['id', 'objeto', 'data_inicio', 'hora_inicio', 'data_fim', 'hora_fim', 'responsavel', 'observacoes']  