from django.shortcuts import render,HttpResponse

# Create your views here.
def management(request):
    return HttpResponse(request,'ok')
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
from rest_framework.permissions import IsAuthenticated,GroupPermission
from rest_framework.decorators import api_view,authentication_classes, permission_classes,parser_classes,action
from rest_framework.response import Response
from rest_framework import status, viewsets

from .models import Ambiente, Empresa,Area,Cargo,Setor,Colaborador,Filial,TipoContrato,TipoAvaliacao,Avaliacao,Avaliador,Formulario,Pergunta,Avaliado

from .serializers import LoginSerializer, UserSerializer,EmpresaSerializer,GroupSerializer,AreaSerializer,SetorSerializer,CargoSerializer,ColaboradorSerializer,FilialSerializer,TipoContratoSerializer,TipoAvaliacaoSerializer,AvaliacaoSerializer,AvaliadorSerializer,PerguntaSerializer,AvaliadoSerializer,AmbienteSerializer
from.serializers import FormularioCreateSerializer,FormularioUpdateSerializer,FormularioSerializer

@api_view(['GET','POST'])
def login(request):
    if request.method == "GET":
        return render(request,'login.html')
    else:    
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data['username']
            password = serializer.validated_data['password']
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                
                return Response({'message': 'Login bem-sucedido'}, status=status.HTTP_200_OK)
            else:
                # Credenciais inválidas
                return Response({'message': 'Credenciais inválidas'}, status=status.HTTP_401_UNAUTHORIZED)
        else:
            # Dados inválidos
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




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
@permission_classes([IsAuthenticated])
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
        perguntas_data = [{'id': pergunta.id, 'texto': pergunta.texto} for pergunta in perguntas]
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
            image=colaborador.image
        )
        avaliado.save()

        serializer = self.get_serializer(avaliado)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    @action(detail=True, methods=['get'])
    def get_avaliado(self, request, pk=None):
        avaliado = self.get_object()
        serializer = self.get_serializer(avaliado)
        return Response(serializer.data)

    
class ColaboradorViewSet(viewsets.ModelViewSet):
    queryset = Colaborador.objects.all()
    serializer_class = ColaboradorSerializer    
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if 'image' in serializer.validated_data:
            image_url = request.build_absolute_uri(instance.image.url)
            return Response({'image_url': image_url, **serializer.data})
        
        return Response(serializer.data)
    
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
            image=colaborador.image
        )
        avaliador.save()

        serializer = self.get_serializer(avaliador)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=['get'], url_path='meus_avaliados')
    def meus_avaliados(self, request):
        try:
            usuario = request.user
            avaliador = Avaliador.objects.get(usuario=usuario)
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
            usuario = request.user
            avaliador = Avaliador.objects.get(usuario=usuario)
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

class AvaliacaoViewSet(viewsets.ModelViewSet):
    queryset = Avaliacao.objects.all()
    serializer_class = AvaliacaoSerializer     

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