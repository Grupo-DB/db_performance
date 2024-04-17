from rest_framework import serializers
from django.contrib.auth.models import User,Group
from rest_framework import serializers
from .models import Empresa,Filial,Area,Cargo,Setor,TipoAvaliacao,TipoContrato,Colaborador,Avaliador

class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = '__all__'

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

class RegisterCompanySerializer(serializers.Serializer):
   
    id = serializers.IntegerField(read_only=True)
    nome = serializers.CharField()
    cnpj = serializers.CharField()
    endereco = serializers.CharField()
    cidade = serializers.CharField()
    estado = serializers.CharField()
    codigo = serializers.CharField()

    def create(self, validated_data):
        empresa = Empresa.objects.create(**validated_data)
        return empresa
    
class FilialSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
    nome = serializers.CharField()
    cnpj = serializers.CharField()
    endereco = serializers.CharField()
    cidade = serializers.CharField()
    estado = serializers.CharField()
    codigo = serializers.CharField()

    def create(self, validate_data):
        filial = Filial.objects.create(**validate_data)
        return filial
    
class AreaSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
    filial = serializers.PrimaryKeyRelatedField(queryset=Filial.objects.all())
    nome = serializers.CharField()

    def create(self, validated_data):
        area = Area.objects.create(**validated_data)
        return area
    
class SetorSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
    filial = serializers.PrimaryKeyRelatedField(queryset=Filial.objects.all())
    area = serializers.PrimaryKeyRelatedField(queryset=Area.objects.all())
    nome = serializers.CharField()

    def create(self, validate_data):
        setor = Setor.objects.create(**validate_data)
        return setor

class CargoSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
    area = serializers.PrimaryKeyRelatedField(queryset=Area.objects.all())
    filial = serializers.PrimaryKeyRelatedField(queryset=Filial.objects.all())
    setor = serializers.PrimaryKeyRelatedField(queryset=Setor.objects.all())
    nome = serializers.CharField()

    def create(self, validate_data):
        cargo = Cargo.objects.create(**validate_data)
        return cargo

class TipoContratoSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
    area = serializers.PrimaryKeyRelatedField(queryset=Area.objects.all())
    filial = serializers.PrimaryKeyRelatedField(queryset=Filial.objects.all())
    setor = serializers.PrimaryKeyRelatedField(queryset=Setor.objects.all())
    nome = serializers.CharField()

    def create(self, validate_data):
        tipocontrato = TipoContrato.objects.create(**validate_data)
        return tipocontrato
    
class ColaboradorSerializer(serializers.Serializer):
    class Meta:
        model = Colaborador
        fields = '__all__'

    def create (self, validate_data):
        colaborador = Colaborador.objects.create(**validate_data)
        return colaborador

class AvaliadorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    colaborador = serializers.IntegerField()
    usuario = serializers.IntegerField()    
    
    def create(self,validate_data):
        avaliador = Avaliador.objects.create(**validate_data)
        return avaliador
    
class TipoAvaliacaoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()

    def create(self,validate_data):
        tipoavaliacao = TipoAvaliacao.objects.crate(**validate_data)
        return tipoavaliacao
    
    