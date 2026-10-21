import io
import json
import uuid as uuid_mod
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, Sum
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import erp, integracao, lubrificacao, regras
from .models import (
    BASE_CODIGO_INTEGRACAO, MARCA_TESTE, PRIVADO, Transferencia, PRODUTOS, Abastecimento, Auditoria, ChaveIntegracao, LoteIntegracao, Lubrificacao, MedicaoTanque, Tanque,
)
from .permissions import (
    AutenticacaoChave, LeituraOuGestao, LimiteIntegracao, LimiteRegistro, PodeGerir, PodeRegistrar, PodeVer, TemChave,
    TemChaveQueConfirma, eh_gestor, ip_do_pedido,
)
from .serializers import (
    AbastecimentoSerializer, TransferenciaSerializer, ChaveSerializer, LoteSerializer, LubrificacaoSerializer, MedicaoSerializer, TanqueSerializer,
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


def _saldo_comboio(t: Tanque, medicao) -> dict:
    """
    Saldo do caminhão, contado no Manager: última régua (ou zero no cadastro) + entradas − entregas.

    Entradas:
    * baixas do SGA no equipamento do comboio (o carregamento que a bomba/CTA lança hoje), no modo
      "já baixado no carregamento";
    * transferências registradas no Manager. A que virou abastecimento do caminhão e já está no SGA
      (o código dela aparece na baixa) não soma de novo.
    """
    desde = medicao.medido_em if medicao else t.criado_em
    base = float(medicao.litros) if medicao else 0.0
    carregado, aviso, codigos_sga = 0.0, None, set()
    if not t.envia_ao_sga and t.equipamento:
        linhas, aviso = _erp_ou_503(erp.carregamentos_comboio, t.equipamento, t.produto,
                                    timezone.make_naive(desde) if timezone.is_aware(desde) else desde)
        for l in linhas or []:
            carregado += l['litros']
            if l.get('iab'):
                codigos_sga.add(l['iab'])
    for tr in (Transferencia.objects.filter(destino=t, transferido_em__gte=desde, situacao=Transferencia.REGISTRADA)
               .select_related('abastecimento')):
        ab = tr.abastecimento
        if ab and (ab.codigo_integracao in codigos_sga or ab.situacao in (Abastecimento.BAIXADO, Abastecimento.CANCELADO)):
            continue  # já está nas baixas do SGA (ou foi cancelada)
        carregado += float(tr.litros)
    entregue = float(Abastecimento.objects.filter(tanque=t, abastecido_em__gte=desde)
                     .exclude(situacao=Abastecimento.CANCELADO).exclude(observacao__startswith=MARCA_TESTE)
                     .aggregate(s=Sum('litros'))['s'] or 0)
    return {'saldo': base + carregado - entregue, 'carregado': carregado, 'entregue': entregue, 'desde': desde, 'aviso': aviso}


def situacao_tanques(serie=None) -> tuple[list[dict], str | None]:
    estoque, erro = _erp_ou_503(erp.estoque_sga)
    pendentes = _pendentes_por_tanque()
    ultimas = {}
    for m in MedicaoTanque.objects.order_by('-medido_em')[:1000]:
        ultimas.setdefault(m.tanque_id, m)   # a primeira de cada tanque é a mais recente
    # Consumo diário de cada produto (para a autonomia em dias).
    consumo_por_produto = {}
    for dia in serie or []:
        for item, litros in dia['por_item'].items():
            consumo_por_produto.setdefault(int(item), []).append({'litros': litros})
    ativos = list(Tanque.objects.filter(ativo=True))
    comboios = {t.id: _saldo_comboio(t, ultimas.get(t.id)) for t in ativos if t.tipo == Tanque.COMBOIO}
    # O SGA tem UM saldo por produto e filial. Dois tanques fixos de S-10 na matriz dividem esse
    # saldo na proporção da capacidade (sem isso cada um mostrava o total e passava de 100%).
    # Comboio com "baixa em cada entrega" ainda está no estoque do SGA: o que está nele sai dos fixos.
    grupos, no_caminhao = {}, {}
    for t in ativos:
        if t.tipo == Tanque.FIXO:
            grupos.setdefault((t.produto, t.filial), []).append(t)
        elif t.envia_ao_sga:
            chave = (t.produto, t.filial)
            no_caminhao[chave] = no_caminhao.get(chave, 0.0) + max(comboios[t.id]['saldo'], 0.0)
    saida = []
    for t in ativos:
        cap = float(t.capacidade_l)
        med = ultimas.get(t.id)
        item = {
            'id': t.id, 'nome': t.nome, 'tipo': t.tipo, 'equipamento': t.equipamento, 'envia_ao_sga': t.envia_ao_sga,
            'produto': t.produto, 'produto_nome': t.produto_nome, 'filial': t.filial,
            'capacidade_l': cap, 'estoque_minimo_l': float(t.estoque_minimo_l),
            'ultima_medicao': {
                'medido_em': med.medido_em, 'litros': float(med.litros),
                'diferenca_l': float(med.litros - med.saldo_sistema_l) if med.saldo_sistema_l is not None else None,
            } if med else None,
        }
        if t.tipo == Tanque.COMBOIO:
            c = comboios[t.id]
            saldo = c['saldo']
            item.update({
                'saldo_l': round(saldo, 2), 'saldo_sga_l': None, 'pendente_l': 0.0, 'custo_medio': None,
                'carregado_l': round(c['carregado'], 2), 'entregue_l': round(c['entregue'], 2), 'saldo_desde': c['desde'],
                'tanques_no_saldo': 1, 'autonomia_dias': None, 'aviso': c['aviso'],
            })
        else:
            sga = (estoque or {}).get((t.produto, t.filial))
            irmaos = grupos[(t.produto, t.filial)]
            cap_grupo = sum(float(x.capacidade_l) for x in irmaos) or cap
            saldo = saldo_grupo = None
            if sga is not None:
                fora = no_caminhao.get((t.produto, t.filial), 0.0)
                saldo_grupo = sga['saldo'] - fora - sum(pendentes.get(x.id, 0.0) for x in irmaos)
                saldo = (sga['saldo'] - fora) * (cap / cap_grupo) - pendentes.get(t.id, 0.0)
            item.update({
                'saldo_l': round(saldo, 2) if saldo is not None else None,
                'saldo_sga_l': sga['saldo'] if sga else None,
                'pendente_l': round(pendentes.get(t.id, 0.0), 2),
                'custo_medio': sga['custo_medio'] if sga else None,
                'tanques_no_saldo': len(irmaos),
                # Autonomia do conjunto: o consumo do SGA é do produto, não do tanque.
                'autonomia_dias': regras.autonomia(saldo_grupo, consumo_por_produto.get(t.produto, [])) if saldo_grupo else None,
            })
        item.update({
            'nivel': round(max(min(saldo / cap, 1.2), -0.2), 4) if saldo is not None and cap else None,
            'abaixo_minimo': saldo is not None and saldo < float(t.estoque_minimo_l),
            # Saldo maior que o tanque: capacidade errada, outro tanque do mesmo combustível não
            # cadastrado ou estoque fora do físico (a régua mostra qual).
            'acima_capacidade': saldo is not None and saldo > cap * 1.02,
        })
        saida.append(item)
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
            # Só o que abastece (veículos e máquinas a diesel), não a planta inteira.
            'equipamentos': [e for e in eqp if e['abastece']], 'funcionarios': fun,
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
        # O mesmo saldo que a tela mostra (dividido entre tanques, comboio contado no Manager).
        situacao, _ = situacao_tanques()
        saldo = next((x['saldo_l'] for x in situacao if x['id'] == tanque.id), None)
        m = serializer.save(usuario=self.request.user,
                            saldo_sistema_l=Decimal(str(round(saldo, 2))) if saldo is not None else None)
        auditar(self.request, 'medicao.criar', m.tanque, litros=float(m.litros))


class TransferenciaViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Tanque → comboio (ou posto externo → comboio). No comboio "já baixado no carregamento" cria o
    abastecimento do caminhão que vai ao SGA. Idempotente pelo uuid (o app manda offline).
    """
    permission_classes = [PodeRegistrar]
    serializer_class = TransferenciaSerializer
    throttle_classes = [LimiteRegistro]
    lookup_field = 'uuid'

    def get_queryset(self):
        qs = Transferencia.objects.select_related('usuario', 'destino', 'origem', 'abastecimento')
        user = self.request.user
        if not eh_gestor(user) and not user.groups.filter(name='CombustivelLeitura').exists() and not user.is_superuser:
            qs = qs.filter(usuario=user)
        if self.action == 'list':
            inicio, fim = _periodo(self.request, dias=60)
            qs = qs.filter(transferido_em__date__gte=inicio, transferido_em__date__lte=fim)
            if self.request.query_params.get('destino'):
                qs = qs.filter(destino_id=self.request.query_params['destino'])
        return qs

    def create(self, request, *args, **kwargs):
        uid = request.data.get('uuid')
        if uid:
            existente = Transferencia.objects.filter(uuid=uid).first()
            if existente:
                if existente.usuario_id != request.user.pk:
                    return Response({'detail': 'Identificador já usado.'}, status=status.HTTP_409_CONFLICT)
                return Response(self.get_serializer(existente).data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def perform_create(self, serializer):
        dados = serializer.validated_data
        destino, origem = dados['destino'], dados.get('origem')
        funcionarios, _ = _erp_ou_503(erp.funcionarios)
        fun = next((f for f in (funcionarios or []) if f['cod'] == dados.get('funcionario')), None)
        tr = serializer.save(usuario=self.request.user, funcionario_nome=(fun or {}).get('nome', ''))
        if origem and not destino.envia_ao_sga and destino.equipamento:
            # Como a bomba faz hoje: o carregamento é um abastecimento do caminhão, baixado no SGA.
            base = {'equipamento': destino.equipamento, 'funcionario': tr.funcionario or 0,
                    'abastecido_em': tr.transferido_em, 'litros': tr.litros,
                    'encerrante_inicial': tr.encerrante_inicial, 'encerrante_final': tr.encerrante_final,
                    'foto_bomba': tr.foto_bomba, 'foto_painel': True, 'horimetro': None, 'km': None}
            eqp, fun2, alertas = _contexto_conferencia(base, origem)
            # O caminhão não precisa de horímetro no carregamento (não é consumo dele).
            alertas = [a for a in alertas if a['codigo'] not in ('SEM_HORIMETRO', 'SEM_KM', 'SEM_FOTO_PAINEL')]
            ab = Abastecimento(
                tanque=origem, abastecido_em=tr.transferido_em, equipamento=destino.equipamento,
                equipamento_nome=(eqp or {}).get('nome', ''), placa=(eqp or {}).get('placa', '')[:10],
                centro_custo=(eqp or {}).get('centro_custo'), funcionario=tr.funcionario or 0,
                funcionario_nome=tr.funcionario_nome, litros=tr.litros, encerrante_inicial=tr.encerrante_inicial,
                encerrante_final=tr.encerrante_final, observacao=f'Transferência para {destino.nome}'[:400],
                alertas=alertas, bloqueado=regras.bloqueia(alertas), registrado_por=self.request.user)
            if tr.foto_bomba:
                ab.foto_bomba.name = tr.foto_bomba.name   # mesmo arquivo, sem copiar
            ab.save()
            tr.abastecimento = ab
            tr.save(update_fields=['abastecimento'])
        auditar(self.request, 'transferencia.criar', tr.uuid, litros=float(tr.litros),
                origem=origem.id if origem else None, destino=destino.id)

    @action(detail=True, methods=['post'], permission_classes=[PodeGerir])
    @transaction.atomic
    def cancelar(self, request, uuid=None):
        tr = self.get_object()
        motivo = (request.data.get('motivo') or '').strip()
        if len(motivo) < 5:
            return Response({'detail': 'Diga o motivo do cancelamento.'}, status=status.HTTP_400_BAD_REQUEST)
        ab = tr.abastecimento
        if ab and ab.situacao == Abastecimento.BAIXADO:
            return Response({'detail': 'Já baixada no SGA: cancele (ou devolva) a baixa lá.'}, status=status.HTTP_400_BAD_REQUEST)
        if ab:
            ab.situacao, ab.motivo_cancelamento = Abastecimento.CANCELADO, f'Transferência cancelada: {motivo}'[:300]
            ab.save(update_fields=['situacao', 'motivo_cancelamento', 'atualizado_em'])
        tr.situacao, tr.motivo_cancelamento = Transferencia.CANCELADA, motivo[:300]
        tr.save(update_fields=['situacao', 'motivo_cancelamento'])
        auditar(request, 'transferencia.cancelar', tr.uuid, motivo=motivo)
        return Response(self.get_serializer(tr).data)

    @action(detail=True, methods=['get'], permission_classes=[PodeVer])
    def foto(self, request, uuid=None):
        tr = self.get_object()
        if not tr.foto_bomba:
            raise Http404
        resp = FileResponse(tr.foto_bomba.open('rb'), content_type='image/jpeg')
        resp['Cache-Control'] = 'private, max-age=3600'
        resp['X-Content-Type-Options'] = 'nosniff'
        return resp


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
        tanque = dados['tanque']
        interno = tanque.tipo == Tanque.COMBOIO and not tanque.envia_ao_sga
        if interno:
            # Diesel já baixado no carregamento do comboio: não vai ao SGA, então o que só
            # importava para a baixa (identificação na integração) deixa de bloquear.
            alertas = [a for a in alertas if a['codigo'] not in ('EQUIPAMENTO_SEM_IDENT', 'FUNCIONARIO_SEM_IDENT', 'DATA_ANTIGA')]
        ab = serializer.save(
            situacao=Abastecimento.INTERNO if interno else Abastecimento.REGISTRADO,
            registrado_por=self.request.user, alertas=alertas, bloqueado=regras.bloqueia(alertas),
            equipamento_nome=(eqp or {}).get('nome', ''), placa=(eqp or {}).get('placa', '')[:10],
            centro_custo=(eqp or {}).get('centro_custo'), funcionario_nome=(fun or {}).get('nome', ''))
        auditar(self.request, 'abastecimento.criar', ab.uuid, litros=float(ab.litros), equipamento=ab.equipamento,
                alertas=[a['codigo'] for a in alertas])

    @transaction.atomic
    def perform_update(self, serializer):
        ab = serializer.instance
        if ab.situacao not in (Abastecimento.REGISTRADO, Abastecimento.CONFERIDO, Abastecimento.INTERNO):
            raise ValidationError('Só dá para corrigir antes do envio ao SGA.')
        antes = {c: str(getattr(ab, c)) for c in ('litros', 'horimetro', 'km', 'equipamento', 'funcionario', 'abastecido_em')}
        dados = {**{c: getattr(ab, c) for c in ('litros', 'horimetro', 'km', 'equipamento', 'funcionario', 'abastecido_em',
                                                'encerrante_inicial', 'encerrante_final')},
                 'foto_bomba': ab.foto_bomba, 'foto_painel': ab.foto_painel, **serializer.validated_data}
        eqp, fun, alertas = _contexto_conferencia(dados, serializer.validated_data.get('tanque', ab.tanque), excluir_id=ab.pk)
        tq = serializer.validated_data.get('tanque', ab.tanque)
        nova = Abastecimento.INTERNO if tq.tipo == Tanque.COMBOIO and not tq.envia_ao_sga else Abastecimento.REGISTRADO
        ab = serializer.save(alertas=alertas, bloqueado=regras.bloqueia(alertas), situacao=nova,
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
            so_teste = Abastecimento.objects.filter(observacao__startswith=MARCA_TESTE, lote__isnull=True).exists()
            return Response({'detail': 'Nada para enviar: os abastecimentos de teste nunca vão para o SGA — use '
                                       '"Baixar exemplo" para ver o arquivo.' if so_teste else
                             'Nada para enviar: sem abastecimento liberado fora de lote.'},
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

    @action(detail=False, methods=['get'])
    def exemplo(self, request):
        """
        O arquivo de verdade, montado só com os abastecimentos de TESTE: mostra o formato (e serve de
        modelo para a Minerion) sem criar lote nem mudar situação. Os registros reais nunca entram aqui.
        """
        formato = (request.query_params.get('formato') or 'CSV').upper()
        if formato not in integracao.GERADORES:
            return Response({'detail': 'Formato inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        lista = list(Abastecimento.objects.select_related('tanque').filter(observacao__startswith=MARCA_TESTE)
                     .exclude(situacao=Abastecimento.CANCELADO).order_by('id')[:100])
        if not lista:
            return Response({'detail': 'Sem abastecimentos de teste: gere com o comando gerar_abastecimentos_teste.'},
                            status=status.HTTP_400_BAD_REQUEST)
        conteudo, ext, tipo, sha = integracao.gerar(formato, [integracao.registro(a) for a in lista])
        nome = f'EXEMPLO-NAO-IMPORTAR_abastecimentos_{timezone.localtime():%Y%m%d_%H%M%S}.{ext}'
        auditar(request, 'lote.exemplo', '', formato=formato, quantidade=len(lista))
        resp = HttpResponse(conteudo, content_type=tipo)
        resp['Content-Disposition'] = f'attachment; filename="{nome}"'
        resp['X-Content-Type-Options'] = 'nosniff'
        return resp

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
        # Entregas do comboio (só no Manager): o diesel foi baixado no caminhão; aqui ele passa
        # para a máquina que de fato consumiu, no ranking e nos centros de custo.
        entregas = [{
            'equipamento': a.equipamento, 'centro_custo': a.centro_custo, 'litros': float(a.litros),
            'comboio': a.tanque.equipamento,
        } for a in Abastecimento.objects.select_related('tanque').filter(
            situacao=Abastecimento.INTERNO, abastecido_em__date__gte=inicio, abastecido_em__date__lte=fim,
            tanque__equipamento__isnull=False).exclude(observacao__startswith=MARCA_TESTE)]
        dados = regras.painel(baixas, entradas, leituras_periodo, equipamentos, entregas_comboio=entregas)
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


# ── Lubrificação ─────────────────────────────────────────────────────────────────
def _leituras_horimetro(desde: date, ate: date) -> list[dict]:
    """Horímetros do SGA (integração) + os digitados no Manager (abastecimento e lubrificação)."""
    sga = [{**l, 'origem': 'SGA'} for l in erp.leituras(desde, ate)]
    manager = [{'equipamento': a['equipamento'], 'data': a['abastecido_em'].isoformat(), 'horimetro': float(a['horimetro']),
                'origem': 'Manager'}
               for a in Abastecimento.objects.filter(abastecido_em__date__gte=desde, horimetro__isnull=False)
               .exclude(situacao=Abastecimento.CANCELADO).exclude(observacao__startswith=MARCA_TESTE)
               .values('equipamento', 'abastecido_em', 'horimetro')]
    campo = [{'equipamento': l['equipamento'], 'data': l['lubrificado_em'].isoformat(), 'horimetro': float(l['horimetro']),
              'origem': 'Lubrificação'}
             for l in Lubrificacao.objects.filter(lubrificado_em__date__gte=desde, horimetro__isnull=False)
             .exclude(situacao=Lubrificacao.CANCELADA).values('equipamento', 'lubrificado_em', 'horimetro')]
    return sga + manager + campo


class LubrificacaoCadastrosView(APIView):
    """Para o registro de campo: todos os equipamentos ativos (britador também lubrifica), lubrificantes e funcionários."""
    permission_classes = [PodeVer]

    def get(self, request):
        try:
            eqp, fun, prods = erp.equipamentos(), erp.funcionarios(), lubrificacao.produtos()
        except erp.ErpIndisponivel as exc:
            return Response({'detail': f'SGA indisponível no momento ({exc}).'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({
            'equipamentos': [{k: e[k] for k in ('cod', 'nome', 'tag', 'descricao', 'abastece', 'usa_km', 'usa_horimetro')} for e in eqp],
            'funcionarios': [{'cod': f['cod'], 'nome': f['nome']} for f in fun],
            'produtos': prods,
            'tipos': [{'value': v, 'label': l} for v, l in Lubrificacao.TIPOS],
            'compartimentos': [{'value': v, 'label': l} for v, l in Lubrificacao.COMPARTIMENTOS],
        })


class LubrificacaoViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Lubrificação de campo, só no Manager. Idempotente pelo uuid (o app manda offline)."""
    permission_classes = [PodeRegistrar]
    serializer_class = LubrificacaoSerializer
    throttle_classes = [LimiteRegistro]
    lookup_field = 'uuid'

    def get_queryset(self):
        qs = Lubrificacao.objects.select_related('usuario')
        user = self.request.user
        if not eh_gestor(user) and not user.groups.filter(name='CombustivelLeitura').exists() and not user.is_superuser:
            qs = qs.filter(usuario=user)
        if self.action == 'list':
            inicio, fim = _periodo(self.request, dias=60)
            qs = qs.filter(lubrificado_em__date__gte=inicio, lubrificado_em__date__lte=fim)
            if self.request.query_params.get('equipamento'):
                qs = qs.filter(equipamento=self.request.query_params['equipamento'])
        return qs

    MAX_ITENS = 20
    CAMPOS_ITEM = ('tipo', 'compartimento', 'produto', 'quantidade')

    def create(self, request, *args, **kwargs):
        if 'itens' in request.data:
            return self._criar_atendimento(request)
        uid = request.data.get('uuid')
        if uid:
            existente = Lubrificacao.objects.filter(uuid=uid).first()
            if existente:
                if existente.usuario_id != request.user.pk:
                    return Response({'detail': 'Identificador já usado.'}, status=status.HTTP_409_CONFLICT)
                return Response(self.get_serializer(existente).data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

    def _criar_atendimento(self, request):
        """
        Vários itens na mesma parada (``itens`` = JSON com tipo, compartimento, produto, quantidade):
        equipamento, horímetro, quem fez, data, foto e observação valem para todos. O ``uuid`` enviado
        é o do atendimento — reenviar devolve os itens já gravados, sem duplicar.
        """
        try:
            itens = json.loads(request.data.get('itens') or '[]')
        except (TypeError, ValueError):
            raise ValidationError({'itens': 'Lista de itens inválida.'})
        if not isinstance(itens, list) or not itens:
            raise ValidationError({'itens': 'Informe ao menos um item.'})
        if len(itens) > self.MAX_ITENS:
            raise ValidationError({'itens': f'No máximo {self.MAX_ITENS} itens por registro.'})
        try:
            atendimento = uuid_mod.UUID(str(request.data.get('uuid') or uuid_mod.uuid4()))
        except ValueError:
            raise ValidationError({'uuid': 'Identificador inválido.'})
        ja = list(Lubrificacao.objects.filter(atendimento=atendimento))
        if ja:
            if any(l.usuario_id != request.user.pk for l in ja):
                return Response({'detail': 'Identificador já usado.'}, status=status.HTTP_409_CONFLICT)
            return Response({'atendimento': str(atendimento), 'itens': self.get_serializer(ja, many=True).data})
        cabecalho = {k: request.data.get(k) for k in ('lubrificado_em', 'equipamento', 'horimetro', 'km', 'funcionario', 'observacao')
                     if request.data.get(k) not in (None, '')}
        validados = []
        for n, item in enumerate(itens, 1):
            if not isinstance(item, dict):
                raise ValidationError({'itens': f'Item {n} inválido.'})
            ser = self.get_serializer(data={**cabecalho, **{k: item.get(k) for k in self.CAMPOS_ITEM if item.get(k) is not None}})
            if not ser.is_valid():
                raise ValidationError({'itens': {f'item {n}': ser.errors}})
            validados.append(ser)
        foto = None
        if request.data.get('foto'):
            ser_foto = self.get_serializer(data={**cabecalho, **{k: itens[0].get(k) for k in self.CAMPOS_ITEM}, 'foto': request.data['foto']})
            ser_foto.is_valid(raise_exception=True)
            foto = ser_foto.validated_data.get('foto')
        with transaction.atomic():
            gravados = []
            for k, ser in enumerate(validados):
                extra = {'atendimento': atendimento}
                if foto is not None and k == 0:
                    extra['foto'] = foto
                gravados.append(self._gravar(ser, **extra))
            if foto is not None and len(gravados) > 1 and gravados[0].foto:
                # Uma foto para o atendimento: os outros itens apontam para o mesmo arquivo.
                Lubrificacao.objects.filter(pk__in=[g.pk for g in gravados[1:]]).update(foto=gravados[0].foto.name)
        return Response({'atendimento': str(atendimento), 'itens': self.get_serializer(gravados, many=True).data},
                        status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        self._gravar(serializer)

    def _gravar(self, serializer, **extra):
        dados = serializer.validated_data
        equipamentos, _ = _erp_ou_503(erp.mapa_equipamentos)
        funcionarios, _ = _erp_ou_503(erp.funcionarios)
        prods, _ = _erp_ou_503(lubrificacao.produtos)
        eqp = (equipamentos or {}).get(int(dados['equipamento']))
        if equipamentos is not None and not eqp:
            raise ValidationError({'equipamento': 'Equipamento não encontrado (ou inativo) no SGA.'})
        prod = next((p for p in (prods or []) if p['cod'] == dados['produto']), None)
        if prods is not None and not prod:
            raise ValidationError({'produto': f"Lubrificante {dados['produto']} não encontrado no SGA."})
        fun = next((f for f in (funcionarios or []) if f['cod'] == dados.get('funcionario')), None)
        lub = serializer.save(usuario=self.request.user, equipamento_nome=(eqp or {}).get('nome', '')[:120],
                              produto_nome=(prod or {}).get('nome', '')[:120], unidade=(prod or {}).get('unidade', '')[:4],
                              funcionario_nome=(fun or {}).get('nome', '')[:120], **extra)
        auditar(self.request, 'lubrificacao.criar', lub.uuid, equipamento=lub.equipamento, produto=lub.produto,
                quantidade=float(lub.quantidade), atendimento=str(lub.atendimento) if lub.atendimento else None)
        return lub

    @action(detail=True, methods=['post'], permission_classes=[PodeGerir])
    def cancelar(self, request, uuid=None):
        lub = self.get_object()
        motivo = (request.data.get('motivo') or '').strip()
        if len(motivo) < 5:
            return Response({'detail': 'Diga o motivo do cancelamento.'}, status=status.HTTP_400_BAD_REQUEST)
        lub.situacao, lub.motivo_cancelamento = Lubrificacao.CANCELADA, motivo[:300]
        lub.save(update_fields=['situacao', 'motivo_cancelamento'])
        auditar(request, 'lubrificacao.cancelar', lub.uuid, motivo=motivo)
        return Response(self.get_serializer(lub).data)

    @action(detail=True, methods=['get'], permission_classes=[PodeVer])
    def foto(self, request, uuid=None):
        lub = self.get_object()
        if not lub.foto:
            raise Http404
        resp = FileResponse(lub.foto.open('rb'), content_type='image/jpeg')
        resp['Cache-Control'] = 'private, max-age=3600'
        resp['X-Content-Type-Options'] = 'nosniff'
        return resp


class LubrificacaoPainelView(APIView):
    """Consumo e custo de óleo e graxa (baixas do SGA) no período, por produto e equipamento."""
    permission_classes = [PodeVer]

    def get(self, request):
        inicio, fim = _periodo(request, dias=90)
        try:
            baixas = lubrificacao.baixas(inicio, fim)
            equipamentos = erp.mapa_equipamentos()
            leituras = _leituras_horimetro(inicio - timedelta(days=15), fim)
            ccs = {b['centro_custo'] for b in baixas if b['centro_custo'] and not b['equipamento']}
            nomes_cc = erp.nomes_centro_custo(sorted(ccs))
            fabrica = lubrificacao.fabrica(lubrificacao.estoque(), lubrificacao.transferencias(inicio, fim))
        except erp.ErpIndisponivel as exc:
            return Response({'detail': f'SGA indisponível no momento ({exc}).'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        campo = list(Lubrificacao.objects.filter(lubrificado_em__date__gte=inicio, lubrificado_em__date__lte=fim)
                     .exclude(situacao=Lubrificacao.CANCELADA).values('tipo', 'quantidade'))
        dados = lubrificacao.painel(baixas, lubrificacao.horas_no_periodo(leituras, inicio, fim), equipamentos, campo)
        fotos = lubrificacao.com_foto()
        for item in dados['produtos'] + fabrica['itens']:
            item['tem_foto'] = item['cod'] in fotos
        # As últimas saídas, uma a uma, para ver o que saiu e para onde.
        dados['ultimas_baixas'] = [{
            'cod': b['cod'], 'data': b['data'], 'item': b['item'], 'nome': b['nome'], 'categoria': b['categoria'],
            'unidade': b['unidade'], 'quantidade': b['quantidade'], 'custo': b['custo'], 'os': b['os'],
            'centro_custo': b['centro_custo'], 'tem_foto': b['item'] in fotos,
            'equipamento': b['equipamento'], 'tag': (equipamentos.get(b['equipamento']) or {}).get('tag', '') if b['equipamento'] else '',
        } for b in sorted(baixas, key=lambda x: x['data'] or '', reverse=True)[:60]]
        for c in dados['centros_custo']:
            c['nome'] = nomes_cc.get(c['centro_custo'], 'Sem centro de custo' if not c['centro_custo'] else f"CC {c['centro_custo']}")
        return Response({'inicio': inicio, 'fim': fim, **dados, 'fabrica': fabrica})


class FotoLubrificanteView(APIView):
    """
    Foto do lubrificante cadastrada no SGA, em miniatura. O SGA guarda BMP de até 4 MB dentro do
    banco: converte uma vez para JPEG de 480 px e guarda no disco privado (refaz depois de 7 dias).
    """
    permission_classes = [PodeVer]
    LADO = 480
    VALIDADE = timedelta(days=7)

    def get(self, request, cod):
        nome = f'sga_itens/{int(cod)}.jpg'
        try:
            novo = not PRIVADO.exists(nome) or timezone.now() - PRIVADO.get_modified_time(nome) > self.VALIDADE
        except OSError:
            novo = True
        if novo:
            try:
                bruta = lubrificacao.foto_bruta(int(cod))
            except erp.ErpIndisponivel:
                bruta = None
                if not PRIVADO.exists(nome):
                    return Response({'detail': 'SGA indisponível.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            if bruta is None and not PRIVADO.exists(nome):
                raise Http404
            if bruta is not None:
                try:
                    img = Image.open(io.BytesIO(bruta))
                    img = ImageOps.exif_transpose(img).convert('RGB')
                    img.thumbnail((self.LADO, self.LADO))
                except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                    raise Http404
                saida = io.BytesIO()
                img.save(saida, 'JPEG', quality=80, optimize=True)
                if PRIVADO.exists(nome):
                    PRIVADO.delete(nome)
                PRIVADO.save(nome, ContentFile(saida.getvalue()))
        resp = FileResponse(PRIVADO.open(nome, 'rb'), content_type='image/jpeg')
        resp['Cache-Control'] = 'private, max-age=86400'
        resp['X-Content-Type-Options'] = 'nosniff'
        return resp


class PreventivasView(APIView):
    """Próximas preventivas por horímetro, recalculadas pelo horímetro dos abastecimentos."""
    permission_classes = [PodeVer]

    def get(self, request):
        hoje = timezone.localdate()
        try:
            pend = lubrificacao.pendentes()
            equipamentos = erp.mapa_equipamentos()
            leituras = _leituras_horimetro(hoje - timedelta(days=120), hoje)
        except erp.ErpIndisponivel as exc:
            return Response({'detail': f'SGA indisponível no momento ({exc}).'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        atuais = lubrificacao.horimetros(leituras)
        planos = lubrificacao.preventivas(pend, atuais, equipamentos, hoje)
        com_plano = {p['equipamento'] for p in planos}
        suspeitas = lubrificacao.leituras_suspeitas(leituras, equipamentos, hoje - timedelta(days=60))
        resumo = {s: sum(1 for p in planos if p['situacao'] == s) for s in ('VENCIDA', 'PROXIMA', 'EM_DIA', 'INDEFINIDA')}
        resumo['fantasmas'] = sum(1 for p in planos if p['vencida_fantasma'])
        resumo['sga_vencidas'] = sum(1 for p in planos if p['sga_vencida'])
        return Response({
            'rodada': pend['rodada'], 'resumo': resumo, 'planos': planos,
            # Primeiro as das máquinas com plano: é ali que a leitura errada estraga a preventiva.
            'leituras_suspeitas': sorted(suspeitas, key=lambda s: s['equipamento'] not in com_plano),
        })
