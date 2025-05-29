from rest_framework import serializers
from .models import Ordem

class OrdemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ordem
        fields = '__all__'
    