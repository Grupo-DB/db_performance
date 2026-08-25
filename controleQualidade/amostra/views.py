from datetime import datetime
from django.shortcuts import render
from rest_framework import viewsets,status
from rest_framework.decorators import action
from django.http import JsonResponse
from .models import Amostra, TipoAmostra, ProdutoAmostra, AmostraImagem, GarantiaProduto
from .serializers import AmostraSerializer, TipoAmostraSerializer, ProdutoAmostraSerializer, AmostraImagemSerializer, GarantiaProdutoSerializer
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.db import transaction
import pandas as pd

from controleQualidade.periodo_listagem import filtro_periodo, limite_periodo
from .numeracao import proximo_sequencial, reservar_numero

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

    def perform_create(self, serializer):
        """Numera a amostra AQUI, ignorando o número que veio do formulário.

        O `numero` do POST é a prévia que a tela mostrou quando o material foi
        escolhido — pode ter minutos ou dias de idade e já pertencer a outra
        amostra (era a origem das duplicatas de "cal 00.0440", ver
        controleQualidade/amostra/numeracao.py). O número definitivo é reservado
        e gravado na MESMA transação: `reservar_numero` deixa as linhas do
        prefixo travadas até o commit, então dois cadastros simultâneos do mesmo
        material saem com números diferentes em vez de esperarem a sorte.

        Quem chamou recebe o número real no corpo da resposta — é ele que a tela
        deve exibir, não a prévia.
        """
        with transaction.atomic():
            numero = reservar_numero(
                serializer.validated_data.get('material'),
                numero_informado=serializer.validated_data.get('numero'),
            )
            if not numero:
                raise ValidationError(
                    {'numero': 'Informe o material da amostra para o número ser gerado.'})
            serializer.save(numero=numero)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='locais-coleta')
    def locais_coleta(self, request):
        """
        Retorna todos os locais de coleta únicos cadastrados nas amostras.
        """
        locais = Amostra.objects.exclude(
            local_coleta__isnull=True
        ).exclude(
            local_coleta__exact=''
        ).values_list('local_coleta', flat=True).distinct().order_by('local_coleta')
        
        return Response({
            'total': len(locais),
            'locais_coleta': list(locais)
        })
    
    @action(detail=False, methods=['get'])
    def sem_ordem(self, request):
        """
        Amostras que ainda não viraram OS (tela de Amostras).

        Aceita `?dias=60` / `?desde=AAAA-MM-DD` (ver controleQualidade/periodo_listagem):
        a tela abre nos últimos 60 dias e o recorte é feito AQUI, não no navegador.
        Sem parâmetro devolve tudo, que é o "Todas as datas" da tela.

        `select_related`/`prefetch_related` porque o AmostraSerializer expande produto e
        imagens de cada amostra — sem isto era uma consulta por linha.
        """
        amostras = (Amostra.objects
                    .filter(ordem__isnull=True, expressa__isnull=True)
                    .filter(filtro_periodo(limite_periodo(request)))
                    .select_related('produto_amostra')
                    .prefetch_related('imagens')
                    .order_by('-id'))
        serializer = self.get_serializer(amostras, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='calcs')
    def calcs(self, request):
        amostras = Amostra.objects.all()
        serializer = self.get_serializer(amostras, many=True)
        serializer.amostras = serializer.data

        df = pd.DataFrame(serializer.amostras)
        total_por_finalidade = df['finalidade'].value_counts().to_dict()
        total_por_material = df['material'].value_counts().to_dict()
        total_por_fornecedor = df['fornecedor'].value_counts().to_dict()
        total_por_local_coleta = df['local_coleta'].value_counts().to_dict()

        # Cálculos via ORM para evitar dependência de campos não serializados (write_only)
        total_amostras = Amostra.objects.count()
        total_sem_ordem = Amostra.objects.filter(ordem__isnull=True, expressa__isnull=True).count()
        
        # Contagem de expressa e ordem
        total_com_expressa = Amostra.objects.filter(expressa__isnull=False).count()
        total_com_ordem = Amostra.objects.filter(ordem__isnull=False).count()
    
        total_por_tipo = {
            'Expressa': total_com_expressa,
            'Com Plano': total_com_ordem
        }

        response_data = {
            'total_amostras': total_amostras,
            'total_sem_ordem': total_sem_ordem,
            'total_por_finalidade': total_por_finalidade,
            'total_por_material': total_por_material,
            'total_por_fornecedor': total_por_fornecedor,
            'total_por_local_coleta': total_por_local_coleta,
            'total_por_tipo': total_por_tipo
        }
        return JsonResponse(response_data, safe=False)

    @action(detail=False, methods=['get'], url_path='proximo-sequencial-nome/(?P<material_nome>[^/.]+)')
    def proximo_sequencial_nome(self, request, material_nome=None):
        """PRÉVIA do próximo sequencial, para a tela mostrar antes de gravar.

        Não reserva nada: entre esta consulta e o POST outra pessoa pode levar o
        número. Quem define o número da amostra é `perform_create`; aqui é só
        para o campo "Número" do formulário não ficar vazio.

        A leitura (`values_list` + `sequencial_de`) mora em numeracao.py para
        prévia e gravação nunca divergirem.
        """
        try:
            # Decodifica o nome do material (case de caracteres especiais na URL)
            import urllib.parse
            material_nome = urllib.parse.unquote(material_nome)

            return Response(proximo_sequencial(material_nome))

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