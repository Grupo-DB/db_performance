from rest_framework import viewsets
from gestaoDocumentos.models import Atas, Diretorio, Contrato, DocumentoAnexo, ProcessoExterno, Acao, Alvara, ProcessoInterno, Procuracao, Patrimonial, Seguro, Societario, Veiculo
from gestaoDocumentos.serializers import (
    AtasSerializer,
    DiretorioSerializer,
    ContratoSerializer,
    DocumentoAnexoSerializer,
    ProcessoInternoSerializer,
    AcaoSerializer,
    AlvaraSerializer,
    ProcuracaoSerializer,
    PatrimonialSerializer,
    SeguroSerializer,
    SocietarioSerializer,
    ProcessoExternoSerializer,
    VeiculoSerializer
)


def _salvar_anexos(request, instance):
    """Salva os arquivos enviados como 'novos_anexos' vinculando ao objeto."""
    for arquivo in request.FILES.getlist('novos_anexos'):
        DocumentoAnexo.objects.create(
            content_object=instance,
            arquivo=arquivo,
            nome_original=arquivo.name,
            created_by=request.data.get('created_by') or request.data.get('updated_by', '')
        )


class DiretorioViewSet(viewsets.ModelViewSet):
    queryset = Diretorio.objects.all()
    serializer_class = DiretorioSerializer


class DocumentoAnexoViewSet(viewsets.ModelViewSet):
    queryset = DocumentoAnexo.objects.all()
    serializer_class = DocumentoAnexoSerializer


class AtasViewSet(viewsets.ModelViewSet):
    queryset = Atas.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = AtasSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)


class SocietarioViewSet(viewsets.ModelViewSet):
    queryset = Societario.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = SocietarioSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)


class SeguroViewSet(viewsets.ModelViewSet):
    queryset = Seguro.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = SeguroSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)


class ContratoViewSet(viewsets.ModelViewSet):
    queryset = Contrato.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = ContratoSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)


class ProcessoInternoViewSet(viewsets.ModelViewSet):
    queryset = ProcessoInterno.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = ProcessoInternoSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)


class ProcessoExternoViewSet(viewsets.ModelViewSet):
    queryset = ProcessoExterno.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = ProcessoExternoSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)


class AcaoViewSet(viewsets.ModelViewSet):
    queryset = Acao.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = AcaoSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)


class AlvaraViewSet(viewsets.ModelViewSet):
    queryset = Alvara.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = AlvaraSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)


class ProcuracaoViewSet(viewsets.ModelViewSet):
    queryset = Procuracao.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = ProcuracaoSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)


class VeiculoViewSet(viewsets.ModelViewSet):
    queryset = Veiculo.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = VeiculoSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)


class PatrimonialViewSet(viewsets.ModelViewSet):
    queryset = Patrimonial.objects.select_related('diretorio').prefetch_related('anexos').all()
    serializer_class = PatrimonialSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

