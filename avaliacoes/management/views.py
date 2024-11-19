from django.shortcuts import render,HttpResponse

from baseOrcamentaria.orcamento.models import Gestor
from baseOrcamentaria.orcamento.serializers import GestorSerializer

# Create your views here.
def management(request):
    return HttpResponse(request,'ok')
#import logging
from django.utils import timezone
from django.shortcuts import render, HttpResponse,get_object_or_404
from django.contrib.auth.models import User,Group
from django.contrib.auth import authenticate
from django.contrib.auth import login as login_django
from django.contrib.auth.decorators import login_required 
from rolepermissions.roles import assign_role
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from rest_framework.parsers import MultiPartParser,FormParser,FileUploadParser,JSONParser
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated,AllowAny,IsAdminUser,DjangoModelPermissions
from rest_framework.decorators import api_view,authentication_classes, permission_classes,parser_classes,action
from django.views.decorators.csrf import csrf_exempt
from rest_framework.response import Response
from rest_framework import status, viewsets
from .models import Ambiente, Empresa,Area,Cargo,Setor,Colaborador,Filial,TipoContrato,TipoAvaliacao,Avaliacao,Avaliador,Formulario,Pergunta,Avaliado,HistoricoAlteracao
from django.conf import settings
from .serializers import LoginSerializer, UserSerializer,EmpresaSerializer,GroupSerializer,AreaSerializer,SetorSerializer,CargoSerializer,ColaboradorSerializer,FilialSerializer,TipoContratoSerializer,TipoAvaliacaoSerializer,AvaliacaoSerializer,AvaliadorSerializer,PerguntaSerializer,AvaliadoSerializer,AmbienteSerializer,HistoricoAlteracaoSerializer
from.serializers import FormularioCreateSerializer,FormularioUpdateSerializer,FormularioSerializer,NotificationSerializer
from .utils import send_custom_email
from django.core.mail import send_mail
from datetime import datetime
from django.db.models import Q
from notifications.signals import notify
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from .permissions import IsInGroup
from db_performance.tasks import enviar_notificacoes

#logger = logging.getLogger(__name__)
# @api_view(['GET','POST'])
# def login(request):
#     if request.method == "GET":
#         return render(request,'login.html')
#     else:    
#         serializer = LoginSerializer(data=request.data)
#         if serializer.is_valid():
#             username = serializer.validated_data['username']
#             password = serializer.validated_data['password']
#             user = authenticate(username=username, password=password)
#             if user is not None:
#                 login(request, user)
                
#                 return Response({'message': 'Login bem-sucedido'}, status=status.HTTP_200_OK)
#             else:
#                 # Credenciais inválidas
#                 return Response({'message': 'Credenciais inválidas'}, status=status.HTTP_401_UNAUTHORIZED)
#         else:
#             # Dados inválidos
#             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# @api_view(['POST'])
# def login(request):
#         serializer = LoginSerializer(data=request.data)
#         if serializer.is_valid():
#             username = serializer.validated_data['username']
#             password = serializer.validated_data['password']
#             user = authenticate(username=username, password=password)
#             if user is not None:
#                 refresh = RefreshToken.for_user(user)
#                 return Response({
#                     'refresh': str(refresh),
#                     'access': str(refresh.access_token),
#                     'primeiro_acesso': user.primeiro_acesso,
#                 })
#             return Response({'detail': 'Invalid credentials'}, status=status.HTTP_400_BAD_REQUEST)
#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



User = get_user_model()

