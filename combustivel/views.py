from datetime import date, datetime, timedelta

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, Sum
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import erp, integracao, regras
from .models import (
    BASE_CODIGO_INTEGRACAO, MARCA_TESTE, PRODUTOS, Abastecimento, Auditoria, ChaveIntegracao, LoteIntegracao, MedicaoTanque, Tanque,
)
from .permissions import (
    AutenticacaoChave, LeituraOuGestao, LimiteIntegracao, LimiteRegistro, PodeGerir, PodeRegistrar, PodeVer, TemChave,
    TemChaveQueConfirma, eh_gestor, ip_do_pedido,
)
from .serializers import (
    AbastecimentoSerializer, ChaveSerializer, LoteSerializer, MedicaoSerializer, TanqueSerializer,
)

# Situações que ainda podem ir para o SGA.
A_ENVIAR = (Abastecimento.REGISTRADO, Abastecimento.CONFERIDO, Abastecimento.EXPORTADO)
SEM_BAIXA = A_ENVIAR


def auditar(request, acao, objeto='', **dados):
    user = request.user if getattr(request.user, 'pk', None) else None
    chave = request.auth if isinstance(request.auth, ChaveIntegracao) else None
    Auditoria.objects.create(usuario=user, chave=chave, acao=acao, objeto=str(objeto)[:80],
                             ip=ip_do_pedido(request), dados=dados)


def _data_param(texto, padrao):
    try:
        return date.fromisoformat(texto) if texto else padrao
    except ValueError:
        return padrao


def _periodo(request, dias=30):
    fim = _data_param(request.query_params.get('fim'), timezone.localdate())
    inicio = _data_param(request.query_params.get('inicio'), fim - timedelta(days=dias - 1))
    if inicio > fim:
        inicio, fim = fim, inicio
    # Teto de 400 dias: o painel lê o SGA ao vivo e não pode varrer anos de baixa.
    return max(inicio, fim - timedelta(days=400)), fim


def _erp_ou_503(func, *args):
    try:
        return func(*args), None
    except erp.ErpIndisponivel as exc:
        return None, f'SGA indisponível no momento ({exc}).'


def _pendentes_por_tanque() -> dict[int, float]:
    """Litros registrados no Manager que o SGA ainda não baixou (saem do saldo do tanque).
    Os de teste (comando gerar_abastecimentos_teste) não contam: não existem de verdade."""
    linhas = (Abastecimento.objects.filter(situacao__in=SEM_BAIXA).exclude(observacao__startswith=MARCA_TESTE)
              .values('tanque').annotate(litros=Sum('litros')))
    return {l['tanque']: float(l['litros'] or 0) for l in linhas}


