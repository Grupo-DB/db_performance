from datetime import datetime
from django.shortcuts import render
from rest_framework import viewsets,status
from rest_framework.decorators import action
from django.http import JsonResponse
from .models import Amostra, TipoAmostra, ProdutoAmostra, AmostraImagem, GarantiaProduto
from .serializers import AmostraSerializer, TipoAmostraSerializer, ProdutoAmostraSerializer, AmostraImagemSerializer, GarantiaProdutoSerializer
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
    

    @action(detail=False, methods=['get'], url_path='tipos-por-material/(?P<material_nome>[^/.]+)')
    def tipos_por_material(self, request, material_nome=None):
        try:
            import urllib.parse
            material_nome = urllib.parse.unquote(material_nome)

            tipos = TipoAmostra.objects.filter(
                material__iexact=material_nome
            )

            serializer = self.get_serializer(tipos, many=True)
            return Response(serializer.data)

        except Exception as e:
            return Response(
                {'error': f'Erro ao filtrar tipos: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    

class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = ProdutoAmostra.objects.all()
    serializer_class = ProdutoAmostraSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    @action(detail=False, methods=['get'], url_path='produtos-por-material/(?P<material_nome>[^/.]+)')
    def por_material(self, request, material_nome=None):
        try:
            # Decodifica o nome do material (caso de caracteres especiais na URL)
            import urllib.parse
            material_nome = urllib.parse.unquote(material_nome)
            
            # Filtra produtos que contêm o nome do material
            produtos = ProdutoAmostra.objects.filter(
                material__iexact=material_nome
            )
            
            serializer = self.get_serializer(produtos, many=True)
            return Response(serializer.data)
            
        except Exception as e:
            return Response(
                {'error': f'Erro ao filtrar produtos: {str(e)}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

class GarantiaProdutoViewSet(viewsets.ModelViewSet):
    queryset = GarantiaProduto.objects.all()
    serializer_class = GarantiaProdutoSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=False, methods=['POST'], url_path='por-produto')
    def por_produto(self, request):
        try:
            produto_id = request.data.get('produto_id')
            if not produto_id:
                return Response(
                    {'error': 'produto_id é obrigatório'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            garantias = GarantiaProduto.objects.filter(produto_id=produto_id)
            serializer = self.get_serializer(garantias, many=True)
            return Response(serializer.data)
            
        except Exception as e:
            return Response(
                {'error': f'Erro ao filtrar garantias: {str(e)}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )        

class AmostraViewSet(viewsets.ModelViewSet):
    queryset = Amostra.objects.all()
    serializer_class = AmostraSerializer
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def sem_ordem(self, request):
        amostras = Amostra.objects.filter(
            ordem__isnull=True,
            expressa__isnull=True
        )
        serializer = self.get_serializer(amostras, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='calcs')
    def calcs(self, request):
        # Cálculos via ORM para evitar dependência de campos não serializados (write_only)
        total_amostras = Amostra.objects.count()
        total_sem_ordem = Amostra.objects.filter(ordem__isnull=True, expressa__isnull=True).count()
        response_data = {
            'total_amostras': total_amostras,
            'total_sem_ordem': total_sem_ordem
        }
        return JsonResponse(response_data, safe=False)

    @action(detail=False, methods=['get'], url_path='proximo-sequencial-nome/(?P<material_nome>[^/.]+)')
    def proximo_sequencial_nome(self, request, material_nome=None):
        try:
            # Decodifica o nome do material (case de caracteres especiais na URL)
            import urllib.parse
            material_nome = urllib.parse.unquote(material_nome)
            
            # Busca todas as amostras que começam com o nome do material
            amostras = Amostra.objects.filter(numero__istartswith=material_nome)
            
            sequenciais = []
            for amostra in amostras:
                try:
                    # Exemplo: 'Calcário 08.392' -> pega '08.392', remove ponto, converte para int
                    numero_parts = amostra.numero.split(' ')
                    if len(numero_parts) >= 2:
                        seq_str = numero_parts[-1].replace('.', '')
                        if seq_str.isdigit():
                            sequenciais.append(int(seq_str))
                except Exception:
                    continue
            
            proximo = max(sequenciais) + 1 if sequenciais else 1
            return Response(proximo)
            
        except Exception as e:
            # Log do erro para debug
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Erro ao buscar próximo sequencial para material '{material_nome}': {str(e)}")
            
            # Retorna um sequencial padrão em caso de erro
            return Response(1)
    
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