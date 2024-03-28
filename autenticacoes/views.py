from django.shortcuts import render, HttpResponse
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth import login as login_django
from django.contrib.auth.decorators import login_required 
from rolepermissions.roles import assign_role



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

def login(request):
    #inca que se o metodo for GET, sem preenceher e enviar o formulário. somente renderiza a pagina
    if request.method == "GET":
        return render(request,'login.html')
    else:
        username = request.POST.get('username')
        senha = request.POST.get('senha')

        user = authenticate(username=username, password=senha)

        if user: #significa não none
            login_django(request, user)
            return HttpResponse('autenticado')
        else:
            return HttpResponse('email ou senha inválidos')

@login_required(login_url='/auth/login/')        
def plataforma(request):
    return HttpResponse('You are in')



