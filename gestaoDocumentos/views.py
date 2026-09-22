from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.contenttypes.models import ContentType
from gestaoDocumentos.aprovacoes import (
    ErroAprovacao, iniciar_fluxo, pendentes_de, registrar_decisao,
)
from gestaoDocumentos.models import (
    Atas, Diretorio, Contrato, DocumentoAnexo, DocumentoNotificacao, ProcessoExterno,
    Acao, Alvara, ProcessoInterno, Procuracao, Patrimonial, Seguro, Societario, Veiculo,
)
from gestaoDocumentos.serializers import (
    AprovacaoContratoSerializer,
    DocumentoNotificacaoSerializer,
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


def _lista_aprovadores(request):
    """Lê 'aprovadores' aceitando FormData (chave repetida) ou JSON (lista)."""
    dados = request.data
    valores = dados.getlist('aprovadores') if hasattr(dados, 'getlist') else dados.get('aprovadores')
    if valores is None:
        return []
    if isinstance(valores, str):
        valores = valores.split(',')
    elif len(valores) == 1 and isinstance(valores[0], str) and ',' in valores[0]:
        valores = valores[0].split(',')
    return [v for v in valores if str(v).strip()]


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
    queryset = (
        Contrato.objects
        .select_related('diretorio', 'criado_por')
        .prefetch_related('anexos', 'aprovacoes__aprovador')
        .all()
    )
    serializer_class = ContratoSerializer

    def perform_create(self, serializer):
        usuario = self.request.user if self.request.user.is_authenticated else None
        instance = serializer.save(criado_por=usuario)
        _salvar_anexos(self.request, instance)

        aprovadores = _lista_aprovadores(self.request)
        if aprovadores:
            iniciar_fluxo(instance, aprovadores, self.request.data.get('modo_aprovacao'))

    def perform_update(self, serializer):
        instance = serializer.save()
        _salvar_anexos(self.request, instance)

    # ── Fluxo de aprovação ──────────────────────────────────────────────────

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def aprovar(self, request, pk=None):
        return self._decidir(request, aprovado=True)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def reprovar(self, request, pk=None):
        return self._decidir(request, aprovado=False)

    def _decidir(self, request, aprovado):
        contrato = self.get_object()
        try:
            registrar_decisao(contrato, request.user, aprovado, request.data.get('parecer', ''))
        except ErroAprovacao as erro:
            return Response({'detail': str(erro)}, status=status.HTTP_400_BAD_REQUEST)
        contrato.refresh_from_db()
        return Response(self.get_serializer(contrato).data)

    @action(detail=True, methods=['post'], url_path='definir-aprovadores',
            permission_classes=[IsAuthenticated])
    def definir_aprovadores(self, request, pk=None):
        """Abre (ou reabre) o fluxo de um contrato que já está cadastrado."""
        contrato = self.get_object()
        if contrato.situacao_aprovacao == 'PENDENTE':
            return Response(
                {'detail': 'Este contrato já tem um fluxo de aprovação em andamento.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        aprovadores = _lista_aprovadores(request)
        if not aprovadores:
            return Response(
                {'detail': 'Informe ao menos um aprovador.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        contrato.aprovacoes.all().delete()
        iniciar_fluxo(contrato, aprovadores, request.data.get('modo_aprovacao'))
        contrato.refresh_from_db()
        return Response(self.get_serializer(contrato).data)

    @action(detail=False, methods=['get'], url_path='minhas-aprovacoes',
            permission_classes=[IsAuthenticated])
    def minhas_aprovacoes(self, request):
        """Contratos que dependem de uma decisão do usuário logado agora."""
        pendentes = pendentes_de(request.user)
        return Response({
            'total': len(pendentes),
            'aprovacoes': AprovacaoContratoSerializer(pendentes, many=True).data,
            'contratos': self.get_serializer([p.contrato for p in pendentes], many=True).data,
        })


class DocumentoNotificacaoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DocumentoNotificacaoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            DocumentoNotificacao.objects
            .filter(usuario_notificado=self.request.user)
            .select_related('contrato')
        )

    @action(detail=False, methods=['post'], url_path='marcar_como_lido')
    def marcar_como_lido(self, request):
        ids = request.data.get('notificacao_ids', [])
        DocumentoNotificacao.objects.filter(
            id__in=ids, usuario_notificado=request.user,
        ).update(lido=True)
        return Response({'status': 'notificacoes marcadas como lidas'})

    @action(detail=False, methods=['get'], url_path='nao_lidas')
    def nao_lidas(self, request):
        count = DocumentoNotificacao.objects.filter(
            usuario_notificado=request.user, lido=False,
        ).count()
        return Response({'nao_lidas': count})


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

