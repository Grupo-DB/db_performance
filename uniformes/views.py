from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from avaliacoes.management.models import Colaborador

from .models import TAMANHOS, Campanha, ItemPedido, Peca, Pedido
from .permissions import IsRHUniformes
from .regras import (
    REGRAS_PADRAO, alertas, criar_catalogo, ler_celula, ler_entrega, ler_ziper, peca_do_pedido, sem_acento, valor_pedido,
)
from .serializers import CampanhaSerializer, ItemPedidoSerializer, PecaSerializer, PedidoSerializer


def _pedidos(campanha_id):
    return (Pedido.objects.filter(campanha_id=campanha_id)
            .select_related('campanha', 'colaborador__cargo')
            .prefetch_related(Prefetch('itens', queryset=ItemPedido.objects.select_related('peca'))))


class CampanhaViewSet(viewsets.ModelViewSet):
    permission_classes = [IsRHUniformes]
    serializer_class = CampanhaSerializer
    queryset = Campanha.objects.prefetch_related('pecas')

    def perform_create(self, serializer):
        """Campanha nova nasce com as peças, preços e regras do Inverno/2026 — é só ajustar."""
        campanha = serializer.save(regras=serializer.validated_data.get('regras') or REGRAS_PADRAO)
        criar_catalogo(campanha)

    @action(detail=True, methods=['get'])
    def resumo(self, request, pk=None):
        """Pedido ao fornecedor (peça × tamanho), totais e entregas pendentes."""
        campanha = self.get_object()
        pedidos = list(_pedidos(campanha.id))
        grade = defaultdict(lambda: defaultdict(int))
        pendentes = defaultdict(int)
        for pedido in pedidos:
            for item in pedido.itens.all():
                grade[str(item.peca)][item.tamanho] += item.quantidade
                if not item.entregue:
                    pendentes[str(item.peca)] += item.quantidade
        ordem = {str(p): p.ordem for p in campanha.pecas.all()}
        compras = [p for p in pedidos if p.modalidade == Pedido.COMPRA]
        return Response({
            'tamanhos': TAMANHOS,
            'grade': [
                {'peca': peca, 'por_tamanho': dict(tam), 'total': sum(tam.values()), 'pendentes': pendentes[peca]}
                for peca, tam in sorted(grade.items(), key=lambda kv: ordem.get(kv[0], 99))
            ],
            'pedidos': len(pedidos),
            'ganha': len(pedidos) - len(compras),
            'compra': len(compras),
            'valor_compras': sum((valor_pedido(p) for p in compras), Decimal('0')),
            'itens_pendentes': sum(pendentes.values()),
            'com_alerta': sum(1 for p in pedidos if alertas(p)),
        })

    @action(detail=True, methods=['post'])
    def importar(self, request, pk=None):
        """
        Linhas das abas de pedidos, lidas no navegador: ``{aba, nome, cpf, setor, jaqueta,
        sueter, camisa, soft, ziper, entrega, entrega_jaqueta}``; a aba diz gênero
        (FEMININOS/MASCULINOS) e modalidade (GANHA/COMPRA). Reimportar atualiza.
        """
        campanha = self.get_object()
        linhas = request.data.get('linhas') or []
        por_nome = {sem_acento(c.nome): c for c in Colaborador.objects.select_related('cargo', 'setor')}
        criados = atualizados = 0
        sem_peca = set()
        with transaction.atomic():
            for linha in linhas:
                nome = ' '.join(str(linha.get('nome') or '').split())
                aba = sem_acento(linha.get('aba'))
                if not nome or ('FEMININ' not in aba and 'MASCULIN' not in aba):
                    continue
                genero = 'F' if 'FEMININ' in aba else 'M'
                modalidade = Pedido.GANHA if 'GANHA' in aba else Pedido.COMPRA
                colaborador = por_nome.get(sem_acento(nome))
                pedido = Pedido.objects.filter(campanha=campanha, modalidade=modalidade, nome__iexact=nome).first()
                dados = {
                    'cpf': str(linha.get('cpf') or '').strip(), 'setor': str(linha.get('setor') or '').strip(),
                    'genero': genero, 'colaborador': colaborador,
                    'cargo': colaborador.cargo.nome if colaborador and colaborador.cargo_id else '',
                }
                if pedido:
                    for k, v in dados.items():
                        setattr(pedido, k, v)
                    pedido.save()
                    pedido.itens.all().delete()
                    atualizados += 1
                else:
                    pedido = Pedido.objects.create(campanha=campanha, nome=nome, modalidade=modalidade, **dados)
                    criados += 1

                entregue, data, obs = ler_entrega(linha.get('entrega'))
                jaq_entregue, jaq_data, jaq_obs = ler_entrega(linha.get('entrega_jaqueta'))
                for campo, nome_peca in (('jaqueta', 'Jaqueta'), ('sueter', 'Suéter'), ('camisa', 'Camisa'), ('soft', 'Soft')):
                    celula = ler_celula(linha.get(campo))
                    if not celula:
                        continue
                    peca = peca_do_pedido(campanha, nome_peca, genero)
                    if not peca:
                        sem_peca.add(nome_peca)
                        continue
                    if campo == 'jaqueta':
                        # A jaqueta chegou depois: vale a coluna dela; sem ela, a entrega geral
                        # só conta se for nota ("Jak levou", "DEMITIDO"), não data das outras peças.
                        e, d, o = (jaq_entregue, jaq_data, jaq_obs) if (jaq_entregue or jaq_obs) else \
                            ((entregue, None, obs) if not data else (False, None, ''))
                    else:
                        e, d, o = entregue, data, obs
                    ItemPedido.objects.create(
                        pedido=pedido, peca=peca, quantidade=celula[0], tamanho=celula[1],
                        ziper=ler_ziper(linha.get('ziper')) if peca.tem_ziper else '',
                        entregue=e, entregue_em=d, entrega_obs=o,
                    )
        return Response({'criados': criados, 'atualizados': atualizados, 'pecas_nao_encontradas': sorted(sem_peca)})


