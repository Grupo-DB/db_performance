from rest_framework import serializers
from .models import CalculoEnsaio


class CalculoEnsaioSerializer(serializers.ModelSerializer):
    class Meta:
        model = CalculoEnsaio
        fields = '__all__'