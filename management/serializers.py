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

# class RegisterCompanySerializer(serializers.Serializer):
   
#     id = serializers.IntegerField(read_only=True)
#     nome = serializers.CharField()
#     cnpj = serializers.CharField()
#     endereco = serializers.CharField()
#     cidade = serializers.CharField()
#     estado = serializers.CharField()
#     codigo = serializers.CharField()

#     def create(self, validated_data):
#         empresa = Empresa.objects.create(**validated_data)
#         return empresa
    
# class FilialSerializer(serializers.Serializer):
#     id = serializers.IntegerField(read_only=True)
#     empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
#     nome = serializers.CharField()
#     cnpj = serializers.CharField()
#     endereco = serializers.CharField()
#     cidade = serializers.CharField()
#     estado = serializers.CharField()
#     codigo = serializers.CharField()

#     def create(self, validate_data):
#         filial = Filial.objects.create(**validate_data)
#         return filial
    
# class AreaSerializer(serializers.Serializer):
#     id = serializers.IntegerField(read_only=True)
#     empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
#     filial = serializers.PrimaryKeyRelatedField(queryset=Filial.objects.all())
#     nome = serializers.CharField()

#     def create(self, validated_data):
#         area = Area.objects.create(**validated_data)
#         return area
    
# class SetorSerializer(serializers.Serializer):
#     id = serializers.IntegerField(read_only=True)
#     empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
#     filial = serializers.PrimaryKeyRelatedField(queryset=Filial.objects.all())
#     area = serializers.PrimaryKeyRelatedField(queryset=Area.objects.all())
#     nome = serializers.CharField()

#     def create(self, validate_data):
#         setor = Setor.objects.create(**validate_data)
#         return setor

# class CargoSerializer(serializers.Serializer):
#     id = serializers.IntegerField(read_only=True)
#     empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
#     area = serializers.PrimaryKeyRelatedField(queryset=Area.objects.all())
#     filial = serializers.PrimaryKeyRelatedField(queryset=Filial.objects.all())
#     setor = serializers.PrimaryKeyRelatedField(queryset=Setor.objects.all())
#     nome = serializers.CharField()

#     def create(self, validate_data):
#         cargo = Cargo.objects.create(**validate_data)
#         return cargo

# class TipoContratoSerializer(serializers.Serializer):
#     id = serializers.IntegerField(read_only=True)
#     empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
#     area = serializers.PrimaryKeyRelatedField(queryset=Area.objects.all())
#     filial = serializers.PrimaryKeyRelatedField(queryset=Filial.objects.all())
#     setor = serializers.PrimaryKeyRelatedField(queryset=Setor.objects.all())
#     cargo = serializers.PrimaryKeyRelatedField(queryset=Cargo.objects.all())
#     nome = serializers.CharField()

#     def create(self, validate_data):
#         tipocontrato = TipoContrato.objects.create(**validate_data)
#         return tipocontrato
    
# class ColaboradorSerializer(serializers.ModelSerializer):
#     cargo_nome = serializers.CharField(source='cargo.nome', read_only=True)
#     area_nome = serializers.CharField(source='area.nome', read_only=True)
#     setor_nome = serializers.CharField(source='setor.nome', read_only=True)
#     class Meta:
#          model = Colaborador
#          fields = '__all__'
#     # id = serializers.IntegerField(read_only=True)
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

    
      

    # def create (self, validate_data):
    #     colaborador = Colaborador.objects.create(**validate_data)
    #     return colaborador

# class AvaliadorSerializer(serializers.ModelSerializer):
#     #colaborador = serializers.PrimaryKeyRelatedField(read_only=True)
#     class Meta:
#         model = Avaliador
#         fields = '__all__'
    
#     def create(self,validate_data):
#         avaliador = Avaliador.objects.create(**validate_data)
#         return avaliador
    
# class TipoAvaliacaoSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = TipoAvaliacao
#         fields = '__all__' 

#     def create(self,validate_data):
#         tipoavaliacao = TipoAvaliacao.objects.create(**validate_data)
#         return tipoavaliacao
    
    
# class UploadSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Upload
#         fields = '__all__' 

    # def create(self,validate_data):
    #     upload = Upload.objects.create(**validate_data)
    #     return upload
           
    
