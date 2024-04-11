from django.shortcuts import render,HttpResponse

# Create your views here.
def management(request):
    return HttpResponse(request,'ok')

from django.shortcuts import render, HttpResponse
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth import login as login_django
from django.contrib.auth.decorators import login_required 
from rolepermissions.roles import assign_role
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.decorators import api_view,authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status

from .serializers import LoginSerializer, UserSerializer,RegisterCompanySerializer





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




def cadastro(request):
    if request.method == 'GET':
        return render(request, 'cadastro_user.html')
    else:
        username = request.POST.get('username')
        email = request.POST.get('email')
        senha = request.POST.get('senha')
        
        #verifica se já tem esse username cadastrado
        user = User.objects.filter(username=username).first()

        if user:
            return HttpResponse('Username já cadastrado!')
        
        user = User.objects.create_user(username=username, email=email, password=senha)
        user.save()
        
        return HttpResponse('Usuário cadastrado com sucesso!')

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

@login_required(login_url='/auth/login/')        
def plataforma(request):
    return HttpResponse('You are in')



@api_view(['GET'])
#@permission_classes([IsAuthenticated])
def get_users(request):

    if request.method == 'GET':

        users = User.objects.all()                          # Get all objects in User's database (It returns a queryset)

        serializer = UserSerializer(users, many=True)       # Serialize the object data into json (Has a 'many' parameter cause it's a queryset)

        return Response(serializer.data)                    # Return the serialized data
    
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
    
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def registercompany(request):
    if request.method == 'POST':
        serializer = RegisterCompanySerializer(data=request.data)
        if serializer.is_valid():
            empresa = serializer.save()
            return Response({'message': 'Empresa cadastrada com sucesso!', 'empresa_id': empresa.id})
        return Response(status=status.HTTP_400_BAD_REQUEST)