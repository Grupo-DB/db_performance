from rest_framework import viewsets
from gestaoDocumentos.models import Atas, Diretorio, Contrato, ProcessoExterno, Acao, Alvara, ProcessoInterno, Procuracao, Patrimonial, Seguro, Societario, Veiculo
from gestaoDocumentos.serializers import (
    AtasSerializer,
    DiretorioSerializer,
    ContratoSerializer,
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


class DiretorioViewSet(viewsets.ModelViewSet):
    queryset = Diretorio.objects.all()
    serializer_class = DiretorioSerializer

class AtasViewSet(viewsets.ModelViewSet):
    queryset = Atas.objects.select_related('diretorio').all()
    serializer_class = AtasSerializer

class SocietarioViewSet(viewsets.ModelViewSet):
    queryset = Societario.objects.select_related('diretorio').all()
    serializer_class = SocietarioSerializer

class SeguroViewSet(viewsets.ModelViewSet):
    queryset = Seguro.objects.select_related('diretorio').all()
    serializer_class = SeguroSerializer    

class ContratoViewSet(viewsets.ModelViewSet):
    queryset = Contrato.objects.select_related('diretorio').all()
    serializer_class = ContratoSerializer


class ProcessoInternoViewSet(viewsets.ModelViewSet):
    queryset = ProcessoInterno.objects.select_related('diretorio').all()
    serializer_class = ProcessoInternoSerializer

class ProcessoExternoViewSet(viewsets.ModelViewSet):
    queryset = ProcessoExterno.objects.select_related('diretorio').all()
    serializer_class = ProcessoExternoSerializer

class AcaoViewSet(viewsets.ModelViewSet):
    queryset = Acao.objects.select_related('diretorio').all()
    serializer_class = AcaoSerializer


class AlvaraViewSet(viewsets.ModelViewSet):
    queryset = Alvara.objects.select_related('diretorio').all()
    serializer_class = AlvaraSerializer


class ProcuracaoViewSet(viewsets.ModelViewSet):
    queryset = Procuracao.objects.select_related('diretorio').all()
    serializer_class = ProcuracaoSerializer

class VeiculoViewSet(viewsets.ModelViewSet):
    queryset = Veiculo.objects.select_related('diretorio').all()
    serializer_class = VeiculoSerializer

class PatrimonialViewSet(viewsets.ModelViewSet):
    queryset = Patrimonial.objects.select_related('diretorio').all()
    serializer_class = PatrimonialSerializer