# class AvaliacaoSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Avaliacao
#         fields = '__all__'

#     def create(self, validate_data):
#         avaliacao = Avaliacao.objects.create(**validate_data)
#         return avaliacao        
    
# class PerguntaSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Pergunta
#         fields = '__all__'
#     def create(self, validate_data):
#         pergunta = Pergunta.objects.create(**validate_data)
#         return pergunta      


# class FormularioSerializer(serializers.ModelSerializer):  
#     class Meta:
#         model = Formulario
#         fields = '__all__'

#     def create(self, validate_data):
#         perguntas_data = validate_data.pop('perguntas', [])  # Extrai os dados das perguntas do formulário
#         formulario = Formulario.objects.create(**validate_data)

#         # Adiciona as perguntas ao formulário recém-criado
#         for pergunta_data in perguntas_data:
#             pergunta = Pergunta.objects.create(**pergunta_data)
#             formulario.perguntas.add(pergunta)

#         return formulario
    
class FormularioUpdateSerializer(serializers.ModelSerializer):
    perguntas = serializers.PrimaryKeyRelatedField(queryset=Pergunta.objects.all(), many=True)

    class Meta:
        model = Formulario
        fields = ['id', 'perguntas']

class FormularioCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Formulario
        fields = ['id', 'nome']
# class FormularioSerializer(serializers.ModelSerializer):
#     perguntas = serializers.PrimaryKeyRelatedField(many=True, queryset=Pergunta.objects.all())

#     class Meta:
#         model = Formulario
#         fields = ['id', 'nome', 'perguntas']

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

# class FormularioNomeSerializer(serializers.Serializer):
#     nome = serializers.CharField()
#     # class Meta:
#     #     model = Formulario
#     #     fields = '__all__'    

#     def create(self,validate_data):
#         formulario = formulario.objects.create(**validate_data)
#         return formulario    
    
# class AvaliadoSerializer(serializers.ModelSerializer):
#     avaliadores = AvaliadorSerializer(many=True, read_only=True)

#     class Meta:
#         model = Avaliado
#         fields = ['id', 'colaborador', 'formulario', 'avaliadores']

#     def create(self, validated_data):
#         avaliadores_data = validated_data.pop('avaliadores', [])  # Extrai os dados dos avaliadores do avaliado
#         avaliado = Avaliado.objects.create(**validated_data)

#         # Adiciona os avaliadores ao avaliado recém-criado
#         for avaliador_data in avaliadores_data:
#             avaliador = Avaliador.objects.create(**avaliador_data)
#             avaliado.avaliadores.add(avaliador)

#         return avaliado
    

class ColaboradorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Colaborador
        fields = '__all__' 

    # def update(self, instance, validated_data):
    #     if 'image' in validated_data:
    #         instance.image.delete(save=False)  # Remove a imagem antiga se necessário
    #         instance.image = validated_data['image']
    #     return super().update(instance, validated_data)     

class AvaliadoSerializer(serializers.ModelSerializer):
    colaborador_id = serializers.IntegerField(write_only=True)
    formulario_id = serializers.IntegerField(write_only=True)
    class Meta:
        model = Avaliado
        fields = '__all__'  # Ou liste os campos que deseja incluir no serializer
    def create(self, validated_data):
        colaborador_data = validated_data.pop('colaborador_ptr', None)
        formulario = validated_data.pop('formulario', None)
        avaliado = Avaliado.objects.create(colaborador_ptr=colaborador_data, formulario=formulario, **validated_data)
        return avaliado

class AvaliadorSerializer(serializers.ModelSerializer):
    colaborador_id = serializers.IntegerField(write_only=True)
    usuario_id = serializers.IntegerField(write_only=True)
    class Meta:
        model = Avaliador
        fields = '__all__'  # Ou liste os campos que deseja incluir no serializer
    def create(self, validated_data):
        colaborador_data = validated_data.pop('colaborador_ptr', None)
        usuario = validated_data.pop('usuario', None)
        avaliador = Avaliador.objects.create(colaborador_ptr=colaborador_data, usuario=usuario, **validated_data)
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