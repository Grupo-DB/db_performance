from rest_framework import serializers
from django.contrib.auth.models import User,Group
from rest_framework import serializers
from .models import Empresa,Filial,Area,Cargo,Setor,TipoAvaliacao,TipoContrato,Colaborador,Avaliador,Avaliacao,Formulario,Pergunta,Avaliado,Ambiente



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


    
class FormularioUpdateSerializer(serializers.ModelSerializer):
    perguntas = serializers.PrimaryKeyRelatedField(queryset=Pergunta.objects.all(), many=True)

    class Meta:
        model = Formulario
        fields = ['id', 'perguntas']

class FormularioCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Formulario
        fields = ['id', 'nome']


class FormularioSerializer(serializers.ModelSerializer):
    perguntas = serializers.PrimaryKeyRelatedField(queryset=Pergunta.objects.all(), many=True, required=False)
    
    class Meta:
        model = Formulario
        fields = ['id', 'nome', 'perguntas']

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

 

class ColaboradorSerializer(serializers.ModelSerializer):
    # user = UserSerializer(required=False)
    # tornar_avaliado = serializers.BooleanField(write_only=True, required=False)
    # tornar_avaliador = serializers.BooleanField(write_only=True, required=False)

    class Meta:
        model = Colaborador
        fields = '__all__'

    

    # def update(self, instance, validated_data):
    #     user_data = validated_data.pop('user', None)
    #     tornar_avaliado = validated_data.pop('tornar_avaliado', False)
    #     tornar_avaliador = validated_data.pop('tornar_avaliador', False)

    #     for attr, value in validated_data.items():
    #         setattr(instance, attr, value)
    #     instance.save()

    #     if user_data:
    #         if instance.user:
    #             user = instance.user
    #             user.username = user_data.get('username', user.username)
    #             user.email = user_data.get('email', user.email)
    #             if 'password' in user_data:
    #                 user.set_password(user_data['password'])
    #             user.save()
    #         else:
    #             user = User.objects.create_user(**user_data)
    #             instance.user = user
    #             instance.save()

    #     if tornar_avaliado and not Avaliado.objects.filter(colaborador_ptr=instance).exists():
    #         Avaliado.objects.create(**validated_data, colaborador_ptr=instance)
    #     elif tornar_avaliador and not Avaliador.objects.filter(colaborador_ptr=instance).exists():
    #         Avaliador.objects.create(**validated_data, colaborador_ptr=instance)

        # return instance

# class AvaliadoSerializer(serializers.ModelSerializer):
#     colaborador_id = serializers.IntegerField(write_only=True)
#     formulario_id = serializers.IntegerField(write_only=True)
#     class Meta:
#         model = Avaliado
#         fields = '__all__'  # Ou liste os campos que deseja incluir no serializer
#     def create(self, validated_data):
#         colaborador_data = validated_data.pop('colaborador_ptr', None)
#         formulario = validated_data.pop('formulario', None)
#         avaliado = Avaliado.objects.create(colaborador_ptr=colaborador_data, formulario=formulario, **validated_data)
#         return avaliado

class AvaliadoSerializer(serializers.ModelSerializer):
    colaborador_id = serializers.IntegerField(write_only=True)
    tipoAvaliacao_id = serializers.IntegerField(write_only=True)

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

# class AvaliadorSerializer(serializers.ModelSerializer):
#     colaborador_id = serializers.IntegerField(write_only=True)
#     usuario_id = serializers.IntegerField(write_only=True)
#     class Meta:
#         model = Avaliador
#         fields = '__all__'  # Ou liste os campos que deseja incluir no serializer
#     def create(self, validated_data):
#         colaborador_data = validated_data.pop('colaborador_ptr', None)
#         usuario = validated_data.pop('usuario', None)
#         avaliador = Avaliador.objects.create(colaborador_ptr=colaborador_data, usuario=usuario, **validated_data)
#         return avaliador
        
class AvaliadorSerializer(serializers.ModelSerializer):
    colaborador_id = serializers.IntegerField(write_only=True)

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

class PerguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pergunta
        fields = '__all__'                                                    