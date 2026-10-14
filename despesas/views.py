from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import Despesa, DocumentoAnexo
from .permissions import AcessoDespesas, eh_gestor
from .serializers import DespesaSerializer, DocumentoAnexoSerializer


def nome_usuario(u):
    """Nome do cadastro de colaboradores (Colaborador.user); sem ele, nome ou login."""
    if not u:
        return ''
    colaborador = getattr(u, 'colaborador', None)
    nome = (getattr(colaborador, 'nome', '') or '').strip()
    return nome or (u.get_full_name() or u.username).strip()


def _salvar_anexos(request, instance):
    """Salva os arquivos enviados como 'novos_anexos' vinculando ao objeto."""
    ct = ContentType.objects.get_for_model(instance)
    for arquivo in request.FILES.getlist('novos_anexos'):
        DocumentoAnexo.objects.create(
            content_type=ct,
            object_id=instance.pk,
            arquivo=arquivo,
            nome_original=arquivo.name,
            created_by=nome_usuario(request.user),
        )


def despesas_visiveis(user):
    """Gestor vê todas; os demais, só as suas (pelo usuário ou, nas antigas, pelo nome)."""
    qs = Despesa.objects.all()
    if eh_gestor(user):
        return qs
    filtro = Q(usuario=user)
    nome = nome_usuario(user)
    if nome:
        filtro |= Q(usuario__isnull=True, colaborador=nome)
    return qs.filter(filtro)


def pode_alterar(user, despesa):
    """Dono mexe enquanto pendente ou recusada; gestor, enquanto não lançada."""
    if eh_gestor(user):
        return despesa.status != Despesa.LANCADA
    return despesa.status in (Despesa.PENDENTE, Despesa.RECUSADA)


# Ação → (status de onde pode sair). `reabrir` volta qualquer uma para pendente.
TRANSICOES = {
    'aprovar': (Despesa.PENDENTE, Despesa.RECUSADA),
    'recusar': (Despesa.PENDENTE, Despesa.APROVADA),
    'lancar': (Despesa.APROVADA,),
    'reabrir': (Despesa.APROVADA, Despesa.RECUSADA, Despesa.LANCADA),
}


def aplicar_acao(despesa, acao, user, motivo=''):
    """Muda o status da despesa; levanta ValidationError se a transição não vale."""
    agora = timezone.now()
    nome = nome_usuario(user)
    if acao == 'reembolsar' or acao == 'desfazer_reembolso':
        if not despesa.reembolsavel:
            raise ValidationError('Só despesa reembolsável pode ser reembolsada.')
        if acao == 'reembolsar':
            if despesa.status not in (Despesa.APROVADA, Despesa.LANCADA):
                raise ValidationError('A despesa precisa estar aprovada para ser reembolsada.')
            despesa.reembolsada, despesa.reembolsada_em, despesa.reembolsada_por = True, timezone.localdate(), nome
        else:
            despesa.reembolsada, despesa.reembolsada_em, despesa.reembolsada_por = False, None, ''
        despesa.save()
        return despesa

    origens = TRANSICOES.get(acao)
    if origens is None:
        raise ValidationError(f'Ação desconhecida: {acao}.')
    if despesa.status not in origens:
        raise ValidationError(f'Não é possível {acao} uma despesa {despesa.get_status_display().lower()}.')

    if acao == 'aprovar':
        despesa.status, despesa.aprovado_por, despesa.aprovado_em, despesa.motivo_recusa = Despesa.APROVADA, nome, agora, ''
    elif acao == 'recusar':
        if not (motivo or '').strip():
            raise ValidationError('Informe o motivo da recusa.')
        despesa.status, despesa.aprovado_por, despesa.aprovado_em = Despesa.RECUSADA, nome, agora
        despesa.motivo_recusa = motivo.strip()
    elif acao == 'lancar':
        despesa.status, despesa.lancada_por, despesa.lancada_em = Despesa.LANCADA, nome, agora
    elif acao == 'reabrir':
        despesa.status = Despesa.PENDENTE
        despesa.aprovado_por, despesa.aprovado_em, despesa.motivo_recusa = '', None, ''
        despesa.lancada_por, despesa.lancada_em = '', None
    despesa.save()
    return despesa


class DocumentoAnexoViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentoAnexoSerializer
    permission_classes = [AcessoDespesas]
    http_method_names = ['get', 'delete', 'head', 'options']

    def get_queryset(self):
        ct = ContentType.objects.get_for_model(Despesa)
        ids = despesas_visiveis(self.request.user).values_list('id', flat=True)
        return DocumentoAnexo.objects.filter(content_type=ct, object_id__in=list(ids))

    def perform_destroy(self, instance):
        despesa = Despesa.objects.get(pk=instance.object_id)
        if not pode_alterar(self.request.user, despesa):
            raise PermissionDenied('Esta despesa não pode mais ser alterada.')
        instance.arquivo.delete(save=False)
        instance.delete()


class DespesaViewSet(viewsets.ModelViewSet):
    serializer_class = DespesaSerializer
    permission_classes = [AcessoDespesas]

    def get_queryset(self):
        return despesas_visiveis(self.request.user).prefetch_related('anexos')

    def perform_create(self, serializer):
        user = self.request.user
        # Quem não é gestor lança sempre em nome próprio.
        colaborador = serializer.validated_data.get('colaborador') if eh_gestor(user) else None
        instance = serializer.save(usuario=user, colaborador=colaborador or nome_usuario(user))
        _salvar_anexos(self.request, instance)

    def perform_update(self, serializer):
        user = self.request.user
        despesa = serializer.instance
        if not pode_alterar(user, despesa):
            raise PermissionDenied('Esta despesa já foi lançada (ou aprovada) e não pode mais ser alterada.')
        extra = {}
        if not eh_gestor(user):
            extra['colaborador'] = despesa.colaborador
            # Corrigir uma recusada é reenviar para aprovação.
            if despesa.status == Despesa.RECUSADA:
                extra['status'] = Despesa.PENDENTE
        instance = serializer.save(**extra)
        _salvar_anexos(self.request, instance)

    def perform_destroy(self, instance):
        if not pode_alterar(self.request.user, instance):
            raise PermissionDenied('Esta despesa não pode mais ser excluída.')
        for anexo in instance.anexos.all():
            anexo.arquivo.delete(save=False)
            anexo.delete()
        instance.delete()

    @action(detail=False, methods=['get'])
    def perfil(self, request):
        """Quem está usando a tela: nome do cadastro e se é gestor do módulo."""
        return Response({'nome': nome_usuario(request.user), 'gestor': eh_gestor(request.user)})

    def _acao(self, request, acao):
        if not eh_gestor(request.user):
            raise PermissionDenied('Só gestores de despesas aprovam, lançam e reembolsam.')
        despesa = aplicar_acao(self.get_object(), acao, request.user, request.data.get('motivo', ''))
        return Response(self.get_serializer(despesa).data)

    @action(detail=True, methods=['post'])
    def aprovar(self, request, pk=None):
        return self._acao(request, 'aprovar')

    @action(detail=True, methods=['post'])
    def recusar(self, request, pk=None):
        return self._acao(request, 'recusar')

    @action(detail=True, methods=['post'])
    def lancar(self, request, pk=None):
        return self._acao(request, 'lancar')

    @action(detail=True, methods=['post'])
    def reabrir(self, request, pk=None):
        return self._acao(request, 'reabrir')

    @action(detail=True, methods=['post'])
    def reembolsar(self, request, pk=None):
        desfazer = str(request.data.get('desfazer', '')).lower() in ('1', 'true', 'sim')
        return self._acao(request, 'desfazer_reembolso' if desfazer else 'reembolsar')

    @action(detail=False, methods=['post'], url_path='acao-lote')
    def acao_lote(self, request):
        """Mesma ação em várias despesas: {ids, acao, motivo}. Devolve as alteradas e as recusadas pelo fluxo."""
        if not eh_gestor(request.user):
            raise PermissionDenied('Só gestores de despesas aprovam, lançam e reembolsam.')
        acao = request.data.get('acao')
        ids = request.data.get('ids') or []
        if acao not in (*TRANSICOES, 'reembolsar', 'desfazer_reembolso'):
            raise ValidationError({'acao': 'Ação inválida.'})
        alteradas, erros = [], []
        for despesa in self.get_queryset().filter(id__in=ids):
            try:
                alteradas.append(aplicar_acao(despesa, acao, request.user, request.data.get('motivo', '')))
            except ValidationError as e:
                erros.append({'id': despesa.id, 'erro': e.detail[0] if isinstance(e.detail, list) else str(e.detail)})
        return Response({'alteradas': self.get_serializer(alteradas, many=True).data, 'erros': erros},
                        status=status.HTTP_200_OK)
