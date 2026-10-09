import random
import secrets
import unicodedata

from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import TURNOS, Evento, Participante, Premio, Presenca, Sorteio
from .permissions import IsSipat
from .regras import concorrentes, dias_do_evento, ids_semana_inteira
from .serializers import EventoSerializer, ParticipanteSerializer, PremioSerializer, SorteioSerializer

TURNOS_VALIDOS = {t for t, _ in TURNOS}


def _chave_nome(nome: str) -> str:
    sem_acento = unicodedata.normalize('NFKD', nome or '').encode('ascii', 'ignore').decode()
    return ' '.join(sem_acento.upper().split())


def _evento_da_query(request):
    evento_id = request.query_params.get('evento')
    if not evento_id:
        raise ValidationError({'evento': 'Informe o evento.'})
    return evento_id


class EventoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSipat]
    serializer_class = EventoSerializer
    queryset = Evento.objects.all()

    @action(detail=True, methods=['get'])
    def resumo(self, request, pk=None):
        evento = self.get_object()
        dias = dias_do_evento(evento)
        participantes = Participante.objects.filter(evento=evento, ativo=True)

        por_dia = []
        for d in dias:
            linha = {'data': d}
            for turno, _ in TURNOS:
                linha[turno] = Presenca.objects.filter(
                    participante__in=participantes, data=d, turno=turno
                ).count()
            linha['total'] = participantes.filter(presencas__data=d).distinct().count()
            por_dia.append(linha)

        return Response({
            'dias': dias,
            'participantes': participantes.count(),
            'com_presenca': participantes.filter(presencas__isnull=False).distinct().count(),
            'semana_inteira': len(ids_semana_inteira(evento) & set(participantes.values_list('id', flat=True))),
            'sorteados': Sorteio.objects.filter(evento=evento).count(),
            'por_dia': por_dia,
        })

    @action(detail=True, methods=['post'])
    def importar(self, request, pk=None):
        """
        Recebe as linhas já lidas da planilha no navegador:
        ``{"linhas": [{"matricula", "nome", "setor", "empresa"}], "inativar_ausentes": bool}``.
        Casa por matrícula; sem matrícula, pelo nome sem acento. Nunca apaga —
        quem tem presença ou sorteio não pode sumir.
        """
        evento = self.get_object()
        linhas = request.data.get('linhas') or []
        if not isinstance(linhas, list) or not linhas:
            raise ValidationError({'linhas': 'Nenhuma linha recebida.'})

        existentes = list(Participante.objects.filter(evento=evento))
        por_matricula = {p.matricula.strip(): p for p in existentes if p.matricula.strip()}
        por_nome = {_chave_nome(p.nome): p for p in existentes}

        criados = atualizados = ignorados = 0
        vistos: set[int] = set()
        with transaction.atomic():
            for bruta in linhas:
                nome = ' '.join(str(bruta.get('nome') or '').split())
                if not nome:
                    ignorados += 1
                    continue
                matricula = str(bruta.get('matricula') or '').strip()
                if matricula.endswith('.0'):  # número lido do Excel como float
                    matricula = matricula[:-2]
                dados = {
                    'nome': nome[:200],
                    'setor': str(bruta.get('setor') or '').strip()[:150],
                    'empresa': str(bruta.get('empresa') or '').strip()[:150],
                }
                p = (por_matricula.get(matricula) if matricula else None) or por_nome.get(_chave_nome(nome))
                if p:
                    mudou = False
                    for campo, valor in dados.items():
                        # Mesma pessoa grafada em caixa alta/sem acento: mantém o nome que já estava.
                        if campo == 'nome' and _chave_nome(valor) == _chave_nome(p.nome):
                            continue
                        if valor and getattr(p, campo) != valor:
                            setattr(p, campo, valor)
                            mudou = True
                    if matricula and p.matricula != matricula:
                        p.matricula, mudou = matricula, True
                    if not p.ativo:
                        p.ativo, mudou = True, True
                    if mudou:
                        p.save()
                        atualizados += 1
                else:
                    p = Participante.objects.create(evento=evento, matricula=matricula, **dados)
                    criados += 1
                    if matricula:
                        por_matricula[matricula] = p
                    por_nome[_chave_nome(nome)] = p
                vistos.add(p.id)

            inativados = 0
            if request.data.get('inativar_ausentes'):
                inativados = (
                    Participante.objects.filter(evento=evento, ativo=True)
                    .exclude(id__in=vistos).update(ativo=False)
                )

        return Response({
            'criados': criados, 'atualizados': atualizados,
            'ignorados': ignorados, 'inativados': inativados,
        })


class ParticipanteViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSipat]
    serializer_class = ParticipanteSerializer

    def get_queryset(self):
        qs = Participante.objects.prefetch_related(
            'presencas', Prefetch('sorteios', queryset=Sorteio.objects.select_related('premio'))
        )
        if self.action == 'list':
            qs = qs.filter(evento_id=_evento_da_query(self.request))
        return qs

    def destroy(self, request, *args, **kwargs):
        p = self.get_object()
        if p.sorteios.exists():
            return Response({'detail': 'Participante já sorteado: anule o sorteio antes ou apenas desative.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def presenca(self, request, pk=None):
        """``{"data": "AAAA-MM-DD", "turno": "M"|"T", "presente": bool}``"""
        p = self.get_object()
        data = str(request.data.get('data') or '')[:10]
        turno = request.data.get('turno')
        if turno not in TURNOS_VALIDOS:
            raise ValidationError({'turno': 'Turno inválido.'})
        if data not in dias_do_evento(p.evento):
            raise ValidationError({'data': 'Dia fora do evento.'})
        if request.data.get('presente', True):
            Presenca.objects.get_or_create(
                participante=p, data=data, turno=turno,
                defaults={'registrado_por': request.user},
            )
        else:
            Presenca.objects.filter(participante=p, data=data, turno=turno).delete()
        p = self.get_queryset().get(pk=p.pk)
        return Response(self.get_serializer(p).data)


class PremioViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSipat]
    serializer_class = PremioSerializer

    def get_queryset(self):
        qs = Premio.objects.prefetch_related(
            Prefetch('sorteios', queryset=Sorteio.objects.select_related('participante'))
        )
        if self.action == 'list':
            qs = qs.filter(evento_id=_evento_da_query(self.request))
        return qs

    def destroy(self, request, *args, **kwargs):
        if self.get_object().sorteios.exists():
            return Response({'detail': 'Prêmio já sorteado: anule os sorteios antes de excluir.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get'])
    def concorrentes(self, request, pk=None):
        premio = self.get_object()
        qs = concorrentes(premio)
        return Response({'total': qs.count()})

    @action(detail=True, methods=['post'])
    def sortear(self, request, pk=None):
        with transaction.atomic():
            # Trava o prêmio: dois cliques simultâneos não sorteiam a mesma unidade duas vezes.
            premio = Premio.objects.select_for_update().select_related('evento').get(pk=self.get_object().pk)
            validos = premio.sorteios.filter(status=Sorteio.STATUS_GANHADOR).count()
            if validos >= premio.quantidade:
                return Response({'detail': 'Todas as unidades deste prêmio já foram sorteadas.'},
                                status=status.HTTP_400_BAD_REQUEST)
            urna = list(concorrentes(premio).values('id', 'nome'))
            if not urna:
                return Response({'detail': 'Ninguém concorre a este prêmio pela regra definida.'},
                                status=status.HTTP_400_BAD_REQUEST)
            escolhido = secrets.choice(urna)
            try:
                sorteio = Sorteio.objects.create(
                    evento=premio.evento, premio=premio, participante_id=escolhido['id'],
                    total_concorrentes=len(urna), sorteado_por=request.user,
                )
            except IntegrityError:
                return Response({'detail': 'Este participante acabou de ser sorteado em outro prêmio. Sorteie de novo.'},
                                status=status.HTTP_409_CONFLICT)

        # Nomes para a animação da roleta (só visual — o resultado já está gravado).
        outros = [c['nome'] for c in urna if c['id'] != escolhido['id']]
        roleta = random.sample(outros, min(40, len(outros)))
        sorteio = Sorteio.objects.select_related('participante', 'premio', 'sorteado_por').get(pk=sorteio.pk)
        return Response({
            'sorteio': SorteioSerializer(sorteio).data,
            'roleta': roleta,
            'premio': PremioSerializer(self.get_queryset().get(pk=premio.pk)).data,
        }, status=status.HTTP_201_CREATED)


class SorteioViewSet(viewsets.ReadOnlyModelViewSet):
    """Histórico. Anular (DELETE) devolve a pessoa à urna; ``ausente`` não devolve."""

    permission_classes = [IsSipat]
    serializer_class = SorteioSerializer

    def get_queryset(self):
        qs = Sorteio.objects.select_related('participante', 'premio', 'sorteado_por')
        if self.action == 'list':
            qs = qs.filter(evento_id=_evento_da_query(self.request))
        return qs

    def destroy(self, request, pk=None):
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def ausente(self, request, pk=None):
        s = self.get_object()
        s.status = Sorteio.STATUS_AUSENTE
        s.save(update_fields=['status'])
        return Response(self.get_serializer(s).data)
