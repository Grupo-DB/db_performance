from rest_framework import viewsets
from gestaoDocumentos.models import Diretorio, Contrato, Processo, Acao, Alvara, Procuracao, Patrimonial
from gestaoDocumentos.serializers import (
    DiretorioSerializer,
    ContratoSerializer,
    ProcessoSerializer,
    AcaoSerializer,
    AlvaraSerializer,
    ProcuracaoSerializer,
    PatrimonialSerializer,
)


class DiretorioViewSet(viewsets.ModelViewSet):
    queryset = Diretorio.objects.all()
    serializer_class = DiretorioSerializer


class ContratoViewSet(viewsets.ModelViewSet):
    queryset = Contrato.objects.select_related('diretorio').all()
    serializer_class = ContratoSerializer


class ProcessoViewSet(viewsets.ModelViewSet):
    queryset = Processo.objects.select_related('diretorio').all()
    serializer_class = ProcessoSerializer


class AcaoViewSet(viewsets.ModelViewSet):
    queryset = Acao.objects.select_related('diretorio').all()
    serializer_class = AcaoSerializer


class AlvaraViewSet(viewsets.ModelViewSet):
    queryset = Alvara.objects.select_related('diretorio').all()
    serializer_class = AlvaraSerializer


class ProcuracaoViewSet(viewsets.ModelViewSet):
    queryset = Procuracao.objects.select_related('diretorio').all()
    serializer_class = ProcuracaoSerializer


class PatrimonialViewSet(viewsets.ModelViewSet):
    queryset = Patrimonial.objects.select_related('diretorio').all()
    serializer_class = PatrimonialSerializer
