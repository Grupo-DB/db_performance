from rest_framework import serializers
from django.contrib.auth.models import User,Group
from rest_framework import serializers
from .models import Empresa,Filial,Area,Cargo,Setor,TipoAvaliacao,TipoContrato,Colaborador,Avaliador,Avaliacao,Formulario,Pergunta,Avaliado,Ambiente,HistoricoAlteracao
from notifications.models import Notification
#from .serializers import EmpresaSerializer,FilialSerializer,AmbienteSerializer,AreaSerializer,CargoSerializer,SetorSerializer

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
    primeiro_acesso = serializers.BooleanField()

    
class FormularioUpdateSerializer(serializers.ModelSerializer):
    perguntas = serializers.PrimaryKeyRelatedField(queryset=Pergunta.objects.all(), many=True)

    class Meta:
        model = Formulario
        fields = ['id', 'perguntas']

class FormularioCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Formulario
        fields = ['id', 'nome']


    def create(self, validated_data):
        perguntas_data = validated_data.pop('perguntas', [])
        formulario = Formulario.objects.create(**validated_data)
        formulario.perguntas.set(perguntas_data)
        return formulario

    def update(self, instance, validated_data):
        perguntas_data = validated_data.pop('perguntas', [])
        instance.nome = validated_data.get('nome', instance.nome)
        instance.save()
        instance.perguntas.set(perguntas_data)
        return instance


class AvaliadoSerializer(serializers.ModelSerializer):
    colaborador_id = serializers.IntegerField(write_only=True)
    tipoAvaliacao_id = serializers.IntegerField(write_only=True)
    setor = serializers.CharField(source='setor.nome', read_only=True)
    ambiente = serializers.CharField(source='ambiente.nome', read_only=True)
    cargo = serializers.CharField(source='cargo.nome', read_only=True)

    class Meta:
        model = Avaliado
        fields = '__all__'  # Ou liste os campos que deseja incluir no serializer

    def create(self, validated_data):
        colaborador_data = validated_data.pop('colaborador_id', None)
        # formulario_id = validated_data.pop('formulario_id', None)
        if colaborador_data:
            colaborador = Colaborador.objects.get(id=colaborador_data)
            validated_data['colaborador_ptr'] = colaborador
       
        avaliado = Avaliado.objects.create(**validated_data)
        return avaliado


class AvaliadorSerializer(serializers.ModelSerializer):
    colaborador_id = serializers.IntegerField(write_only=True)
    avaliados = AvaliadoSerializer(many=True, read_only=True)
    setor = serializers.CharField(source='ambiente.nome', read_only=True)
    ambiente = serializers.CharField(source='setor.nome', read_only=True)
    cargo = serializers.CharField(source='cargo.nome', read_only=True)
    class Meta:
        model = Avaliador
        fields = '__all__'  # Ou liste os campos que deseja incluir no serializer

    def create(self, validated_data):
        colaborador_data = validated_data.pop('colaborador_id', None)
        if colaborador_data:
            colaborador = Colaborador.objects.get(id=colaborador_data)
            validated_data['colaborador_ptr'] = colaborador
        avaliador = Avaliador.objects.create(**validated_data)
        return avaliador

class EmpresaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empresa
        fields = '__all__'

class FilialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Filial
        fields = '__all__'        

class AreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = '__all__'           

class SetorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Setor
        fields = '__all__'           

class AmbienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ambiente
        fields = '__all__'

class CargoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cargo
        fields = '__all__'

class TipoContratoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoContrato
        fields = '__all__'

class TipoAvaliacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAvaliacao
        fields = '__all__'   

class AvaliacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Avaliacao
        fields = '__all__'
    def validate_feedback(self, value):
        if value is None:
            return False
        return value    

class PerguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pergunta
        fields = '__all__'   

class FormularioSerializer(serializers.ModelSerializer):
    # perguntas = serializers.PrimaryKeyRelatedField(queryset=Pergunta.objects.all(), many=True, required=False)
    perguntas = PerguntaSerializer(many=True, read_only=True)
    avaliados = AvaliadoSerializer(many=True, read_only=True)
    class Meta:
        model = Formulario
        fields = ['id', 'nome', 'tipoavaliacao', 'perguntas','avaliados']                                                         

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'         

class HistoricoAlteracaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = HistoricoAlteracao
        fields = '__all__'

class ColaboradorSerializer(serializers.ModelSerializer):
    # Para escrita, aceita apenas IDs
    empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all(), write_only=True)
    filial = serializers.PrimaryKeyRelatedField(queryset=Filial.objects.all(), write_only=True)
    area = serializers.PrimaryKeyRelatedField(queryset=Area.objects.all(), write_only=True)
    setor = serializers.PrimaryKeyRelatedField(queryset=Setor.objects.all(), write_only=True)
    ambiente = serializers.PrimaryKeyRelatedField(queryset=Ambiente.objects.all(), write_only=True)
    cargo = serializers.PrimaryKeyRelatedField(queryset=Cargo.objects.all(), write_only=True)
    # Para leitura, retorna os dados completos
    empresa_detalhes = EmpresaSerializer(source='empresa', read_only=True)
    filial_detalhes = FilialSerializer(source='filial', read_only=True)
    area_detalhes = AreaSerializer(source='area', read_only=True)
    setor_detalhes = SetorSerializer(source='setor', read_only=True)
    ambiente_detalhes = AmbienteSerializer(source='ambiente', read_only=True)
    cargo_detalhes = CargoSerializer(source='cargo', read_only=True)


    class Meta:
        model = Colaborador
        fields = '__all__'