from rest_framework import serializers
from django.contrib.auth.models import User,Group
from rest_framework import serializers
from .models import Empresa,Filial,Area,Cargo,Setor,TipoAvaliacao,TipoContrato,Colaborador,Avaliador,Upload,Avaliacao,Formulario,Pergunta,Respondido




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
    cargo = serializers.PrimaryKeyRelatedField(queryset=Cargo.objects.all())
    nome = serializers.CharField()

    def create(self, validate_data):
        tipocontrato = TipoContrato.objects.create(**validate_data)
        return tipocontrato
    
class ColaboradorSerializer(serializers.ModelSerializer):
    cargo_nome = serializers.CharField(source='cargo.nome', read_only=True)
    area_nome = serializers.CharField(source='area.nome', read_only=True)
    setor_nome = serializers.CharField(source='setor.nome', read_only=True)
    class Meta:
         model = Colaborador
         fields = '__all__'
    # id = serializers.IntegerField(read_only=True)
    # empresa = serializers.PrimaryKeyRelatedField(required=False,queryset=Empresa.objects.all())
    # area = serializers.PrimaryKeyRelatedField(required=False,queryset=Area.objects.all())
    # filial = serializers.PrimaryKeyRelatedField(required=False,queryset=Filial.objects.all())
    # setor = serializers.PrimaryKeyRelatedField(required=False,queryset=Setor.objects.all())
    # cargo = serializers.PrimaryKeyRelatedField(required=False,queryset=Cargo.objects.all())
    # tipocontrato = serializers.PrimaryKeyRelatedField(required=False,queryset=TipoContrato.objects.all())
    # nome = serializers.CharField()
    # data_admissao = serializers.DateTimeField(required=False,allow_null=True)
    # #situacao = serializers.BooleanField(required=False,allow_null=True)
    # genero = serializers.CharField(required=False,allow_blank=True)
    # estado_civil = serializers.CharField(required=False,allow_null=True)
    # data_nascimento = serializers.DateTimeField(required=False,allow_null=True)
    # data_troca_setor = serializers.DateTimeField(required=False,allow_null=True)
    # data_troca_cargo = serializers.DateTimeField(required=False,allow_null=True)
    # data_demissao = serializers.DateTimeField(required=False,allow_null=True)
    # image = serializers.FileField(required=False,allow_null=True)

    
      

    def create (self, validate_data):
        colaborador = Colaborador.objects.create(**validate_data)
        return colaborador

class AvaliadorSerializer(serializers.ModelSerializer):
    colaborador = serializers.PrimaryKeyRelatedField(read_only=True)
    class Meta:
        model = Avaliador
        fields = '__all__'
    
    def create(self,validate_data):
        avaliador = Avaliador.objects.create(**validate_data)
        return avaliador
    
class TipoAvaliacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAvaliacao
        fields = '__all__' 

    def create(self,validate_data):
        tipoavaliacao = TipoAvaliacao.objects.create(**validate_data)
        return tipoavaliacao
    
    
class UploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Upload
        fields = '__all__' 

    def create(self,validate_data):
        upload = Upload.objects.create(**validate_data)
        return upload
           
    
class AvaliacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Avaliacao
        fields = '__all__'

    def create(self, validate_data):
        avaliacao = Avaliacao.objects.create(**validate_data)
        return avaliacao        
    
class PerguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pergunta
        fields = '__all__'
    def create(self, validate_data):
        pergunta = Pergunta.objects.create(**validate_data)
        return pergunta      
class FormularioSerializer(serializers.ModelSerializer):
    perguntas = PerguntaSerializer(many=True)    
    class Meta:
        model = Formulario
        fields = '__all__'

    def create(self, validate_data):
        perguntas_data = validate_data.pop('perguntas', [])  # Extrai os dados das perguntas do formulário
        formulario = Formulario.objects.create(**validate_data)

        # Adiciona as perguntas ao formulário recém-criado
        for pergunta_data in perguntas_data:
            pergunta = Pergunta.objects.create(**pergunta_data)
            formulario.perguntas.add(pergunta)

        return formulario
class RespondidoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Respondido
        fields = '__all__'    

    def create(self,validate_data):
        respondido = Respondido.objects.create(**validate_data)
        return respondido    