def situacao_tanques(serie=None) -> tuple[list[dict], str | None]:
    estoque, erro = _erp_ou_503(erp.estoque_sga)
    pendentes = _pendentes_por_tanque()
    ultimas = {}
    for m in MedicaoTanque.objects.filter(medido_em__gte=timezone.now() - timedelta(days=120)).order_by('-medido_em'):
        ultimas.setdefault(m.tanque_id, m)   # a primeira de cada tanque é a mais recente
    # Consumo diário de cada produto (para a autonomia em dias).
    consumo_por_produto = {}
    for dia in serie or []:
        for item, litros in dia['por_item'].items():
            consumo_por_produto.setdefault(int(item), []).append({'litros': litros})
    ativos = list(Tanque.objects.filter(ativo=True))
    # O SGA tem UM saldo por produto e filial. Dois tanques de S-10 na matriz dividem esse saldo
    # na proporção da capacidade (sem isso cada um mostrava o total e passava de 100%).
    grupos = {}
    for t in ativos:
        grupos.setdefault((t.produto, t.filial), []).append(t)
    saida = []
    for t in ativos:
        sga = (estoque or {}).get((t.produto, t.filial))
        irmaos = grupos[(t.produto, t.filial)]
        cap = float(t.capacidade_l)
        cap_grupo = sum(float(x.capacidade_l) for x in irmaos) or cap
        saldo = saldo_grupo = None
        if sga is not None:
            saldo_grupo = sga['saldo'] - sum(pendentes.get(x.id, 0.0) for x in irmaos)
            saldo = sga['saldo'] * (cap / cap_grupo) - pendentes.get(t.id, 0.0)
        med = ultimas.get(t.id)
        saida.append({
            'id': t.id, 'nome': t.nome, 'produto': t.produto, 'produto_nome': t.produto_nome, 'filial': t.filial,
            'capacidade_l': cap, 'estoque_minimo_l': float(t.estoque_minimo_l),
            'saldo_l': round(saldo, 2) if saldo is not None else None,
            'saldo_sga_l': sga['saldo'] if sga else None,
            'pendente_l': round(pendentes.get(t.id, 0.0), 2),
            'custo_medio': sga['custo_medio'] if sga else None,
            'nivel': round(max(min(saldo / cap, 1.2), -0.2), 4) if saldo is not None and cap else None,
            'abaixo_minimo': saldo is not None and saldo < float(t.estoque_minimo_l),
            # Saldo do sistema maior que o tanque: cadastro de capacidade errado, outro tanque do mesmo
            # combustível não cadastrado ou estoque do SGA fora do físico (a régua mostra qual).
            'acima_capacidade': saldo is not None and saldo > cap * 1.02,
            'tanques_no_saldo': len(irmaos),
            # Autonomia do conjunto: o consumo do SGA é do produto, não do tanque.
            'autonomia_dias': regras.autonomia(saldo_grupo, consumo_por_produto.get(t.produto, [])) if saldo_grupo else None,
            'ultima_medicao': {
                'medido_em': med.medido_em, 'litros': float(med.litros),
                'diferenca_l': float(med.litros - med.saldo_sistema_l) if med.saldo_sistema_l is not None else None,
            } if med else None,
        })
    return saida, erro


