from datetime import date

from django.db.models import Max
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import VisitaTecnica, VisitaTecnicaImagem
from .serializers import VisitaTecnicaImagemSerializer, VisitaTecnicaSerializer


class VisitaTecnicaViewSet(viewsets.ModelViewSet):
    """
    Visitas técnicas de atendimento externo (aderência à tração em obra).

    `permission_classes` é declarado EXPLICITAMENTE: o
    `DEFAULT_PERMISSION_CLASSES` do projeto está vazio, então um viewset que
    omite este atributo nasce aberto a qualquer requisição sem autenticação.
    """

    queryset = VisitaTecnica.objects.prefetch_related('imagens').all()
    serializer_class = VisitaTecnicaSerializer
    permission_classes = [permissions.IsAuthenticated]
    # MultiPart para o upload de fotos vir no mesmo request da visita.
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_fields = ['codigo', 'cliente', 'data_visita', 'laboratorio']

    @action(detail=False, methods=['get'], url_path='proximo-codigo')
    def proximo_codigo(self, request):
        """
        Sugere o próximo código no formato do laboratório: ANO.SEQUENCIAL
        ('2026.42'). O sequencial reinicia a cada ano.

        É só uma SUGESTÃO para o campo vir preenchido — o código continua editável
        e a unicidade é garantida pelo banco, não por aqui. Duas pessoas abrindo o
        formulário ao mesmo tempo veem o mesmo número, e a segunda a salvar recebe
        erro de duplicidade em vez de sobrescrever.
        """
        ano = date.today().year
        prefixo = f'{ano}.'
        ultimo = 0
        for codigo in (VisitaTecnica.objects
                       .filter(codigo__startswith=prefixo)
                       .values_list('codigo', flat=True)):
            sufixo = str(codigo)[len(prefixo):]
            if sufixo.isdigit():
                ultimo = max(ultimo, int(sufixo))
        return Response({'codigo': f'{prefixo}{ultimo + 1}'})


class VisitaTecnicaImagemViewSet(viewsets.ModelViewSet):
    """Fotos do ensaio, para subir uma a uma (câmera do app) e para excluir."""

    queryset = VisitaTecnicaImagem.objects.all()
    serializer_class = VisitaTecnicaImagemSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_fields = ['visita', 'cp']
