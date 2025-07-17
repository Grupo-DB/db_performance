from datetime import datetime
from django.shortcuts import render
from rest_framework import viewsets,status
from rest_framework.decorators import action
from .models import Amostra, TipoAmostra, ProdutoAmostra, AmostraImagem
from .serializers import AmostraSerializer, TipoAmostraSerializer, ProdutoAmostraSerializer, AmostraImagemSerializer
from rest_framework.response import Response
import pandas as pd

class TipoAmostraViewSet(viewsets.ModelViewSet):
    queryset = TipoAmostra.objects.all()
    serializer_class = TipoAmostraSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    

class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = ProdutoAmostra.objects.all()
    serializer_class = ProdutoAmostraSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
class AmostraViewSet(viewsets.ModelViewSet):
    queryset = Amostra.objects.all()
    serializer_class = AmostraSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='proximo-sequencial/(?P<material_id>[^/.]+)')
    def proximo_sequencial(self, request, material_id=None):
        ano = datetime.now().year % 100  # dois últimos dígitos do ano
        # Busca todas as amostras do material e ano atual
        amostras = Amostra.objects.filter(material_id=material_id, numero__icontains=str(ano))
        sequenciais = []
        for amostra in amostras:
            try:
                # Exemplo: 'Calc25 08.392' -> pega '08.392', remove ponto, converte para int
                seq_str = amostra.numero.split(' ')[-1].replace('.', '')
                sequenciais.append(int(seq_str))
            except Exception:
                pass
        proximo = max(sequenciais) + 1 if sequenciais else 1
        return Response(proximo)
    
    @action(detail=True, methods=['post'])
    def upload_images(self, request, pk=None):
        amostra = self.get_object()
        images = request.FILES.getlist('images')
        
        if not images:
            return Response(
                {'error': 'Nenhuma imagem foi enviada'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        created_images = []
        for index, image in enumerate(images):
            # Buscar descrição específica para cada imagem
            descricao_key = f'descricao_{index}'
            descricao = request.data.get(descricao_key, '')
            
            amostra_image = AmostraImagem.objects.create(
                amostra=amostra,
                image=image,
                descricao=descricao  # Usar a descrição específica
            )
            created_images.append(AmostraImagemSerializer(amostra_image).data)
        
        return Response({
            'message': f'{len(created_images)} imagens foram enviadas com sucesso',
            'images': created_images
        })
    
    @action(detail=True, methods=['get'])
    def get_images(self, request, pk=None):
        amostra = self.get_object()
        images = amostra.imagens.all()
        # Passa o contexto da request para o serializer
        serializer = AmostraImagemSerializer(images, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['delete'], url_path='delete_image/(?P<image_id>[^/.]+)')
    def delete_image(self, request, pk=None, image_id=None):
        try:
            amostra = self.get_object()
            image = amostra.imagens.get(id=image_id)
            image.delete()
            return Response({'message': 'Imagem deletada com sucesso'})
        except AmostraImagem.DoesNotExist:
            return Response({'error': 'Imagem não encontrada'}, status=status.HTTP_404_NOT_FOUND)
    
class AmostraImagemViewSet(viewsets.ModelViewSet):
    queryset = AmostraImagem.objects.all()
    serializer_class = AmostraImagemSerializer    