# ── Cadastros vindos do SGA ─────────────────────────────────────────────────────
class CadastrosView(APIView):
    """Equipamentos e funcionários do SGA para o formulário de registro (cache de 30 min)."""
    permission_classes = [PodeVer]

    def get(self, request):
        eqp, erro1 = _erp_ou_503(erp.equipamentos)
        fun, erro2 = _erp_ou_503(erp.funcionarios)
        if erro1 or erro2:
            return Response({'detail': erro1 or erro2}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({
            'equipamentos': eqp, 'funcionarios': fun,
            'tanques': TanqueSerializer(Tanque.objects.filter(ativo=True), many=True).data,
            'produtos': [{'cod': k, **v} for k, v in PRODUTOS.items()],
        })


class UltimaLeituraView(APIView):
    """Última leitura de horímetro/km do equipamento — o formulário mostra antes de digitar."""
    permission_classes = [PodeVer]

    def get(self, request, equipamento):
        do_erp, erro = _erp_ou_503(erp.ultima_leitura, int(equipamento))
        local = (Abastecimento.objects.filter(equipamento=equipamento).exclude(situacao=Abastecimento.CANCELADO)
                 .order_by('-abastecido_em').values('abastecido_em', 'horimetro', 'km').first())
        return Response({'sga': do_erp, 'manager': local, 'aviso': erro})


# ── Tanques e medições ───────────────────────────────────────────────────────────
class TanqueViewSet(viewsets.ModelViewSet):
    permission_classes = [LeituraOuGestao]
    serializer_class = TanqueSerializer
    queryset = Tanque.objects.all()

    def perform_destroy(self, instance):
        # Tanque com abastecimento não some: vira inativo (o histórico aponta para ele).
        if instance.abastecimentos.exists():
            instance.ativo = False
            instance.save(update_fields=['ativo'])
        else:
            instance.delete()
        auditar(self.request, 'tanque.excluir', instance)

    @action(detail=False, methods=['get'])
    def situacao(self, request):
        dados, erro = situacao_tanques()
        return Response({'tanques': dados, 'aviso': erro})


class MedicaoViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [PodeRegistrar]
    serializer_class = MedicaoSerializer

    def get_queryset(self):
        qs = MedicaoTanque.objects.select_related('usuario')
        if self.request.query_params.get('tanque'):
            qs = qs.filter(tanque_id=self.request.query_params['tanque'])
        return qs[:200]

    def perform_create(self, serializer):
        tanque = serializer.validated_data['tanque']
        estoque, _ = _erp_ou_503(erp.estoque_sga)
        sga = (estoque or {}).get((tanque.produto, tanque.filial))
        saldo = sga['saldo'] - _pendentes_por_tanque().get(tanque.id, 0.0) if sga else None
        m = serializer.save(usuario=self.request.user, saldo_sistema_l=round(saldo, 2) if saldo is not None else None)
        auditar(self.request, 'medicao.criar', m.tanque, litros=float(m.litros))


# ── Abastecimentos ───────────────────────────────────────────────────────────────
def _contexto_conferencia(dados, tanque, excluir_id=None):
    equipamentos, _ = _erp_ou_503(erp.mapa_equipamentos)
    funcionarios, _ = _erp_ou_503(erp.funcionarios)
    eqp = (equipamentos or {}).get(int(dados['equipamento']))
    fun = next((f for f in (funcionarios or []) if f['cod'] == int(dados['funcionario'])), None)
    ultima, _ = _erp_ou_503(erp.ultima_leitura, int(dados['equipamento']))
    recentes = (Abastecimento.objects.filter(equipamento=dados['equipamento'],
                                             abastecido_em__gte=dados['abastecido_em'] - timedelta(days=60))
                .exclude(situacao=Abastecimento.CANCELADO).exclude(pk=excluir_id)
                .values('abastecido_em', 'horimetro', 'km'))
    saldos, _ = situacao_tanques()
    saldo = next((t['saldo_l'] for t in saldos if t['id'] == tanque.id), None)
    alertas = regras.conferir(dados, equipamento=eqp, funcionario=fun, ultima_leitura=ultima,
                              saldo_tanque=saldo, recentes=list(recentes))
    # Sem SGA no ar não dá para conferir a identificação: avisa e segura o envio.
    if equipamentos is None or funcionarios is None:
        alertas = [a for a in alertas if not a['codigo'].endswith('DESCONHECIDO')]
        alertas.append(regras._alerta('SGA_FORA', regras.BLOQUEIO,
                                      'SGA fora do ar no registro — confira antes de enviar.'))
    return eqp, fun, alertas


class AbastecimentoViewSet(viewsets.ModelViewSet):
    serializer_class = AbastecimentoSerializer
    permission_classes = [PodeRegistrar]
    throttle_classes = [LimiteRegistro]
    lookup_field = 'uuid'
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        qs = Abastecimento.objects.select_related('tanque', 'registrado_por')
        user = self.request.user
        # Operador vê só o que registrou; gestão e leitura veem tudo.
        if not eh_gestor(user) and not user.groups.filter(name='CombustivelLeitura').exists() and not user.is_superuser:
            qs = qs.filter(registrado_por=user)
        p = self.request.query_params
        if self.action == 'list':
            inicio, fim = _periodo(self.request, dias=60)
            qs = qs.filter(abastecido_em__date__gte=inicio, abastecido_em__date__lte=fim)
            if p.get('situacao'):
                qs = qs.filter(situacao__in=p['situacao'].split(','))
            if p.get('equipamento'):
                qs = qs.filter(equipamento=p['equipamento'])
            if p.get('tanque'):
                qs = qs.filter(tanque_id=p['tanque'])
            if p.get('bloqueado') in ('1', 'true'):
                qs = qs.filter(bloqueado=True)
        return qs

    def create(self, request, *args, **kwargs):
        # Idempotente: o aparelho manda o mesmo uuid ao reenviar; não nasce um segundo registro.
        uid = request.data.get('uuid')
        if uid:
            existente = Abastecimento.objects.filter(uuid=uid).first()
            if existente:
                if existente.registrado_por_id != request.user.pk:
                    return Response({'detail': 'Identificador já usado.'}, status=status.HTTP_409_CONFLICT)
                return Response(self.get_serializer(existente).data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def perform_create(self, serializer):
        dados = dict(serializer.validated_data)
        eqp, fun, alertas = _contexto_conferencia(dados, dados['tanque'])
        ab = serializer.save(
            registrado_por=self.request.user, alertas=alertas, bloqueado=regras.bloqueia(alertas),
            equipamento_nome=(eqp or {}).get('nome', ''), placa=(eqp or {}).get('placa', '')[:10],
            centro_custo=(eqp or {}).get('centro_custo'), funcionario_nome=(fun or {}).get('nome', ''))
        auditar(self.request, 'abastecimento.criar', ab.uuid, litros=float(ab.litros), equipamento=ab.equipamento,
                alertas=[a['codigo'] for a in alertas])

    @transaction.atomic
    def perform_update(self, serializer):
        ab = serializer.instance
        if ab.situacao not in (Abastecimento.REGISTRADO, Abastecimento.CONFERIDO):
            raise ValidationError('Só dá para corrigir antes do envio ao SGA.')
        antes = {c: str(getattr(ab, c)) for c in ('litros', 'horimetro', 'km', 'equipamento', 'funcionario', 'abastecido_em')}
        dados = {**{c: getattr(ab, c) for c in ('litros', 'horimetro', 'km', 'equipamento', 'funcionario', 'abastecido_em',
                                                'encerrante_inicial', 'encerrante_final')},
                 'foto_bomba': ab.foto_bomba, 'foto_painel': ab.foto_painel, **serializer.validated_data}
        eqp, fun, alertas = _contexto_conferencia(dados, serializer.validated_data.get('tanque', ab.tanque), excluir_id=ab.pk)
        ab = serializer.save(alertas=alertas, bloqueado=regras.bloqueia(alertas), situacao=Abastecimento.REGISTRADO,
                             equipamento_nome=(eqp or {}).get('nome', ab.equipamento_nome),
                             placa=(eqp or {}).get('placa', ab.placa)[:10],
                             centro_custo=(eqp or {}).get('centro_custo', ab.centro_custo),
                             funcionario_nome=(fun or {}).get('nome', ab.funcionario_nome))
        auditar(self.request, 'abastecimento.corrigir', ab.uuid, antes=antes)

    @action(detail=True, methods=['post'], permission_classes=[PodeGerir])
    def conferir(self, request, uuid=None):
        ab = self.get_object()
        if ab.bloqueado:
            return Response({'detail': 'Há alertas que bloqueiam o envio: corrija antes de conferir.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if ab.situacao != Abastecimento.REGISTRADO:
            return Response({'detail': 'Só abastecimento registrado pode ser conferido.'}, status=status.HTTP_400_BAD_REQUEST)
        ab.situacao, ab.conferido_por = Abastecimento.CONFERIDO, request.user
        ab.save(update_fields=['situacao', 'conferido_por', 'atualizado_em'])
        auditar(request, 'abastecimento.conferir', ab.uuid)
        return Response(self.get_serializer(ab).data)

    @action(detail=True, methods=['post'], permission_classes=[PodeGerir])
    def cancelar(self, request, uuid=None):
        ab = self.get_object()
        motivo = (request.data.get('motivo') or '').strip()
        if len(motivo) < 5:
            return Response({'detail': 'Diga o motivo do cancelamento.'}, status=status.HTTP_400_BAD_REQUEST)
        if ab.situacao == Abastecimento.BAIXADO:
            return Response({'detail': 'Já baixado no SGA: cancele (ou devolva) a baixa lá.'},
                            status=status.HTTP_400_BAD_REQUEST)
        ab.situacao, ab.motivo_cancelamento = Abastecimento.CANCELADO, motivo[:300]
        ab.save(update_fields=['situacao', 'motivo_cancelamento', 'atualizado_em'])
        auditar(request, 'abastecimento.cancelar', ab.uuid, motivo=motivo)
        return Response(self.get_serializer(ab).data)

    @action(detail=True, methods=['get'], url_path=r'foto/(?P<qual>bomba|painel)', permission_classes=[PodeVer])
    def foto(self, request, uuid=None, qual=None):
        ab = self.get_object()
        arquivo = ab.foto_bomba if qual == 'bomba' else ab.foto_painel
        if not arquivo:
            raise Http404
        resp = FileResponse(arquivo.open('rb'), content_type='image/jpeg')
        resp['Cache-Control'] = 'private, max-age=3600'
        resp['X-Content-Type-Options'] = 'nosniff'
        return resp

    @action(detail=False, methods=['post'], permission_classes=[PodeGerir])
    def conciliar(self, request):
        return Response(conciliar(request))


def conciliar(request=None) -> dict:
    """Marca como BAIXADO o que o SGA já baixou (procura o código em BAIXAESTOQUE.BESTIAB)."""
    pendentes = list(Abastecimento.objects.filter(situacao__in=SEM_BAIXA).only('id', 'abastecido_em'))
    if not pendentes:
        return {'baixados': 0, 'pendentes': 0}
    desde = min(p.abastecido_em for p in pendentes) - timedelta(days=2)
    achados, erro = _erp_ou_503(erp.baixas_dos_codigos, [p.id + BASE_CODIGO_INTEGRACAO for p in pendentes],
                                timezone.make_naive(desde) if timezone.is_aware(desde) else desde)
    if erro:
        return {'baixados': 0, 'pendentes': len(pendentes), 'aviso': erro}
    baixados = 0
    for p in pendentes:
        info = achados.get(p.id + BASE_CODIGO_INTEGRACAO)
        if info:
            Abastecimento.objects.filter(pk=p.pk).update(situacao=Abastecimento.BAIXADO, baixa_sga=info['baixa'],
                                                         baixado_em=timezone.now(), erro_sga='')
            baixados += 1
    if request is not None and baixados:
        auditar(request, 'conciliar', '', baixados=baixados)
    return {'baixados': baixados, 'pendentes': len(pendentes) - baixados}


# ── Arquivos de integração ──────────────────────────────────────────────────────
class LoteViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [PodeGerir]
    serializer_class = LoteSerializer
    queryset = LoteIntegracao.objects.select_related('criado_por')

    @transaction.atomic
    def create(self, request):
        formato = (request.data.get('formato') or 'CSV').upper()
        if formato not in integracao.GERADORES:
            return Response({'detail': 'Formato inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        qs = (Abastecimento.objects.select_for_update().select_related('tanque')
              .filter(situacao__in=(Abastecimento.REGISTRADO, Abastecimento.CONFERIDO), bloqueado=False, lote__isnull=True))
        if request.data.get('somente_conferidos'):
            qs = qs.filter(situacao=Abastecimento.CONFERIDO)
        uuids = request.data.get('abastecimentos')
        if uuids:
            qs = qs.filter(uuid__in=uuids)
        lista = list(qs.order_by('id'))
        if not lista:
            return Response({'detail': 'Nada para enviar: sem abastecimento liberado fora de lote.'},
                            status=status.HTTP_400_BAD_REQUEST)
        registros = [integracao.registro(a) for a in lista]
        conteudo, ext, _, sha = integracao.gerar(formato, registros)
        nome = f'abastecimentos_{timezone.localtime():%Y%m%d_%H%M%S}.{ext}'
        lote = LoteIntegracao(formato=formato, nome_arquivo=nome, sha256=sha, quantidade=len(lista),
                              litros=sum(a.litros for a in lista), criado_por=request.user)
        lote.arquivo.save(nome, ContentFile(conteudo), save=False)
        lote.save()
        agora = timezone.now()
        Abastecimento.objects.filter(pk__in=[a.pk for a in lista]).update(
            lote=lote, situacao=Abastecimento.EXPORTADO, enviado_sga_em=agora)
        auditar(request, 'lote.gerar', lote.pk, formato=formato, quantidade=len(lista), sha256=sha)
        return Response(LoteSerializer(lote).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def arquivo(self, request, pk=None):
        lote = self.get_object()
        _, _, tipo = integracao.GERADORES[lote.formato]
        auditar(request, 'lote.baixar', lote.pk)
        resp = FileResponse(lote.arquivo.open('rb'), content_type=tipo, as_attachment=True, filename=lote.nome_arquivo)
        resp['X-Content-Type-Options'] = 'nosniff'
        resp['X-Checksum-SHA256'] = lote.sha256
        return resp

    @action(detail=True, methods=['post'])
    def importado(self, request, pk=None):
        lote = self.get_object()
        if lote.situacao != LoteIntegracao.GERADO:
            return Response({'detail': 'Lote já fechado.'}, status=status.HTTP_400_BAD_REQUEST)
        lote.situacao = LoteIntegracao.IMPORTADO
        lote.save(update_fields=['situacao', 'atualizado_em'])
        auditar(request, 'lote.importado', lote.pk)
        return Response(LoteSerializer(lote).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancelar(self, request, pk=None):
        """Devolve os abastecimentos ao estado anterior (o arquivo não foi usado)."""
        lote = self.get_object()
        if lote.situacao != LoteIntegracao.GERADO:
            return Response({'detail': 'Só lote ainda não importado pode ser cancelado.'}, status=status.HTTP_400_BAD_REQUEST)
        lote.abastecimentos.filter(situacao=Abastecimento.EXPORTADO).update(
            situacao=Abastecimento.REGISTRADO, lote=None, enviado_sga_em=None)
        lote.situacao = LoteIntegracao.CANCELADO
        lote.save(update_fields=['situacao', 'atualizado_em'])
        auditar(request, 'lote.cancelar', lote.pk)
        return Response(LoteSerializer(lote).data)


class ChaveViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [PodeGerir]
    serializer_class = ChaveSerializer
    queryset = ChaveIntegracao.objects.select_related('criado_por')

    def create(self, request):
        ser = ChaveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        chave, texto = ChaveIntegracao.gerar(
            nome=ser.validated_data['nome'], pode_confirmar=ser.validated_data.get('pode_confirmar', True),
            ips_permitidos=ser.validated_data.get('ips_permitidos', ''), expira_em=ser.validated_data.get('expira_em'),
            criado_por=request.user)
        auditar(request, 'chave.criar', chave.prefixo, nome=chave.nome)
        # O segredo aparece só nesta resposta; no banco fica o hash.
        return Response({**ChaveSerializer(chave).data, 'segredo': texto}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def revogar(self, request, pk=None):
        chave = self.get_object()
        chave.ativa, chave.revogada_em = False, timezone.now()
        chave.save(update_fields=['ativa', 'revogada_em'])
        auditar(request, 'chave.revogar', chave.prefixo)
        return Response(ChaveSerializer(chave).data)


class DocumentacaoView(APIView):
    permission_classes = [PodeVer]

    def get(self, request):
        return Response(integracao.documentacao())


class AuditoriaView(APIView):
    permission_classes = [PodeGerir]

    def get(self, request):
        linhas = Auditoria.objects.select_related('usuario', 'chave')[:300]
        return Response([{
            'quando': a.quando, 'acao': a.acao, 'objeto': a.objeto, 'ip': a.ip, 'dados': a.dados,
            'quem': (a.usuario.get_full_name() or a.usuario.username) if a.usuario else (
                f'chave {a.chave.prefixo} ({a.chave.nome})' if a.chave else '—'),
        } for a in linhas])


# ── API para o SGA buscar (autenticação por chave, sem usuário) ──────────────────
class IntegracaoAbastecimentosView(APIView):
    authentication_classes = [AutenticacaoChave]
    permission_classes = [TemChave]
    throttle_classes = [LimiteIntegracao]

    def get(self, request):
        try:
            depois_de = int(request.query_params.get('depois_de') or 0)
            limite = min(max(int(request.query_params.get('limite') or 500), 1), 1000)
        except ValueError:
            return Response({'detail': 'Parâmetros inválidos.'}, status=status.HTTP_400_BAD_REQUEST)
        a_partir = max(depois_de - BASE_CODIGO_INTEGRACAO, 0)
        qs = (Abastecimento.objects.select_related('tanque')
              .filter(situacao__in=A_ENVIAR, bloqueado=False, pk__gt=a_partir).order_by('pk')[:limite])
        lista = list(qs)
        agora = timezone.now()
        Abastecimento.objects.filter(pk__in=[a.pk for a in lista], enviado_sga_em__isnull=True).update(enviado_sga_em=agora)
        auditar(request, 'api.buscar', '', depois_de=depois_de, entregues=len(lista))
        return Response({
            'layout': integracao.VERSAO_LAYOUT, 'quantidade': len(lista),
            'ultimo_codigo': lista[-1].codigo_integracao if lista else depois_de,
            'abastecimentos': [integracao.registro(a) for a in lista],
        })


class IntegracaoConfirmarView(APIView):
    authentication_classes = [AutenticacaoChave]
    permission_classes = [TemChaveQueConfirma]
    throttle_classes = [LimiteIntegracao]

    @transaction.atomic
    def post(self, request):
        itens = request.data if isinstance(request.data, list) else request.data.get('itens')
        if not isinstance(itens, list) or len(itens) > 1000:
            return Response({'detail': 'Envie uma lista de até 1000 itens.'}, status=status.HTTP_400_BAD_REQUEST)
        resultado = {'baixados': 0, 'com_erro': 0, 'ignorados': 0}
        for item in itens:
            try:
                pk = int(item.get('codigo')) - BASE_CODIGO_INTEGRACAO
            except (TypeError, ValueError, AttributeError):
                resultado['ignorados'] += 1
                continue
            ab = Abastecimento.objects.select_for_update().filter(pk=pk, situacao__in=A_ENVIAR).first()
            if not ab:
                resultado['ignorados'] += 1
                continue
            if item.get('baixa'):
                try:
                    ab.baixa_sga = int(item['baixa'])
                except (TypeError, ValueError):
                    resultado['ignorados'] += 1
                    continue
                ab.situacao, ab.baixado_em, ab.erro_sga = Abastecimento.BAIXADO, timezone.now(), ''
                resultado['baixados'] += 1
            else:
                ab.erro_sga = str(item.get('erro') or 'Recusado pelo SGA')[:300]
                resultado['com_erro'] += 1
            ab.save(update_fields=['baixa_sga', 'situacao', 'baixado_em', 'erro_sga', 'atualizado_em'])
        auditar(request, 'api.confirmar', '', **resultado)
        return Response(resultado)


# ── Painel ───────────────────────────────────────────────────────────────────────
class PainelView(APIView):
    permission_classes = [PodeVer]

    def get(self, request):
        inicio, fim = _periodo(request, dias=30)
        try:
            baixas = erp.baixas(inicio, fim)
            entradas = erp.entradas(inicio, fim)
            # Leituras de 60 dias antes também: o primeiro abastecimento do período precisa
            # do anterior para virar litros por hora.
            leituras = erp.leituras(inicio - timedelta(days=60), fim)
            equipamentos = erp.mapa_equipamentos()
            situacao = erp.situacao_integracao()
        except erp.ErpIndisponivel as exc:
            return Response({'detail': f'SGA indisponível no momento ({exc}).'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        leituras_periodo = [l for l in leituras if l['data'] and l['data'][:10] >= inicio.isoformat()]
        dados = regras.painel(baixas, entradas, leituras_periodo, equipamentos)
        anomalias = [a for a in regras.anomalias(leituras, equipamentos) if a['data'][:10] >= inicio.isoformat()]
        tanques, _ = situacao_tanques(dados['serie'])

        nomes = {k: v['nome'] for k, v in equipamentos.items()}
        for t in situacao['travados']:
            t['nome'] = nomes.get(t['equipamento'], '')
        for d in situacao['duplicadas']:
            d['nome'] = nomes.get(d['equipamento'], '')

        ultima = situacao['ultima_importacao']
        horas_parada = None
        if ultima:
            horas_parada = round((datetime.now() - datetime.fromisoformat(ultima)).total_seconds() / 3600, 1)

        locais = Abastecimento.objects.exclude(situacao=Abastecimento.CANCELADO).exclude(observacao__startswith=MARCA_TESTE)
        manager = {
            'registrados_periodo': locais.filter(abastecido_em__date__gte=inicio, abastecido_em__date__lte=fim).count(),
            'aguardando_sga': locais.filter(situacao__in=SEM_BAIXA).count(),
            'bloqueados': locais.filter(situacao__in=SEM_BAIXA, bloqueado=True).count(),
        }
        return Response({
            'inicio': inicio, 'fim': fim, **dados, 'anomalias': anomalias[:50], 'tanques': tanques,
            'integracao': {**situacao, 'horas_sem_importar': horas_parada, 'manager': manager},
        })
