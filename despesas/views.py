from django.shortcuts import render
from rest_framework import viewsets
from django.contrib.contenttypes.models import ContentType
from .models import Despesa, DocumentoAnexo
from .serializers import DespesaSerializer, DocumentoAnexoSerializer

# Create your views here.
def _salvar_anexos(request, instance):
    """Salva os arquivos enviados como 'novos_anexos' vinculando ao objeto."""
    ct = ContentType.objects.get_for_model(instance)
    for arquivo in request.FILES.getlist('novos_anexos'):
        DocumentoAnexo.objects.create(
            content_type=ct,
            object_id=instance.pk,
            arquivo=arquivo,
            nome_original=arquivo.name,
            created_by=request.data.get('created_by') or request.data.get('updated_by', '')
        )

class DocumentoAnexoViewSet(viewsets.ModelViewSet):
    queryset = DocumentoAnexo.objects.all()
    serializer_class = DocumentoAnexoSerializer


class DespesaViewSet(viewsets.ModelViewSet):
    queryset = Despesa.objects.all()
    serializer_class = DespesaSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)