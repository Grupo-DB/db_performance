from django.shortcuts import render,HttpResponse

# Create your views here.
def management(request):
    return HttpResponse(request,'ok')
from django.shortcuts import render, HttpResponse
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
from rest_framework.decorators import api_view,authentication_classes, permission_classes,parser_classes
from rest_framework.response import Response
from rest_framework import status

from .models import Empresa,Area,Cargo,Setor,Colaborador,Filial,TipoContrato,TipoAvaliacao

from .serializers import LoginSerializer, UploadSerializer, UserSerializer,RegisterCompanySerializer,GroupSerializer,AreaSerializer,SetorSerializer,CargoSerializer,ColaboradorSerializer,FilialSerializer,TipoContratoSerializer,TipoAvaliacaoSerializer





# class LoginAPIView(APIView):
#     def get(self,request):
        
#         return render(request,'login.html')




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



#Empresas    
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def registercompany(request):
    if request.method == 'POST':
        serializer = RegisterCompanySerializer(data=request.data)
        if serializer.is_valid():
            empresa = serializer.save()
            return Response({'message': 'Empresa cadastrada com sucesso!', 'empresa_id': empresa.id})
        return Response(status=status.HTTP_400_BAD_REQUEST)
    

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_company(request):
    if request.method == 'GET':

        companys = Empresa.objects.all()                         

        serializer = RegisterCompanySerializer(companys, many=True)       

        return Response(serializer.data)                    
    
    return Response(status=status.HTTP_400_BAD_REQUEST)


#--------------------------------------------------------------------Areas
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_area(request):
    if request.method == 'GET':

        areas = Area.objects.all()                         

        serializer = AreaSerializer(areas, many=True)       

        return Response(serializer.data)                    
    
    return Response(status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def registerarea(request):
    if request.method == 'POST':
        serializer = AreaSerializer(data=request.data)
        if serializer.is_valid():
            area = serializer.save()
            return Response({'message': 'Area cadastrada com sucesso!', 'area_id': area.id})
        return Response(status=status.HTTP_400_BAD_REQUEST)
    
#---------------------------------------------------------------------------------------Setores
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_setor(request):
    if request.method == 'GET':
        setores = Setor.objects.all()                         
        serializer = SetorSerializer(setores, many=True)       
        return Response(serializer.data)                    
    return Response(status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def registersetor(request):
    if request.method == 'POST':
        serializer = SetorSerializer(data=request.data)
        if serializer.is_valid():
            setor = serializer.save()
            return Response({'message': 'Area cadastrada com sucesso!', 'setor_id': setor.id})
        return Response(status=status.HTTP_400_BAD_REQUEST)



#####################################################################################------------Filiais-------------------------################################################
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_filial(request):
    if request.method == 'GET':
        filiais = Filial.objects.all()                         
        serializer = FilialSerializer(filiais, many=True)       
        return Response(serializer.data)                    
    return Response(status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def registerfilial(request):
    if request.method == 'POST':
        serializer = FilialSerializer(data=request.data)
        if serializer.is_valid():
            filial = serializer.save()
            return Response({'message': 'Area cadastrada com sucesso!', 'filial_id': filial.id})
        return Response(status=status.HTTP_400_BAD_REQUEST)

##################################################################################------------------Cargos--------------------------------------#############################

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_cargo(request):
    if request.method == 'GET':
        cargos = Cargo.objects.all()                         
        serializer = CargoSerializer(cargos, many=True)       
        return Response(serializer.data)                    
    return Response(status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def registercargo(request):
    if request.method == 'POST':
        serializer = CargoSerializer(data=request.data)
        if serializer.is_valid():
            cargo = serializer.save()
            return Response({'message': 'Area cadastrada com sucesso!', 'cargo_id': cargo.id})
        return Response(status=status.HTTP_400_BAD_REQUEST)


###############################-------------------------------------------Tipos-de-contratos-------------------##############

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_tipocontrato(request):
    if request.method == 'GET':
        tipocontratos = TipoContrato.objects.all()                         
        serializer = TipoContratoSerializer(tipocontratos, many=True)       
        return Response(serializer.data)                    
    return Response(status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def registertipocontrato(request):
    if request.method == 'POST':
        serializer = TipoContratoSerializer(data=request.data)
        if serializer.is_valid():
            tipocontrato = serializer.save()
            return Response({'message': 'Area cadastrada com sucesso!', 'tipocontrato_id': tipocontrato.id})
        return Response(status=status.HTTP_400_BAD_REQUEST)


#########################################----------------------------Colaboradores---------------------------#####################
@api_view(['GET'])
#@permission_classes([IsAuthenticated])
def get_colaborador(request):
    if request.method == 'GET':
        colaboradores = Colaborador.objects.all()                         
        serializer = ColaboradorSerializer(colaboradores, many=True)       
        return Response(serializer.data)                    
    return Response(status=status.HTTP_400_BAD_REQUEST)
#@permission_classes([IsAuthenticated])
@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def registercolaborador(request):
    if request.method == 'POST':
        serializer = ColaboradorSerializer(data=request.data)
        if serializer.is_valid():
            colaborador = serializer.save()
            return Response({'message': 'Area cadastrada com sucesso!', 'colaborador_id': colaborador.id})
        return Response(status=status.HTTP_400_BAD_REQUEST)
    
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_colaborador(request):
    if request.method == 'GET':
        colaboradores = Colaborador.objects.all()                         
        serializer = ColaboradorSerializer(colaboradores, many=True)       
        return Response(serializer.data)                    
    return Response(status=status.HTTP_400_BAD_REQUEST)    

@api_view(['POST'])
def upload(request):
    if request.method == 'POST':
        serializer = UploadSerializer(data=request.data)
        if serializer.is_valid():
            upload= serializer.save()
            return Response({'message': 'Area cadastrada com sucesso!', 'upload_id': upload.id})
        return Response(status=status.HTTP_400_BAD_REQUEST)







    #get as funções
@api_view(['GET'])
#@permission_classes([IsAuthenticated])
def get_funcao(request):

    if request.method == 'GET':

        funcao = Group.objects.all()                          
        nomes_funcoes = [funcao.name for funcao in funcao]       

        return Response(nomes_funcoes)                    
    
    return Response(status=status.HTTP_400_BAD_REQUEST)

