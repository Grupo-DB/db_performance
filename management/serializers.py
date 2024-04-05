from rest_framework import serializers
from django.contrib.auth.models import User
from rest_framework import serializers

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)  # Define a senha como campo write_only
    class Meta:
        model = User
        fields = '__all__'

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        # Cria o usuário usando o método create_user do modelo User
        user = User.objects.create_user(**validated_data, password=password)
        return user
class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()