@api_view(['POST'])
@permission_classes([AllowAny])
def update_password_first_login(request):
    user = request.user
    new_password = request.data.get('new_password')

    if user.primeiro_acesso:
        user.set_password(new_password)
        user.primeiro_acesso = False
        user.save()
        return Response({"message": "Password updated successfully"}, status=status.HTTP_200_OK)
    return Response({"error": "Password reset not required"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    email = request.data.get('email')
    try:
        colaborador = Colaborador.objects.get(email=email)
        user = colaborador.user
    except Colaborador.DoesNotExist:
        return Response({'error': 'Usuário não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    reset_link = f"{settings.FRONTEND_URL}/redefinirsenha/{uid}/{token}/"

    send_mail(
        'Redefinição de Senha',
        f'Use o link abaixo para redefinir sua senha:\n{reset_link}',
        settings.DEFAULT_FROM_EMAIL,
        [email],
    )

    return Response({'message': 'Email enviado com sucesso.'}, status=status.HTTP_200_OK)



@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        new_password = request.data.get('new_password')
        user.set_password(new_password)
        user.save()
        return Response({'message': 'Senha redefinida com sucesso.'}, status=status.HTTP_200_OK)
    else:
        return Response({'error': 'Link inválido ou expirado.'}, status=status.HTTP_400_BAD_REQUEST)




# def cadastro(request):
#     if request.method == 'GET':
#         return render(request, 'cadastro_user.html')
#     else:
#         username = request.POST.get('username')
#         email = request.POST.get('email')
#         senha = request.POST.get('senha')
        
#         #verifica se já tem esse username cadastrado
#         user = User.objects.filter(username=username).first()

#         if user:
#             return HttpResponse('Username já cadastrado!')
        
#         user = User.objects.create_user(username=username, email=email, password=senha)
#         user.save()
        
#         return HttpResponse('Usuário cadastrado com sucesso!')

# def login(request):
#     #inca que se o metodo for GET, sem preenceher e enviar o formulário. somente renderiza a pagina
#     if request.method == "GET":
#         return render(request,'login.html')
#     else:
#         username = request.POST.get('username')
#         senha = request.POST.get('senha')

#         user = authenticate(username=username, password=senha)

#         if user: #significa não none
#             login_django(request, user)
#             return HttpResponse('autenticado')
#         else:
#             return HttpResponse('email ou senha inválidos')

# @login_required(login_url='/auth/login/')        
# def plataforma(request):
#     return HttpResponse('You are in')



@api_view(['GET'])
#@permission_classes([IsAuthenticated])
def get_users(request):

    if request.method == 'GET':

        users = User.objects.all()                         

        serializer = UserSerializer(users, many=True)       

        return Response(serializer.data)                    
    
    return Response(status=status.HTTP_400_BAD_REQUEST)


## Cadsatra User
@api_view(['POST'])
#@permission_classes([IsAuthenticated])
def create_user(request):
    if request.method == 'POST':
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({'message': 'Usuário cadastrado com sucesso!', 'user_id': user.id})
        return Response(status=status.HTTP_400_BAD_REQUEST)



# #Empresas    
# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def registercompany(request):
#     if request.method == 'POST':
#         serializer = RegisterCompanySerializer(data=request.data)
#         if serializer.is_valid():
#             empresa = serializer.save()
#             return Response({'message': 'Empresa cadastrada com sucesso!', 'empresa_id': empresa.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)
    

# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def get_company(request):
#     if request.method == 'GET':

#         companys = Empresa.objects.all()                         

#         serializer = RegisterCompanySerializer(companys, many=True)       

#         return Response(serializer.data)                    
    
#     return Response(status=status.HTTP_400_BAD_REQUEST)


#--------------------------------------------------------------------Areas
# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def get_area(request):
#     if request.method == 'GET':

#         areas = Area.objects.all()                         

#         serializer = AreaSerializer(areas, many=True)       

#         return Response(serializer.data)                    
    
#     return Response(status=status.HTTP_400_BAD_REQUEST)


# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def registerarea(request):
#     if request.method == 'POST':
#         serializer = AreaSerializer(data=request.data)
#         if serializer.is_valid():
#             area = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'area_id': area.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)
    
#---------------------------------------------------------------------------------------Setores
# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def get_setor(request):
#     if request.method == 'GET':
#         setores = Setor.objects.all()                         
#         serializer = SetorSerializer(setores, many=True)       
#         return Response(serializer.data)                    
#     return Response(status=status.HTTP_400_BAD_REQUEST)

# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def registersetor(request):
#     if request.method == 'POST':
#         serializer = SetorSerializer(data=request.data)
#         if serializer.is_valid():
#             setor = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'setor_id': setor.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)



#####################################################################################------------Filiais-------------------------################################################
# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def get_filial(request):
#     if request.method == 'GET':
#         filiais = Filial.objects.all()                         
#         serializer = FilialSerializer(filiais, many=True)       
#         return Response(serializer.data)                    
#     return Response(status=status.HTTP_400_BAD_REQUEST)

# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def registerfilial(request):
#     if request.method == 'POST':
#         serializer = FilialSerializer(data=request.data)
#         if serializer.is_valid():
#             filial = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'filial_id': filial.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)

##################################################################################------------------Cargos--------------------------------------#############################

# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def get_cargo(request):
#     if request.method == 'GET':
#         cargos = Cargo.objects.all()                         
#         serializer = CargoSerializer(cargos, many=True)       
#         return Response(serializer.data)                    
#     return Response(status=status.HTTP_400_BAD_REQUEST)

# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def registercargo(request):
#     if request.method == 'POST':
#         serializer = CargoSerializer(data=request.data)
#         if serializer.is_valid():
#             cargo = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'cargo_id': cargo.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)


###############################-------------------------------------------Tipos-de-contratos-------------------##############

# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def get_tipocontrato(request):
#     if request.method == 'GET':
#         tipocontratos = TipoContrato.objects.all()                         
#         serializer = TipoContratoSerializer(tipocontratos, many=True)       
#         return Response(serializer.data)                    
#     return Response(status=status.HTTP_400_BAD_REQUEST)

# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def registertipocontrato(request):
#     if request.method == 'POST':
#         serializer = TipoContratoSerializer(data=request.data)
#         if serializer.is_valid():
#             tipocontrato = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'tipocontrato_id': tipocontrato.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)


#########################################----------------------------Colaboradores---------------------------#####################
# @api_view(['GET'])
# #@permission_classes([IsAuthenticated])
# def get_colaborador(request):
#     if request.method == 'GET':
#         colaboradores = Colaborador.objects.all()                         
#         serializer = ColaboradorSerializer(colaboradores, many=True)       
#         return Response(serializer.data)                    
#     return Response(status=status.HTTP_400_BAD_REQUEST)
# #@permission_classes([IsAuthenticated])
# @api_view(['POST'])
# @parser_classes([MultiPartParser, FormParser])
# def registercolaborador(request):
#     if request.method == 'POST':
#         serializer = ColaboradorSerializer(data=request.data)
#         if serializer.is_valid():
#             colaborador = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'colaborador_id': colaborador.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)
    
################################-------------------------Tipos de Avaliacao----------------------------------############
# @permission_classes([IsAuthenticated])
# @api_view(['GET'])
# def get_tipoavaliacao(request):
#     if request.method == 'GET':
#         tipoavaliacoes = TipoAvaliacao.objects.all()                         
#         serializer = TipoAvaliacaoSerializer(tipoavaliacoes, many=True)       
#         return Response(serializer.data)                    
#     return Response(status=status.HTTP_400_BAD_REQUEST)
# #@permission_classes([IsAuthenticated])
# @api_view(['POST'])
# def registertipoavaliacao(request):
#     if request.method == 'POST':
#         serializer = TipoAvaliacaoSerializer(data=request.data)
#         if serializer.is_valid():
#             tipoavaliacao = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'colaborador_id': tipoavaliacao.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)


############################################------------------AVALIAÇÔES--------------------##########################################
# @permission_classes([IsAuthenticated])
# @api_view(['GET'])
# def get_avaliacao(request):
#     if request.method == 'GET':
#         avaliacoes = Avaliacao.objects.all()                         
#         serializer = AvaliacaoSerializer(avaliacoes, many=True)       
#         return Response(serializer.data)                    
#     return Response(status=status.HTTP_400_BAD_REQUEST)

# @permission_classes([IsAuthenticated])
# @api_view(['POST'])
# #@parser_classes([MultiPartParser, FormParser])
# def registeravaliacao(request):
#     if request.method == 'POST':
#         serializer = AvaliacaoSerializer(data=request.data)
#         if serializer.is_valid():
#             avaliacao = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'colaborador_id': avaliacao.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)


#####################------------------------------------------------Avaliadores-----------------------------------------########
# @permission_classes([IsAuthenticated])
# @api_view(['GET'])
# def get_avaliador(request):
#     if request.method == 'GET':
#         avaliadores = Avaliador.objects.all()                         
#         serializer = AvaliadorSerializer(avaliadores, many=True)       
#         return Response(serializer.data)                    
#     return Response(status=status.HTTP_400_BAD_REQUEST)

# @permission_classes([IsAuthenticated])
# @api_view(['POST'])
# #@parser_classes([MultiPartParser, FormParser])
# def registeravaliador(request):
#     if request.method == 'POST':
#         serializer = AvaliadorSerializer(data=request.data)
#         if serializer.is_valid():
#             avaliador = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'avaliador_id': avaliador.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)

###########-------------------------------------------------------------Formulaios--------------------------------############
# @permission_classes([IsAuthenticated])
# @api_view(['GET'])
# def get_formulario(request):
#     if request.method == 'GET':
#         formularios = Formulario.objects.all()                         
#         serializer = FormularioSerializer(formularios, many=True)       
#         return Response(serializer.data)                    
#     return Response(status=status.HTTP_400_BAD_REQUEST)

# @permission_classes([IsAuthenticated])
# @api_view(['POST'])
# #@parser_classes([MultiPartParser, FormParser])
# def registerformulario(request):
#     if request.method == 'POST':
#         serializer = FormularioSerializer(data=request.data)
#         if serializer.is_valid():
#             formulario = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'formulario_id': formulario.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)

######################----------------------------------------PERGUNTAS-----------------------------------##########################
# @permission_classes([IsAuthenticated])
# @api_view(['GET'])
# def get_pergunta(request):
#     if request.method == 'GET':
#         perguntas = Pergunta.objects.all()                         
#         serializer = PerguntaSerializer(perguntas, many=True)       
#         return Response(serializer.data)                    
#     return Response(status=status.HTTP_400_BAD_REQUEST)

# @permission_classes([IsAuthenticated])
# @api_view(['POST'])
# #@parser_classes([MultiPartParser, FormParser])
# def registerpergunta(request):
#     if request.method == 'POST':
#         serializer = PerguntaSerializer(data=request.data)
#         if serializer.is_valid():
#             pergunta = serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'pergunta_id': pergunta.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)


#################-----------------------------------Inserir Pergunta no formulário-------------------===========###################
@api_view(['POST'])
def add_pergunta_formulario(request, formulario_id):
    formulario = Formulario.objects.get(pk=formulario_id)
    pergunta_id = request.data.get('pergunta_id')  # Supondo que você envia o ID da pergunta no corpo da requisição

    try:
        pergunta = Pergunta.objects.get(pk=pergunta_id)
    except Pergunta.DoesNotExist:
        return Response({'error': 'Pergunta não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

    # Verifica se a pergunta já está associada ao formulário
    if formulario.perguntas.filter(pk=pergunta_id).exists():
        return Response({'error': 'Esta pergunta já está associada ao formulário.'}, status=status.HTTP_400_BAD_REQUEST)

    # Adiciona a pergunta ao formulário na tabela intermediária
    formulario.perguntas.add(pergunta)

    # Serializa o formulário atualizado para retornar na resposta
    serializer = FormularioSerializer(formulario)
    return Response(serializer.data, status=status.HTTP_201_CREATED)



# @api_view(['POST'])
# def upload(request):
#     if request.method == 'POST':
#         serializer = UploadSerializer(data=request.data)
#         if serializer.is_valid():
#             upload= serializer.save()
#             return Response({'message': 'Area cadastrada com sucesso!', 'upload_id': upload.id})
#         return Response(status=status.HTTP_400_BAD_REQUEST)

###########################----------------------------------------------------------######################


@api_view(['GET'])
def get_perguntas_formularios(request, formulario_id):
    try:
        formulario = Formulario.objects.get(id=formulario_id)
        perguntas = formulario.perguntas.all()  # Obtém todas as perguntas associadas a este formulário
        perguntas_data = [{'id': pergunta.id, 'texto': pergunta.texto,'legenda':pergunta.legenda} for pergunta in perguntas]
        return Response(perguntas_data)
    except Formulario.DoesNotExist:
        return Response({'error': 'Formulário não encontrado'}, status=404)
    except Exception as e:
        return Response({'error': str(e)}, status=500)


#####################################################################

# @api_view(['POST'])
# class AvaliadoViewSet(viewsets.ModelViewSet):
#     queryset = Avaliado.objects.all()
#     serializer_class = AvaliadoSerializer

#     def create(self, request, *args, **kwargs):
#         serializer = self.get_serializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
#         avaliado = self.perform_create(serializer)
#         headers = self.get_success_headers(serializer.data)
#         return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

#     def perform_create(self, serializer):
#         avaliadores_data = self.request.data.get('avaliadores', [])  # Extrai os dados dos avaliadores do avaliado
#         avaliado = serializer.save()

#         # Adiciona os avaliadores ao avaliado recém-criado
#         for avaliador_data in avaliadores_data:
#             avaliador = Avaliador.objects.create(**avaliador_data)
#             avaliado.avaliadores.add(avaliador)

#         return avaliado






    #get as funções
@api_view(['GET'])
#@permission_classes([IsAuthenticated])
def get_funcao(request):

    if request.method == 'GET':

        funcao = Group.objects.all()                          
        nomes_funcoes = [funcao.name for funcao in funcao]       

        return Response(nomes_funcoes)                    
    
    return Response(status=status.HTTP_400_BAD_REQUEST)


# @api_view(['GET'])
# def informacoes_avaliador(request, user_id):
#     avaliador = get_object_or_404(Avaliador, usuario_id=user_id)
#     colaborador = avaliador.colaborador
#     avaliador_serializer = AvaliadorSerializer(avaliador)
#     colaborador_serializer = ColaboradorSerializer(colaborador)  # Adicione o serializer do Colaborador
#     return Response({
#         'avaliador': avaliador_serializer.data,
#         'colaborador': colaborador_serializer.data,  # Inclua os dados do Colaborador na resposta
#     })

# @api_view(['GET'])
# def informacoes_avaliador(request, avaliador_id):
#     try:
#         avaliador = Avaliador.objects.get(id=avaliador_id)
#         serializer = AvaliadorSerializer(avaliador)
#         return Response(serializer.data)
#     except Avaliador.DoesNotExist:
#         return Response({"error": "Avaliador não encontrado."}, status=404)

# @api_view(['GET'])

# def avaliador_do_usuario(request):
#     user_id = request.user.id
#     try:
#         avaliador = Avaliador.objects.get(usuario_id=user_id)
#         serializer = AvaliadorSerializer(avaliador)
#         return Response(serializer.data)
#     except Avaliador.DoesNotExist:
#         return Response({"error": "Avaliador não encontrado para este usuário."}, status=404)


    

# @api_view(['POST'])
# def add_avaliado_avaliador(request, avaliador_id):
#     try:
#         avaliador = Avaliador.objects.get(pk=avaliador_id)
#     except Avaliador.DoesNotExist:
#         return Response({'error': 'Avaliador não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

#     avaliado_id = request.data.get('avaliado_id')  # Supondo que você envia o ID do avaliado no corpo da requisição

#     try:
#         avaliado = Avaliado.objects.get(pk=avaliado_id)
#     except Avaliado.DoesNotExist:
#         return Response({'error': 'Avaliado não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

#     # Verifica se o avaliado já está associado ao avaliador
#     if avaliador.avaliados.filter(pk=avaliado_id).exists():
#         return Response({'error': 'Este avaliado já está associado ao avaliador.'}, status=status.HTTP_400_BAD_REQUEST)

#     # Adiciona o avaliado ao avaliador na tabela intermediária
#     avaliador.avaliados.add(avaliado)

#     # Serializa o avaliador atualizado para retornar na resposta
#     serializer = AvaliadorSerializer(avaliador)
#     return Response(serializer.data, status=status.HTTP_201_CREATED)


# @api_view(['GET'])
# def get_avaliados_avaliador(request, avaliador_id):
#     try:
#         avaliador = Avaliador.objects.get(pk=avaliador_id)
#     except Avaliador.DoesNotExist:
#         return Response({'error': 'Avaliador não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

#     avaliados = avaliador.avaliados.all()
#     serializer = AvaliadoSerializer(avaliados, many=True)
#     return Response(serializer.data)

##########------------------------------------------------------------------------------------------------------------------------------------------------------#################
class AvaliadoViewSet(viewsets.ModelViewSet):
    queryset = Avaliado.objects.all()
    serializer_class = AvaliadoSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if 'image' in serializer.validated_data:
            image_url = request.build_absolute_uri(instance.image.url)
            return Response({'image_url': image_url, **serializer.data})
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='transformar_em_avaliado')
    def transformar_em_avaliado(self, request, pk=None):
        colaborador = get_object_or_404(Colaborador, pk=pk)
        formulario_id = request.data.get('formulario_id')

        if not formulario_id:
            return Response({'error': 'Formulário ID é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            formulario = Formulario.objects.get(pk=formulario_id)
        except Formulario.DoesNotExist:
            return Response({'error': 'Formulário não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        # Transformar o colaborador em avaliado
        avaliado = Avaliado(
            colaborador_ptr=colaborador,
            formulario=formulario,
            empresa=colaborador.empresa,
            filial=colaborador.filial,
            setor=colaborador.setor,
            area=colaborador.area,
            cargo=colaborador.cargo,
            ambiente=colaborador.ambiente,
            tipocontrato=colaborador.tipocontrato,
            nome=colaborador.nome,
            data_admissao=colaborador.data_admissao,
            situacao=colaborador.situacao,
            genero=colaborador.genero,
            estado_civil=colaborador.estado_civil,
            data_nascimento=colaborador.data_nascimento,
            data_troca_setor=colaborador.data_troca_setor,
            data_troca_cargo=colaborador.data_troca_cargo,
            data_demissao=colaborador.data_demissao,
            create_at=colaborador.create_at,
            image=colaborador.image,
            email=colaborador.email
        )
        avaliado.save()

        serializer = self.get_serializer(avaliado)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    @action(detail=True, methods=['get'])
    def get_avaliado(self, request, pk=None):
        avaliado = self.get_object()
        serializer = self.get_serializer(avaliado)
        return Response(serializer.data)
    @action(detail=False, methods=['get'], url_path='byTipoAvaliacao')
    def by_tipo_avaliacao(self, request):
        tipo_avaliacao_id = request.query_params.get('tipoAvaliacao')
        if not tipo_avaliacao_id:
            return Response({'detail': 'TipoAvaliacao ID is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            tipo_avaliacao = TipoAvaliacao.objects.get(id=tipo_avaliacao_id)
        except TipoAvaliacao.DoesNotExist:
            return Response({'detail': 'TipoAvaliacao not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Utilizando o campo de relacionamento many-to-many correto
        avaliados = Avaliado.objects.filter(tipoAvaliacao__id=tipo_avaliacao_id)
        serializer = AvaliadoSerializer(avaliados, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'],url_path='byAvaliador')
    def byAvaliador(self, request):
        avaliador_id = request.query_params.get('avaliador_id')
        try:
            avaliador = Avaliador.objects.get(id=avaliador_id)  # Busque o objeto Avaliador
        except Avaliador.DoesNotExist:
            raise NotFound('Avaliador não encontrado')  # type: ignore # Levante um erro se o Avaliador não existir
        avaliados = avaliador.avaliados.all()
        serializer = AvaliadoSerializer(avaliados, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

     


class ColaboradorViewSet(viewsets.ModelViewSet):
    queryset = Colaborador.objects.all()
    serializer_class = ColaboradorSerializer  


    # c



    # def partial_update(self, request, *args, **kwargs):
    #     kwargs['partial'] = True
    #     instance = self.get_object()
    #     serializer = self.get_serializer(instance, data=request.data, partial=True)
    #     serializer.is_valid(raise_exception=True)
    #     self.perform_update(serializer)
    #     if 'image' in serializer.validated_data:
    #         image_url = request.build_absolute_uri(instance.image.url)
    #         return Response({'image_url': image_url, **serializer.data})
        
    #     return Response(serializer.data)
    
    def perform_create(self, serializer):
        username = self.request.data.get('username', None)
        password = self.request.data.get('password', None)
        tornar_avaliado = self.request.data.get('tornar_avaliado', False)
        tornar_avaliador = self.request.data.get('tornar_avaliador', False)
        tornar_gestor = self.request.data.get('tornar_gestor', False)
        colaborador = serializer.save()
        
        if username and password:
            user = User.objects.create_user(username=username, password=password)
            colaborador.user = user
            colaborador.save()
        if tornar_avaliado and not hasattr(colaborador, 'avaliado'):
            Avaliado.objects.create(
                colaborador_ptr=colaborador,
                **{field: getattr(colaborador, field) for field in [f.name for f in Colaborador._meta.fields if f.name != 'id']}
            )

        if tornar_avaliador and not hasattr(colaborador, 'avaliador'):
            Avaliador.objects.create(
                colaborador_ptr=colaborador,
                **{field: getattr(colaborador, field) for field in [f.name for f in Colaborador._meta.fields if f.name != 'id']}
            )

        if tornar_gestor and not hasattr(colaborador, 'gestor'):
            Gestor.objects.create(
                colaborador_ptr=colaborador,
                **{field: getattr(colaborador, field) for field in [f.name for f in Colaborador._meta.fields if f.name != 'id']}
            )    

    @action(detail=False, methods=['get'])
    def meInfo(self, request):
        try:
            user = request.user
            colaborador = Colaborador.objects.get(user=user)
            serializer = self.get_serializer(colaborador)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Colaborador.DoesNotExist:
            return Response({"error": "Colaborador não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def perform_update(self, serializer):
        username = self.request.data.get('username', None)
        password = self.request.data.get('password', None)
        tornar_avaliado = self.request.data.get('tornar_avaliado', False)
        tornar_avaliador = self.request.data.get('tornar_avaliador', False)
        tornar_gestor = self.request.data.get('tornar_gestor', False)

        colaborador = serializer.save()

        if username and password:
            if colaborador.user:
                user = colaborador.user
                user.username = username
                if password:
                    user.set_password(password)
                user.save()
            else:
                user = User.objects.create_user(username=username, password=password)
                colaborador.user = user
                colaborador.save()

        if tornar_avaliado and not hasattr(colaborador, 'avaliado'):
            Avaliado.objects.create(
                colaborador_ptr=colaborador,
                **{field: getattr(colaborador, field) for field in [f.name for f in Colaborador._meta.fields if f.name != 'id']}
            )

        if tornar_avaliador and not hasattr(colaborador, 'avaliador'):
            Avaliador.objects.create(
                colaborador_ptr=colaborador,
                **{field: getattr(colaborador, field) for field in [f.name for f in Colaborador._meta.fields if f.name != 'id']}
            )

        if tornar_gestor and not hasattr(colaborador, 'gestor'):
            Gestor.objects.create(
                colaborador_ptr=colaborador,
                **{field: getattr(colaborador, field) for field in [f.name for f in Colaborador._meta.fields if f.name != 'id']}
            )    
                
        
    
class AvaliadorViewSet(viewsets.ModelViewSet):
    queryset = Avaliador.objects.all()
    serializer_class = AvaliadorSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    @action(detail=True, methods=['post'], url_path='transformar_em_avaliador')
    def transformar_em_avaliador(self, request, pk=None):
        colaborador = get_object_or_404(Colaborador, pk=pk)
        usuario_id = request.data.get('usuario_id')

        if not usuario_id:
            return Response({'error': 'Usuário ID é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            usuario = User.objects.get(pk=usuario_id)
        except User.DoesNotExist:
            return Response({'error': 'Usuário não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        # Transformar o colaborador em avaliador
        avaliador = Avaliador(
            colaborador_ptr=colaborador,
            usuario=usuario,
            empresa=colaborador.empresa,
            filial=colaborador.filial,
            setor=colaborador.setor,
            area=colaborador.area,
            cargo=colaborador.cargo,
            ambiente=colaborador.ambiente,
            tipocontrato=colaborador.tipocontrato,
            nome=colaborador.nome,
            data_admissao=colaborador.data_admissao,
            situacao=colaborador.situacao,
            genero=colaborador.genero,
            estado_civil=colaborador.estado_civil,
            data_nascimento=colaborador.data_nascimento,
            data_troca_setor=colaborador.data_troca_setor,
            data_troca_cargo=colaborador.data_troca_cargo,
            data_demissao=colaborador.data_demissao,
            create_at=colaborador.create_at,
            image=colaborador.image,
            email=colaborador.email
        )
        avaliador.save()

        serializer = self.get_serializer(avaliador)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=['get'], url_path='meus_avaliados')
    def meus_avaliados(self, request):
        try:
            user = request.user
            avaliador = Avaliador.objects.get(user=user)
            avaliados = avaliador.avaliados.all()
            serializer = AvaliadoSerializer(avaliados, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Avaliador.DoesNotExist:
            return Response({"error": "Avaliador não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

       
        
    @action(detail=False, methods=['get'])
    def me(self, request):
        try:
            user = request.user
            avaliador = Avaliador.objects.get(user=user)
            serializer = self.get_serializer(avaliador)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Avaliador.DoesNotExist:
            return Response({"error": "Avaliador não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
    @action(detail=True, methods=['post'], url_path='add_avaliado')
    def add_avaliado(self, request, pk=None):
        avaliador = self.get_object()
        avaliado_id = request.data.get('avaliado_id')  # Supondo que você envia o ID da pergunta no corpo da requisição

        try:
            avaliado = Avaliado.objects.get(pk=avaliado_id)
        except Pergunta.DoesNotExist:
            return Response({'error': 'Avaliado não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        # Verifica se a pergunta já está associada ao formulário
        if avaliador.avaliados.filter(pk=avaliado_id).exists():
            return Response({'error': 'Este avaliado já está associado ao avaliador.'}, status=status.HTTP_400_BAD_REQUEST)

        # Adiciona a pergunta ao formulário na tabela intermediária
        avaliador.avaliados.add(avaliado)

        # Serializa o formulário atualizado para retornar na resposta
        serializer = AvaliadorSerializer(avaliador)
        return Response(serializer.data, status=status.HTTP_201_CREATED)    
    
    @action(detail=True, methods=['post'], url_path='remove_avaliado')
    def remove_avaliado(self, request, pk=None):
        avaliador = self.get_object()
        avaliado_id = request.data.get('avaliado_id')

        try:
            avaliado = Avaliado.objects.get(pk=avaliado_id)
        except Avaliado.DoesNotExist:
            return Response({'error': 'Avaliado não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        if not avaliador.avaliados.filter(pk=avaliado_id).exists():
            return Response({'error': 'Este avaliado não está associado ao avaliador.'}, status=status.HTTP_400_BAD_REQUEST)

        avaliador.avaliados.remove(avaliado)
        serializer = AvaliadorSerializer(avaliador)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class EmpresaViewSet(viewsets.ModelViewSet):
    queryset = Empresa.objects.all()
    serializer_class = EmpresaSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

class FilialViewSet(viewsets.ModelViewSet):
    queryset = Filial.objects.all()
    serializer_class = FilialSerializer    
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    @action(detail=False, methods=['get'],url_path='byEmpresa')
    def byEmpresa(self, request):
        empresa_id = request.query_params.get('empresa_id')
        filiais = Filial.objects.filter(empresa_id=empresa_id)
        serializer = self.get_serializer(filiais, many=True)
        return Response(serializer.data)
    
class AreaViewSet(viewsets.ModelViewSet):
    queryset = Area.objects.all()
    serializer_class = AreaSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'],url_path='byFilial')
    def byFilial(self, request):
        filial_id = request.query_params.get('filial_id')
        areas = Area.objects.filter(filial_id=filial_id)
        serializer = self.get_serializer(areas, many=True)
        return Response(serializer.data)        

class SetorViewSet(viewsets.ModelViewSet):
    queryset = Setor.objects.all()
    serializer_class = SetorSerializer        
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'],url_path='byArea')
    def byArea(self, request):
        area_id = request.query_params.get('area_id')
        setores = Setor.objects.filter(area_id=area_id)
        serializer = self.get_serializer(setores, many=True)
        return Response(serializer.data)
    
class AmbienteViewSet(viewsets.ModelViewSet):
    queryset = Ambiente.objects.all()
    serializer_class = AmbienteSerializer        
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data) 
    
    @action(detail=False, methods=['get'],url_path='bySetor')
    def bySetor(self, request):
        setor_id = request.query_params.get('setor_id')
        ambientes = Ambiente.objects.filter(setor_id=setor_id)
        serializer = self.get_serializer(ambientes, many=True)
        return Response(serializer.data)

class CargoViewSet(viewsets.ModelViewSet):
    queryset = Cargo.objects.all()
    serializer_class = CargoSerializer
    permission_classes = [DjangoModelPermissions]
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)  

    @action(detail=False, methods=['get'],url_path='byAmbiente')
    def byAmbiente(self, request):
        ambiente_id = request.query_params.get('ambiente_id')
        cargos = Cargo.objects.filter(ambiente_id=ambiente_id)
        serializer = self.get_serializer(cargos, many=True)
        return Response(serializer.data)      

class TipoContratoViewSet(viewsets.ModelViewSet):
    queryset = TipoContrato.objects.all()
    serializer_class = TipoContratoSerializer        
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'],url_path='byCargo')
    def byCargo(self, request):
        cargo_id = request.query_params.get('cargo_id')
        tiposcontratos = TipoContrato.objects.filter(cargo_id=cargo_id)
        serializer = self.get_serializer(tiposcontratos, many=True)
        return Response(serializer.data)

class TipoAvaliacaoViewSet(viewsets.ModelViewSet):
    queryset = TipoAvaliacao.objects.all()
    serializer_class = TipoAvaliacaoSerializer   
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)   
        
    @action(detail=False, methods=['get'], url_path='user/(?P<user_id>[^/.]+)')
    def get_by_user(self, request, user_id=None):
        try:
            tipos_avaliacao = TipoAvaliacao.objects.filter(avaliados__id=user_id)
            serializer = self.get_serializer(tipos_avaliacao, many=True)
            return Response(serializer.data)
        except TipoAvaliacao.DoesNotExist:
            return Response({'error': 'Tipo de avaliação não encontrado'}, status=404)

class AvaliacaoViewSet(viewsets.ModelViewSet):
    queryset = Avaliacao.objects.all()
    serializer_class = AvaliacaoSerializer 
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)  

    def perform_create(self, serializer):
        if 'feedback' not in self.request.data:
            serializer.save(feedback=False)
        else:
            serializer.save()

    @action(detail=True, methods=['post'])
    def update_feedback(self, request, pk=None):
        try:
            avaliacao = self.get_object()
            avaliacao.feedback = True
            avaliacao.finished_at = timezone.now()
            avaliacao.save()
            return Response({'status': 'success'})
        except Avaliacao.DoesNotExist:
            return Response({'status': 'error', 'message': 'Avaliação não encontrada'}, status=404)
    
   # @action(detail=False, methods=['get'], url_path='meus_avaliados_sem_avaliacao')
   # def meus_avaliados_sem_avaliacao(self, request):
    #    try:
     #       user = request.user
      #      periodo = request.query_params.get('periodo')

       #     if not periodo:
        #        return Response({'status': 'error', 'message': 'Período não fornecido'}, status=status.HTTP_400_BAD_REQUEST)

         #   avaliador = Avaliador.objects.get(user=user)
          #  avaliados = avaliador.avaliados.all()

            # Filtrar avaliados que não têm avaliação no período especificado
           # avaliados_com_avaliacao = Avaliacao.objects.filter(periodo=periodo, avaliado__in=avaliados).values_list('avaliado_id', flat=True)
            #avaliados_sem_avaliacao = avaliados.exclude(id__in=avaliados_com_avaliacao)

            #serializer = AvaliadoSerializer(avaliados_sem_avaliacao, many=True)
            #return Response(serializer.data, status=status.HTTP_200_OK)
        #except Avaliador.DoesNotExist:
            #return Response({"error": "Avaliador não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        #except Exception as e:
            #return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
    @action(detail=False, methods=['get'], url_path='meus_avaliados_sem_avaliacao')
    def meus_avaliados_sem_avaliacao(self, request):
        try:
            user = request.user
            periodo = request.query_params.get('periodo')

            if not periodo:
                return Response({'status': 'error', 'message': 'Período não fornecido'}, status=status.HTTP_400_BAD_REQUEST)

            avaliador = Avaliador.objects.get(user=user)
            avaliados = avaliador.avaliados.all()

            # Filtrar avaliados que não têm avaliação pelo avaliador atual no período especificado
            avaliados_com_avaliacao_pelo_avaliador = Avaliacao.objects.filter(periodo=periodo, avaliador=avaliador).values_list('avaliado_id', flat=True)
            avaliados_sem_avaliacao = avaliados.exclude(id__in=avaliados_com_avaliacao_pelo_avaliador)

            serializer = AvaliadoSerializer(avaliados_sem_avaliacao, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Avaliador.DoesNotExist:
            return Response({"error": "Avaliador não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)



    @action(detail=False, methods=['get'],url_path='byAvaliador')
    def byAvaliador(self, request):
        avaliador_id = request.query_params.get('avaliador_id')
        try:
            avaliador = Avaliador.objects.get(id=avaliador_id)  # Busque o objeto Avaliador
        except Avaliador.DoesNotExist:
            raise NotFound('Avaliador não encontrado')  # type: ignore # Levante um erro se o Avaliador não existir
        avaliados = avaliador.avaliados.all()
        serializer = AvaliadoSerializer(avaliados, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='minhas_avaliacoes')
    def minhas_avaliacoes(self, request):
        try:
            user = request.user
            avaliador = Avaliador.objects.get(user=user)
            avaliacoes = Avaliacao.objects.filter(avaliador=avaliador)
            serializer = AvaliacaoSerializer(avaliacoes, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Avaliador.DoesNotExist:
            return Response({"error": "Avaliador não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)    
    

class PerguntaViewSet(viewsets.ModelViewSet):
    queryset = Pergunta.objects.all()
    serializer_class = PerguntaSerializer     
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

# class FormularioViewSet(viewsets.ModelViewSet):
#     queryset = Pergunta.objects.all()
#     serializer_class = PerguntaSerializer     
#     def partial_update(self, request, *args, **kwargs):
#         instance = self.get_object()
#         serializer = self.get_serializer(instance, data=request.data, partial=True)
#         serializer.is_valid(raise_exception=True)
#         self.perform_update(serializer)
#         return Response(serializer.data)    

# class FormularioViewSet(viewsets.ModelViewSet):
#     queryset = Formulario.objects.all()
#     def partial_update(self, request, *args, **kwargs):
#         instance = self.get_object()
#         serializer = self.get_serializer(instance, data=request.data, partial=True)
#         serializer.is_valid(raise_exception=True)
#         self.perform_update(serializer)
#         return Response(serializer.data)

#     def get_serializer_class(self):
#         if self.action == 'create':
#             return FormularioCreateSerializer
#         if self.action in ['update', 'partial_update']:
#             return FormularioUpdateSerializer
#         return FormularioCreateSerializer
class FormularioViewSet(viewsets.ModelViewSet):
    queryset = Formulario.objects.all()
    serializer_class = FormularioSerializer 
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='add_pergunta')
    def add_pergunta(self, request, pk=None):
        formulario = self.get_object()
        pergunta_id = request.data.get('pergunta_id')  # Supondo que você envia o ID da pergunta no corpo da requisição

        try:
            pergunta = Pergunta.objects.get(pk=pergunta_id)
        except Pergunta.DoesNotExist:
            return Response({'error': 'Pergunta não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        # Verifica se a pergunta já está associada ao formulário
        if formulario.perguntas.filter(pk=pergunta_id).exists():
            return Response({'error': 'Esta pergunta já está associada ao formulário.'}, status=status.HTTP_400_BAD_REQUEST)

        # Adiciona a pergunta ao formulário na tabela intermediária
        formulario.perguntas.add(pergunta)

        # Serializa o formulário atualizado para retornar na resposta
        serializer = FormularioSerializer(formulario)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'], url_path='add_avaliado')
    def add_avaliado(self, request, pk=None):
        formulario = self.get_object()
        avaliado_id = request.data.get('avaliado_id')  # Supondo que você envia o ID da pergunta no corpo da requisição

        try:
            avaliado = Avaliado.objects.get(pk=avaliado_id)
        except Avaliado.DoesNotExist:
            return Response({'error': 'Avaliado não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        # Verifica se a pergunta já está associada ao formulário
        if formulario.avaliados.filter(pk=avaliado_id).exists():
            return Response({'error': 'Este avaliado já está associada ao formulário.'}, status=status.HTTP_400_BAD_REQUEST)

        # Adiciona a pergunta ao formulário na tabela intermediária
        formulario.avaliados.add(avaliado)

        # Serializa o formulário atualizado para retornar na resposta
        serializer = FormularioSerializer(formulario)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'], url_path='remove_pergunta')
    def remove_pergunta(self, request, pk=None):
        formulario = self.get_object()
        pergunta_id = request.data.get('pergunta_id')

        try:
            pergunta = Pergunta.objects.get(pk=pergunta_id)
        except Pergunta.DoesNotExist:
            return Response({'error': 'Pergunta não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        if not formulario.perguntas.filter(pk=pergunta_id).exists():
            return Response({'error': 'Esta pergunta não está associada ao formulário.'}, status=status.HTTP_400_BAD_REQUEST)

        formulario.perguntas.remove(pergunta)
        serializer = FormularioSerializer(formulario)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'], url_path='remove_avaliado')
    def remove_avaliado(self, request, pk=None):
        formulario = self.get_object()
        avaliado_id = request.data.get('avaliado_id')

        try:
            avaliado = Avaliado.objects.get(pk=avaliado_id)
        except Avaliado.DoesNotExist:
            return Response({'error': 'Avaliado não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        if not formulario.avaliados.filter(pk=avaliado_id).exists():
            return Response({'error': 'Este avaliado não está associado ao formulário.'}, status=status.HTTP_400_BAD_REQUEST)

        formulario.avaliados.remove(avaliado)
        serializer = FormularioSerializer(formulario)
        return Response(serializer.data, status=status.HTTP_200_OK)

    ##########################################################################################
   
@api_view(['POST'])
def send_email_view(request):
    subject = request.data.get('subject')
    message = request.data.get('message')
    recipient_list = request.data.get('recipients')

    # Converting recipient_list to a list if it's a string
    if isinstance(recipient_list, str):
        recipient_list = [recipient.strip() for recipient in recipient_list.split(',')]

    if not subject or not message or not recipient_list:
        return Response({"error": "All fields are required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        send_custom_email(subject, message, recipient_list)
        return Response({"success": "Email sent successfully"}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    #########################################################################################

def obterTrimestre(data):
    mes = data.month
    if mes in [1, 2, 3]:
        return 'Primeiro trimesmtre'
    elif mes in [4, 5, 6]:
        return 'Segundo trimesmtre'
    elif mes in [7, 8, 9]:
        return 'Terceiro trimesmtre'
    elif mes in [10, 11, 12]:
        return 'Quarto trimesmtre'



@api_view(['POST'])
def send_email_view2(request):
    subject = request.data.get('subject')
    message = request.data.get('message')

    if not subject or not message:
        return Response({"error": "Subject and message are required"}, status=status.HTTP_400_BAD_REQUEST)

    now = timezone.now()
    trimestre_atual = obterTrimestre(now)

    # Encontrar todos os avaliados sem avaliação no trimestre atual
    avaliados_sem_avaliacao = Avaliado.objects.filter(
        ~Q(avaliacoes_avaliado__periodo=trimestre_atual)
    ).distinct()

    # Encontrar os avaliadores desses avaliados
    avaliadores_sem_avaliacao = Avaliador.objects.filter(
        avaliados__in=avaliados_sem_avaliacao
    ).distinct()

    # Construir a lista de destinatários
    recipient_list = [avaliador.email for avaliador in avaliadores_sem_avaliacao]

    if not recipient_list:
        return Response({"error": "No evaluators found without evaluations"}, status=status.HTTP_404_NOT_FOUND)

    try:
        send_custom_email(subject, message, recipient_list)
        return Response({"success": "Email sent successfully"}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

    


###########################################################################################################################

def obterTrimestre(data):
    mes = data.month
    if mes in [1, 2, 3]:
        return 'Quarto Trimestre'
    elif mes in [4, 5, 6]:
        return 'Primeiro Trimestre'
    elif mes in [7, 8, 9]:
        return 'Segundo Trimestre'
    elif mes in [10, 11, 12]:
        return 'Terceiro Trimestre'

class NotificationViewSet(viewsets.ViewSet):
    def list(self, request):
        notifications = request.user.notifications.unread()
        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data)
    
    # @action(detail=False, methods=['post'])
    # def enviar_emails(self, request):
    #     subject = 'RH Dagoberto Barcellos'
    #     message = 'Avaliações ainda pendentes no período atual'

    #     if not subject or not message:
    #         return Response({"error": "Erro ao enviar email"}, status=status.HTTP_400_BAD_REQUEST)

    #     # Obter o avaliador logado
    #     avaliador = Avaliador.objects.get(user=request.user)

    #     now = timezone.now()
    #     trimestre_atual = obterTrimestre(now)

    #     # Encontrar avaliados sem avaliação no trimestre atual para o avaliador logado
    #     avaliados_sem_avaliacao = Avaliado.objects.exclude(
    #         avaliacoes_avaliado__periodo=trimestre_atual
    #     ).filter(avaliadores=avaliador).distinct()

    #     if not avaliados_sem_avaliacao.exists():
    #         return Response({"message": "Nenhum avaliador sem avaliação."}, status=status.HTTP_204_NO_CONTENT)

    #     # Construir o corpo do email incluindo os avaliados sem avaliação para o avaliador atual
    #     email_body = f"{message}\n\nAvaliados sem avaliação no trimestre atual:\n"
    #     for avaliado in avaliados_sem_avaliacao:
    #         email_body += f"- {avaliado.nome}\n"

    #     try:
    #         send_custom_email(subject, email_body, [avaliador.user.email])  # Enviando para o email do avaliador logado
    #     except Exception as e:
    #         return Response({"error": "Erro ao enviar email"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    #     return Response({"success": "Email enviado com sucesso!"}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def enviar_notificacoes(self, request):
        task = enviar_notificacoes
        return Response({"success": "Notificações enviadas"}, status=status.HTTP_200_OK)


        # avaliador_id = request.data.get('avaliador_id')

        # if not avaliador_id:
        #     return Response({"error": "Avaliador ID não fornecido."}, status=status.HTTP_400_BAD_REQUEST)

        # try:
        #     avaliador = Avaliador.objects.get(id=avaliador_id)
        # except Avaliador.DoesNotExist:
        #     return Response({"error": "Avaliador não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        # now = timezone.now()
        # trimestre_atual = obterTrimestre(now)

        # avaliados_sem_avaliacao = Avaliado.objects.filter(
        #     ~Q(avaliacoes_avaliado__periodo=trimestre_atual)
        # ).distinct()

        # avaliadores_sem_avaliacao = Avaliador.objects.filter(
        #     avaliados__in=avaliados_sem_avaliacao
        # ).distinct()

        # # Enviar notificações para os avaliadores sem avaliações no trimestre atual
        # for avaliador in avaliadores_sem_avaliacao:
        #     # Verifica se o avaliador tem um usuário associado
        #     if avaliador.user is None:
        #         continue  # Pula este avaliador se não tiver usuário associado

        #     for avaliado in avaliador.avaliados.filter(id__in=avaliados_sem_avaliacao).all():
        #         notify.send(
        #             sender=request.user,  # Quem envia a notificação (usuário autenticado)
        #             recipient=avaliador.user,  # Avaliador (instância de User)
        #             verb='Nova notificação!!',
        #             description=f'Nova avaliação pendente no período atual para {avaliado.nome}'
        #         )

        # return Response({"success": "Notificações enviadas"}, status=status.HTTP_200_OK)
        
    @action(detail=False, methods=['post'])
    def marcar_como_lidas(self, request):
        request.user.notifications.mark_all_as_read()
        return Response({"success": "Todas as notificações foram marcadas como lidas"}, status=status.HTTP_200_OK)



    @action(detail=False, methods=['get'])
    def contar_nao_lidas(self, request):
        unread_count = request.user.notifications.unread().count()
        return Response({"unread_count": unread_count}, status=status.HTTP_200_OK)




class YourViewSet(viewsets.ViewSet):

    @action(detail=False, methods=['get'], url_path='meus_avaliados_sem_avaliacao')
    def meus_avaliados_sem_avaliacao(self, request):
        try:
            user = request.user
            periodo = request.query_params.get('periodo')

            if not periodo:
                return Response({'status': 'error', 'message': 'Período não fornecido'}, status=status.HTTP_400_BAD_REQUEST)

            avaliador = Avaliador.objects.get(user=user)
            avaliados = avaliador.avaliados.filter(periodo=periodo)

            avaliados_com_avaliacao = Avaliacao.objects.filter(periodo=periodo, avaliado__in=avaliados).values_list('avaliado_id', flat=True)
            avaliados_sem_avaliacao = avaliados.exclude(id__in=avaliados_com_avaliacao)

            if avaliados_sem_avaliacao.exists():
                self.enviar_email_avaliador(avaliador, periodo, avaliados_sem_avaliacao)

            serializer = AvaliadoSerializer(avaliados_sem_avaliacao, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Avaliador.DoesNotExist:
            return Response({"error": "Avaliador não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # def enviar_email_avaliador(self, avaliador, periodo, avaliados_sem_avaliacao):
    #     subject = f"Avaliações Pendentes para o Período {periodo}"
    #     message = f"Prezado {avaliador.user.first_name},\n\nVocê possui os seguintes avaliados sem avaliação para o período {periodo}:\n"
    #     for avaliado in avaliados_sem_avaliacao:
    #         message += f"- {avaliado.nome}\n"
    #     message += "\nPor favor, realize as avaliações pendentes o mais breve possível.\n\nAtenciosamente,\nEquipe de Gestão"

    #     send_mail(
    #         subject,
    #         message,
    #         settings.EMAIL_HOST_USER,
    #         [avaliador.user.email],
    #         fail_silently=False,
    #     )


# class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
#     def validate(self, attrs):
#         data = super().validate(attrs)
#         refresh = self.get_token(self.user)
        
#         data['refresh'] = str(refresh)
#         data['access'] = str(refresh.access_token)
#         data['primeiro_acesso'] = self.user.primeiro_acesso  # Adicione o campo personalizado aqui

#         return data

# class CustomTokenObtainPairView(TokenObtainPairView):
#     serializer_class = CustomTokenObtainPairSerializer  

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        refresh = self.get_token(self.user)
        
        data['refresh'] = str(refresh)
        data['access'] = str(refresh.access_token)
        data['primeiro_acesso'] = self.user.primeiro_acesso  # Adicione o campo personalizado aqui
        data['groups'] = list(self.user.groups.values_list('name', flat=True))  # Adiciona a lista de grupos do usuário

        return data

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

class HistoricoAlteracaoViewSet(viewsets.ModelViewSet):
    queryset = HistoricoAlteracao.objects.all()
    serializer_class = HistoricoAlteracaoSerializer

#########------------------------CONVERTER GESTOR-----------------------------###############
class GestorViewSet(viewsets.ModelViewSet):
    queryset = Gestor.objects.all()
    serializer_class = GestorSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if 'image' in serializer.validated_data:
            image_url = request.build_absolute_uri(instance.image.url)
            return Response({'image_url': image_url, **serializer.data})
        return Response(serializer.data)    
    
    @action(detail=True, methods=['post'], url_path='transformar_em_gestor')
    def transformar_em_gestor(self, request, pk=None):
        colaborador = get_object_or_404(Colaborador, pk=pk)

        # Transformar o colaborador em avaliado
        gestor = Gestor(
            colaborador_ptr=colaborador,
            empresa=colaborador.empresa,
            filial=colaborador.filial,
            setor=colaborador.setor,
            area=colaborador.area,
            cargo=colaborador.cargo,
            ambiente=colaborador.ambiente,
            tipocontrato=colaborador.tipocontrato,
            nome=colaborador.nome,
            data_admissao=colaborador.data_admissao,
            situacao=colaborador.situacao,
            genero=colaborador.genero,
            estado_civil=colaborador.estado_civil,
            data_nascimento=colaborador.data_nascimento,
            data_troca_setor=colaborador.data_troca_setor,
            data_troca_cargo=colaborador.data_troca_cargo,
            data_demissao=colaborador.data_demissao,
            create_at=colaborador.create_at,
            image=colaborador.image,
            email=colaborador.email
        )
        gestor.save()

        serializer = self.get_serializer(gestor)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    @action(detail=True, methods=['get'])
    def get_gestor(self, request, pk=None):
        gestor = self.get_object()
        serializer = self.get_serializer(gestor)
        return Response(serializer.data)