class PecaViewSet(viewsets.ModelViewSet):
    permission_classes = [IsRHUniformes]
    serializer_class = PecaSerializer

    def get_queryset(self):
        qs = Peca.objects.all()
        if self.request.query_params.get('campanha'):
            qs = qs.filter(campanha_id=self.request.query_params['campanha'])
        return qs

    def destroy(self, request, *args, **kwargs):
        if self.get_object().itens.exists():
            return Response({'detail': 'Peça já pedida: tire dos pedidos antes de excluir.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class PedidoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsRHUniformes]
    serializer_class = PedidoSerializer

    def get_queryset(self):
        campanha = self.request.query_params.get('campanha')
        if self.action == 'list' and not campanha:
            return Pedido.objects.none()
        qs = _pedidos(campanha) if campanha else Pedido.objects.select_related('campanha', 'colaborador__cargo') \
            .prefetch_related(Prefetch('itens', queryset=ItemPedido.objects.select_related('peca')))
        return qs

    @action(detail=True, methods=['post'])
    def entregar(self, request, pk=None):
        """Marca como entregues hoje os itens pendentes (ou os ``itens`` informados)."""
        pedido = self.get_object()
        ids = request.data.get('itens')
        qs = pedido.itens.filter(entregue=False)
        if ids:
            qs = qs.filter(id__in=ids)
        qs.update(entregue=True, entregue_em=timezone.localdate())
        return Response(self.get_serializer(self.get_queryset().get(pk=pedido.pk)).data)


class ItemPedidoViewSet(mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Só a entrega de um item muda daqui; o resto vai pelo pedido."""

    permission_classes = [IsRHUniformes]
    serializer_class = ItemPedidoSerializer
    queryset = ItemPedido.objects.select_related('peca')
