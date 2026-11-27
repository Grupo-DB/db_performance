"""API do módulo de vistorias (/api/vistorias/...)."""
from collections import defaultdict
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import execucao, indicador, regras, servicos
from .models import (Auditoria, DestinatarioNotificacao, EmailVistoria, Equipamento, Evidencia, Ficha, ImagemTipo, Impedimento,
                     NCCritica, PerfilUsuario, ProgramaItem, Resposta, Setor, Suspensao, TipoEquipamento, Unidade,
                     Vistoria)
from .permissions import (PERFIS, Gestao, LeituraOuGestao, NoModulo, eh_avaliador,
                          eh_gestor, filtro_equipamentos, grupos, pode_corrigir, pode_liberar, so_os_seus)
from .serializers import (DestinatarioSerializer, EquipamentoSerializer, EvidenciaSerializer, FichaSerializer,
                          FichaVersaoSerializer, ProgramaItemSerializer, SetorSerializer, SuspensaoSerializer,
                          TipoEquipamentoSerializer, UnidadeSerializer, VistoriaListaSerializer, VistoriaSerializer,
                          nome, processar_midia, situacao_equipamento)

User = get_user_model()


def _int(v, padrao=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return padrao


def equipamentos_visiveis(user):
    return Equipamento.objects.filter(filtro_equipamentos(user))


def mapa_suspensoes(ids=None) -> dict[int, Suspensao]:
    qs = Suspensao.objects.filter(status__in=(Suspensao.SUSPENSA, Suspensao.AGUARDANDO)).order_by('iniciada_em')
    if ids is not None:
        qs = qs.filter(equipamento_id__in=ids)
    return {s.equipamento_id: s for s in qs}


def resumo_suspensos(eq_qs) -> list[dict]:
    """Quadro de alerta (5.4): quantidade e lista dos suspensos do filtro."""
    ids = list(eq_qs.values_list('id', flat=True))
    saida = []
    for s in (Suspensao.objects.filter(equipamento_id__in=ids, status__in=(Suspensao.SUSPENSA, Suspensao.AGUARDANDO))
              .select_related('equipamento__setor', 'equipamento__unidade').prefetch_related('ncs').order_by('iniciada_em')):
        pendentes = sum(1 for nc in s.ncs.all() if nc.status == NCCritica.PENDENTE)
        saida.append({'id': s.id, 'equipamento': s.equipamento_id, 'tag': s.equipamento.tag,
                      'descricao': s.equipamento.descricao, 'setor': s.equipamento.setor.nome,
                      'unidade': s.equipamento.unidade.sigla, 'desde': s.iniciada_em, 'status': s.status,
                      'adesivo': s.adesivo,
                      'aguardando': 'aguardando liberação' if s.status == Suspensao.AGUARDANDO else
                      ('aguardando correção do PCM' if pendentes else 'aguardando liberação')})
    return saida


def filtrar_equipamentos(qs, params):
    for campo in ('unidade', 'setor', 'gerente', 'tipo'):
        v = params.get(campo)
        if v:
            qs = qs.filter(**{f'{campo}_id': v})
    if params.get('periodicidade'):
        qs = qs.filter(periodicidade=params['periodicidade'])
    return qs


# ── Opções / perfil ────────────────────────────────────────────────────────────
class OpcoesView(APIView):
    permission_classes = [NoModulo]

    def get(self, request):
        u = request.user
        gerentes = User.objects.filter(equipamentos_vistoria__isnull=False).distinct().order_by('first_name', 'username')
        return Response({
            'eu': {'id': u.pk, 'nome': nome(u), 'perfis': sorted(grupos(u) & set(PERFIS)),
                   'gestor': eh_gestor(u), 'avaliador': eh_avaliador(u), 'pcm': pode_corrigir(u),
                   'sesmt': pode_liberar(u), 'so_os_seus': so_os_seus(u)},
            'unidades': UnidadeSerializer(Unidade.objects.all(), many=True).data,
            'setores': SetorSerializer(Setor.objects.select_related('unidade'), many=True).data,
            'tipos': [{'id': t.id, 'codigo': t.codigo, 'descricao': t.descricao, 'medicao': t.medicao,
                       'ficha': t.ficha_id, 'ativo': t.ativo} for t in TipoEquipamento.objects.all()],
            'gerentes': [{'id': g.pk, 'nome': nome(g)} for g in gerentes],
            'hoje': timezone.localdate().isoformat(),
        })


# ── Cadastros ──────────────────────────────────────────────────────────────────
class SemExcluir:
    """Cadastro não se apaga: inativa (preserva histórico)."""

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        obj.ativo = False
        obj.save(update_fields=['ativo'])
        servicos.auditar(request.user, 'inativar', obj._meta.model_name, obj.pk, str(obj))
        return Response(status=status.HTTP_204_NO_CONTENT)


class Auditado:
    def perform_create(self, serializer):
        obj = serializer.save()
        servicos.auditar(self.request.user, 'criar', obj._meta.model_name, obj.pk, str(obj))

    def perform_update(self, serializer):
        obj = serializer.save()
        servicos.auditar(self.request.user, 'alterar', obj._meta.model_name, obj.pk, str(obj),
                         campos=sorted(serializer.validated_data.keys()))


class UnidadeViewSet(Auditado, SemExcluir, viewsets.ModelViewSet):
    permission_classes = [LeituraOuGestao]
    serializer_class = UnidadeSerializer
    queryset = Unidade.objects.all()


class SetorViewSet(Auditado, SemExcluir, viewsets.ModelViewSet):
    permission_classes = [LeituraOuGestao]
    serializer_class = SetorSerializer
    queryset = Setor.objects.select_related('unidade')


class TipoViewSet(Auditado, SemExcluir, viewsets.ModelViewSet):
    permission_classes = [LeituraOuGestao]
    serializer_class = TipoEquipamentoSerializer
    queryset = TipoEquipamento.objects.select_related('ficha').prefetch_related('imagens')
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @action(detail=True, methods=['post'])
    def imagens(self, request, pk=None):
        """Desenho/foto de referência para marcar avarias (GEO)."""
        tipo = self.get_object()
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            raise ValidationError({'arquivo': 'Envie a imagem.'})
        conteudo, tipo_midia, _ = processar_midia(arquivo)
        if tipo_midia != Evidencia.FOTO:
            raise ValidationError({'arquivo': 'Envie uma imagem (não vídeo).'})
        from PIL import Image as PImage
        import io as _io
        with PImage.open(_io.BytesIO(conteudo.read())) as im:
            larg, alt = im.size
        conteudo.seek(0)
        ordem = (tipo.imagens.order_by('-ordem').values_list('ordem', flat=True).first() or 0) + 1
        img = ImagemTipo(tipo=tipo, legenda=str(request.data.get('legenda') or '')[:120], ordem=ordem, largura=larg, altura=alt)
        img.arquivo.save('desenho.jpg', conteudo, save=True)
        servicos.auditar(request.user, 'imagem_tipo', 'tipo', tipo.pk, f'{tipo.descricao}: imagem incluída')
        return Response(self.get_serializer(tipo).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch'], url_path=r'imagens/(?P<img>\d+)')
    def imagem(self, request, pk=None, img=None):
        """Legenda, ordem ou ativa. Não apaga: vistorias antigas marcaram sobre ela."""
        tipo = self.get_object()
        i = get_object_or_404(tipo.imagens, pk=img)
        for campo in ('legenda', 'ordem', 'ativa'):
            if campo in request.data:
                setattr(i, campo, request.data[campo] if campo != 'legenda' else str(request.data[campo])[:120])
        i.save()
        servicos.auditar(request.user, 'imagem_tipo', 'tipo', tipo.pk, f'{tipo.descricao}: imagem {i.pk} alterada')
        return Response(self.get_serializer(tipo).data)


class ImagemArquivoView(APIView):
    permission_classes = [NoModulo]

    def get(self, request, pk):
        i = get_object_or_404(ImagemTipo, pk=pk)
        try:
            arq = i.arquivo.open('rb')
        except FileNotFoundError:
            raise Http404
        nome_arq = i.arquivo.name.lower()
        resp = FileResponse(arq, content_type='image/png' if nome_arq.endswith('.png') else 'image/jpeg')
        resp['Cache-Control'] = 'private, max-age=604800'
        return resp


class DestinatarioViewSet(Auditado, viewsets.ModelViewSet):
    permission_classes = [Gestao]
    serializer_class = DestinatarioSerializer
    queryset = DestinatarioNotificacao.objects.select_related('unidade')

    def perform_destroy(self, instance):
        servicos.auditar(self.request.user, 'excluir', 'destinatario', instance.pk, instance.email)
        instance.delete()


class FichaViewSet(Auditado, SemExcluir, viewsets.ModelViewSet):
    permission_classes = [LeituraOuGestao]
    serializer_class = FichaSerializer
    queryset = Ficha.objects.prefetch_related('tipos', 'versoes')

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['resumo'] = self.action == 'list'
        return ctx

    @action(detail=True, methods=['post'])
    def versoes(self, request, pk=None):
        """Grava a ficha inteira como versão nova (questões: lista completa)."""
        ficha = self.get_object()
        questoes = request.data.get('questoes')
        if not isinstance(questoes, list) or not questoes:
            raise ValidationError({'questoes': 'Envie a lista de questões.'})
        v = servicos.nova_versao(ficha, questoes, request.user, request.data.get('observacao', ''))
        return Response(FichaVersaoSerializer(v).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path=r'versao/(?P<numero>\d+)')
    def versao(self, request, pk=None, numero=None):
        ficha = self.get_object()
        v = get_object_or_404(ficha.versoes, numero=numero)
        return Response(FichaVersaoSerializer(v).data)


class EquipamentoViewSet(viewsets.ModelViewSet):
    serializer_class = EquipamentoSerializer
    permission_classes = [NoModulo]

    def get_queryset(self):
        qs = equipamentos_visiveis(self.request.user).select_related('tipo__ficha', 'unidade', 'setor', 'gerente')
        p = self.request.query_params
        qs = filtrar_equipamentos(qs, p)
        if p.get('ativo') in ('1', 'true'):
            qs = qs.filter(ativo=True)
        if p.get('q'):
            qs = qs.filter(Q(tag__icontains=p['q']) | Q(descricao__icontains=p['q']) | Q(placa__icontains=p['q']))
        sit = p.get('situacao')
        if sit:
            abertas = Suspensao.objects.filter(status__in=(Suspensao.SUSPENSA, Suspensao.AGUARDANDO))
            if sit == 'SUSPENSO':
                qs = qs.filter(id__in=abertas.values('equipamento_id'))
            elif sit == 'AGUARDANDO_LIBERACAO':
                qs = qs.filter(id__in=abertas.filter(status=Suspensao.AGUARDANDO).values('equipamento_id'))
            elif sit == 'MANUTENCAO':
                qs = qs.filter(ativo=True, em_manutencao=True).exclude(id__in=abertas.values('equipamento_id'))
            elif sit == 'OPERACAO':
                qs = qs.filter(ativo=True, em_manutencao=False).exclude(id__in=abertas.values('equipamento_id'))
            elif sit == 'INATIVO':
                qs = qs.filter(ativo=False)
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.action == 'list':
            ctx['suspensoes'] = mapa_suspensoes()
        return ctx

    def _gestor(self):
        if not eh_gestor(self.request.user):
            raise PermissionDenied('Só o Gerente Executivo Operacional altera o cadastro de equipamentos.')

    @transaction.atomic
    def perform_create(self, serializer):
        self._gestor()
        eq = serializer.save()
        servicos.registrar_vinculo(eq, self.request.user)
        servicos.sincronizar_programa(eq, self.request.user)
        servicos.auditar(self.request.user, 'criar', 'equipamento', eq.pk, eq.tag)

    @transaction.atomic
    def perform_update(self, serializer):
        self._gestor()
        antes = {c: getattr(serializer.instance, c) for c in ('periodicidade', 'ativo')}
        eq = serializer.save()
        servicos.registrar_vinculo(eq, self.request.user)
        if antes != {c: getattr(eq, c) for c in antes}:
            servicos.sincronizar_programa(eq, self.request.user)
        servicos.auditar(self.request.user, 'alterar', 'equipamento', eq.pk, eq.tag,
                         campos=sorted(serializer.validated_data.keys()))

    def destroy(self, request, *args, **kwargs):
        self._gestor()
        eq = self.get_object()
        eq.ativo = False
        eq.save(update_fields=['ativo'])
        servicos.registrar_vinculo(eq, request.user)
        servicos.sincronizar_programa(eq, request.user)
        servicos.auditar(request.user, 'inativar', 'equipamento', eq.pk, eq.tag)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def manutencao(self, request, pk=None):
        """Em manutenção: informativa (9.4). PCM ou GEO."""
        if not pode_corrigir(request.user):
            raise PermissionDenied('Só PCM ou Gerente Executivo Operacional.')
        eq = self.get_object()
        eq.em_manutencao = bool(request.data.get('em_manutencao'))
        eq.save(update_fields=['em_manutencao', 'atualizado_em'])
        servicos.auditar(request.user, 'manutencao', 'equipamento', eq.pk,
                         f'{eq.tag}: {"em manutenção" if eq.em_manutencao else "em operação"}')
        return Response(self.get_serializer(eq).data)

    @action(detail=True, methods=['get', 'post', 'delete'], parser_classes=[MultiPartParser, FormParser, JSONParser])
    def foto(self, request, pk=None):
        """
        Foto do equipamento. Com código do SGA é a MESMA de Peças da Oficina (foto do Manager; senão a do SGA):
        trocar aqui troca lá. Sem SGA, fica no próprio cadastro. Enviar/remover: GEO.
        """
        eq = self.get_object()
        if request.method == 'GET':
            dados = None
            if eq.foto:
                try:
                    with eq.foto.open('rb') as f:
                        dados = f.read()
                except FileNotFoundError:
                    dados = None
            elif eq.sga_codigo:
                try:
                    from catalogos import pecas_oficina
                    dados = pecas_oficina.foto_equipamento(eq.sga_codigo, request.query_params.get('tam', 'p'))
                except Exception:  # noqa: BLE001 — SGA fora: a tela mostra o ícone
                    dados = None
            if not dados:
                raise Http404
            from django.http import HttpResponse
            resp = HttpResponse(dados, content_type='image/jpeg')
            resp['Cache-Control'] = 'private, max-age=3600'
            return resp
        if not eh_gestor(request.user):
            raise PermissionDenied('Só o Gerente Executivo Operacional altera a foto.')
        if request.method == 'DELETE':
            if eq.foto:
                eq.foto.delete(save=True)
            elif eq.sga_codigo:
                from catalogos import pecas_oficina
                pecas_oficina.remover_foto_equipamento(eq.sga_codigo)
            servicos.auditar(request.user, 'foto_equipamento', 'equipamento', eq.pk, f'{eq.tag}: foto removida')
            return Response(status=status.HTTP_204_NO_CONTENT)
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            raise ValidationError({'arquivo': 'Escolha a foto.'})
        if eq.sga_codigo:
            from catalogos import pecas_oficina
            try:
                pecas_oficina.salvar_foto_equipamento(eq.sga_codigo, arquivo, request.user)
            except ValueError as exc:
                raise ValidationError({'arquivo': str(exc)})
        else:
            conteudo, tipo_midia, _ = processar_midia(arquivo)
            if tipo_midia != Evidencia.FOTO:
                raise ValidationError({'arquivo': 'Envie uma foto.'})
            if eq.foto:
                eq.foto.delete(save=False)
            eq.foto.save('foto.jpg', conteudo, save=True)
        servicos.auditar(request.user, 'foto_equipamento', 'equipamento', eq.pk, f'{eq.tag}: foto enviada')
        return Response(self.get_serializer(eq).data)

    @action(detail=True, methods=['get'])
    def historico(self, request, pk=None):
        eq = self.get_object()
        vist = (eq.vistorias.select_related('avaliador', 'ficha_versao__ficha', 'unidade', 'setor', 'gerente', 'item')
                .prefetch_related('respostas').order_by('-iniciada_em'))
        return Response({
            'equipamento': self.get_serializer(eq).data,
            'vistorias': VistoriaListaSerializer(vist, many=True).data,
            'suspensoes': SuspensaoSerializer(eq.suspensoes.select_related('vistoria__avaliador', 'equipamento__unidade',
                                                                           'equipamento__setor', 'equipamento__gerente')
                                              .prefetch_related('ncs__resposta', 'emails'), many=True).data,
            'vinculos': [{'desde': v.desde, 'unidade': v.unidade.sigla, 'setor': v.setor.nome, 'gerente': nome(v.gerente),
                          'tipo': v.tipo.descricao, 'periodicidade': v.periodicidade, 'ativo': v.ativo,
                          'alterado_por': nome(v.alterado_por)}
                         for v in eq.vinculos.select_related('unidade', 'setor', 'gerente', 'tipo', 'alterado_por')],
        })

    @action(detail=False, methods=['get'])
    def sga(self, request):
        """Equipamentos ativos do SGA para importar (TAG, descrição, placa, medição)."""
        if not eh_gestor(request.user):
            raise PermissionDenied()
        try:
            from combustivel import erp
            lista = erp.equipamentos()
        except Exception as exc:  # noqa: BLE001 — SGA fora não pode derrubar a tela
            return Response({'equipamentos': [], 'aviso': f'SGA indisponível: {exc}'[:300]})
        ja = set(Equipamento.objects.exclude(sga_codigo=None).values_list('sga_codigo', flat=True))
        tags = set(Equipamento.objects.values_list('tag', flat=True))
        return Response({'equipamentos': [
            {**{k: e[k] for k in ('cod', 'tag', 'descricao', 'nome', 'placa', 'tipo_nome', 'usa_km', 'usa_horimetro',
                                  'centro_custo_nome')},
             'importado': e['cod'] in ja or (e['tag'] or '').upper() in tags}
            for e in lista], 'aviso': None})

    @action(detail=False, methods=['post'], url_path='importar-sga-todos')
    def importar_sga_todos(self, request):
        """Lote automático: tipo pelo prefixo da TAG (vistorias/sga.py). ``aplicar=false`` devolve só a prévia."""
        if not eh_gestor(request.user):
            raise PermissionDenied()
        try:
            from combustivel import erp
            lista = erp.equipamentos()
        except Exception as exc:  # noqa: BLE001
            raise ValidationError({'detail': f'SGA indisponível: {exc}'[:300]})
        from . import sga
        if request.data.get('aplicar'):
            per = request.data.get('periodicidade') or 'MENSAL'
            if per not in ('MENSAL', 'BIMESTRAL', 'TRIMESTRAL'):
                raise ValidationError({'periodicidade': 'Inválida.'})
            return Response(sga.importar(lista, request.user, per))
        return Response(sga.planejar(lista))

    @action(detail=False, methods=['post'], url_path='importar-sga')
    @transaction.atomic
    def importar_sga(self, request):
        if not eh_gestor(request.user):
            raise PermissionDenied()
        itens = request.data.get('itens') or []
        try:
            from combustivel import erp
            sga = erp.mapa_equipamentos()
        except Exception as exc:  # noqa: BLE001
            raise ValidationError({'detail': f'SGA indisponível: {exc}'[:300]})
        criados, erros = [], []
        for it in itens:
            e = sga.get(_int(it.get('cod')))
            if not e:
                erros.append(f'{it.get("cod")}: não encontrado no SGA')
                continue
            tag = (it.get('tag') or e['tag'] or str(e['cod'])).strip().upper()[:30]
            if Equipamento.objects.filter(Q(tag=tag) | Q(sga_codigo=e['cod'])).exists():
                erros.append(f'{tag}: já cadastrado')
                continue
            dados = {'tag': tag, 'descricao': (it.get('descricao') or e['descricao'] or e['nome'])[:160],
                     'placa': (e['placa'] or '')[:10], 'tipo': it.get('tipo'), 'unidade': it.get('unidade'),
                     'setor': it.get('setor'), 'gerente': it.get('gerente'),
                     'periodicidade': it.get('periodicidade') or 'MENSAL', 'sga_codigo': e['cod'],
                     'marca_modelo': it.get('marca_modelo', '')}
            ser = EquipamentoSerializer(data=dados)
            if not ser.is_valid():
                erros.append(f'{tag}: ' + '; '.join(f'{k}: {v[0]}' for k, v in ser.errors.items()))
                continue
            eq = ser.save()
            servicos.registrar_vinculo(eq, request.user)
            servicos.sincronizar_programa(eq, request.user)
            criados.append(eq.tag)
        if criados:
            servicos.auditar(request.user, 'importar_sga', 'equipamento', '', f'{len(criados)} equipamentos do SGA',
                             tags=criados)
        return Response({'criados': criados, 'erros': erros})


# ── Usuários do módulo ─────────────────────────────────────────────────────────
class UsuariosView(APIView):
    """Quem tem perfil no módulo + cargo/unidades. O GEO concede e retira perfis (grupos)."""
    permission_classes = [Gestao]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if q:
            qs = list(User.objects.filter(is_active=True).filter(
                Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
                .prefetch_related('groups')[:30])
        else:
            qs = list(User.objects.filter(groups__name__in=PERFIS).distinct().prefetch_related('groups'))
        perfis = {p.usuario_id: p for p in PerfilUsuario.objects.filter(usuario__in=[u.pk for u in qs]).prefetch_related('unidades')}
        saida = []
        for u in qs:
            p = perfis.get(u.pk)
            saida.append({'id': u.pk, 'nome': nome(u), 'username': u.username, 'email': u.email, 'ativo': u.is_active,
                          'perfis': sorted({g.name for g in u.groups.all()} & set(PERFIS)),
                          'cargo': p.cargo if p else '', 'unidades': [x.pk for x in p.unidades.all()] if p else []})
        saida.sort(key=lambda x: x['nome'].lower())
        return Response(saida)

    @transaction.atomic
    def post(self, request):
        u = get_object_or_404(User, pk=request.data.get('id'))
        perfis = set(request.data.get('perfis') or []) & set(PERFIS)
        for p in PERFIS:
            g, _ = Group.objects.get_or_create(name=p)
            if p in perfis:
                u.groups.add(g)
            else:
                u.groups.remove(g)
        perfil, _ = PerfilUsuario.objects.get_or_create(usuario=u)
        perfil.cargo = str(request.data.get('cargo') or '')[:120]
        perfil.save()
        perfil.unidades.set(Unidade.objects.filter(pk__in=request.data.get('unidades') or []))
        servicos.auditar(request.user, 'usuario_perfis', 'usuario', u.pk, f'{nome(u)}: {", ".join(sorted(perfis)) or "sem perfil"}')
        return Response({'ok': True})


# ── Programa ───────────────────────────────────────────────────────────────────
class ProgramaView(APIView):
    """Mapa anual (5.4): equipamentos × meses, com a situação de cada célula."""
    permission_classes = [NoModulo]

    def get(self, request):
        p = request.query_params
        hoje = timezone.localdate()
        ano = _int(p.get('ano'), hoje.year)
        eqs = filtrar_equipamentos(equipamentos_visiveis(request.user), p).select_related('tipo', 'setor', 'unidade', 'gerente')
        itens = (ProgramaItem.objects.filter(ano=ano, equipamento__in=eqs)
                 .exclude(situacao=ProgramaItem.CANCELADA)
                 .prefetch_related('impedimentos', Prefetch('vistorias', queryset=Vistoria.objects.only(
                     'id', 'uuid', 'status', 'concluida_em', 'resultado_inicial', 'resultado_final', 'item_id'))))
        por_eq = defaultdict(dict)
        for it in itens:
            cel = servicos.situacao_item(it, list(it.vistorias.all()), list(it.impedimentos.all()), hoje)
            cel['item'] = it.id
            cel['manual'] = it.manual
            atual = por_eq[it.equipamento_id].get(it.mes)
            # mês com item reprogramado E o novo: mostra o que vale
            if atual is None or atual['codigo'] == 'X':
                por_eq[it.equipamento_id][it.mes] = cel
        extra = defaultdict(list)
        ini, _ = regras.limites_do_mes(ano, 1)
        _, fim = regras.limites_do_mes(ano, 12)
        for v in Vistoria.objects.filter(equipamento__in=eqs, tipo=Vistoria.EXTRAORDINARIA, iniciada_em__range=(ini, fim)):
            m = timezone.localtime(v.iniciada_em).month
            extra[v.equipamento_id].append({'mes': m, 'vistoria': str(v.uuid), 'status': v.status,
                                            'resultado': v.resultado_vigente})
        susp = mapa_suspensoes([e.pk for e in eqs])
        linhas = []
        for e in eqs.order_by('tag'):
            if not por_eq.get(e.pk) and not e.ativo:
                continue
            s = susp.get(e.pk)
            linhas.append({'equipamento': e.pk, 'tag': e.tag, 'descricao': e.descricao, 'periodicidade': e.periodicidade,
                           'tipo': e.tipo.descricao, 'setor': e.setor.nome, 'unidade': e.unidade.sigla,
                           'gerente': nome(e.gerente), 'ativo': e.ativo,
                           'situacao': situacao_equipamento(e, s),
                           'suspenso_desde': s.iniciada_em if s else None,
                           'meses': por_eq.get(e.pk, {}), 'extraordinarias': extra.get(e.pk, [])})
        return Response({'ano': ano, 'linhas': linhas, 'suspensos': resumo_suspensos(eqs),
                         'tem_programa': ProgramaItem.objects.filter(ano=ano).exists()})


class ProgramaGerarView(APIView):
    permission_classes = [Gestao]

    def post(self, request):
        ano = _int(request.data.get('ano'))
        if not ano or ano < 2020 or ano > timezone.localdate().year + 1:
            raise ValidationError({'ano': 'Ano inválido.'})
        criados = servicos.gerar_programa(ano, request.user)
        return Response({'criados': criados})


class ProgramaItemViewSet(mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = ProgramaItemSerializer
    permission_classes = [NoModulo]

    def get_queryset(self):
        return (ProgramaItem.objects.filter(equipamento__in=equipamentos_visiveis(self.request.user))
                .select_related('equipamento', 'decidido_por').prefetch_related('impedimentos__registrado_por'))

    def create(self, request, *args, **kwargs):
        """Inclusão manual pelo GEO (ajuste do programa)."""
        if not eh_gestor(request.user):
            raise PermissionDenied()
        eq = get_object_or_404(Equipamento, pk=request.data.get('equipamento'))
        ano, mes = _int(request.data.get('ano')), _int(request.data.get('mes'))
        if not ano or not mes or not 1 <= mes <= 12:
            raise ValidationError({'mes': 'Mês inválido.'})
        if servicos.item_aberto(eq, ano, mes):
            raise ValidationError({'mes': 'Já existe vistoria programada nesse mês.'})
        it = ProgramaItem.objects.create(equipamento=eq, ano=ano, mes=mes, manual=True,
                                         justificativa=str(request.data.get('justificativa') or '')[:500])
        servicos.auditar(request.user, 'programa_incluir', 'programa_item', it.pk, f'{eq.tag} {regras.NOMES_MES[mes]}/{ano}')
        return Response(self.get_serializer(it).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        it = self.get_object()
        dados = self.get_serializer(it).data
        dados['vistorias'] = VistoriaListaSerializer(
            it.vistorias.select_related('equipamento', 'avaliador', 'unidade', 'setor', 'gerente', 'ficha_versao__ficha')
            .prefetch_related('respostas'), many=True).data
        dados['reprogramada_para'] = [{'id': r.id, 'ano': r.ano, 'mes': r.mes} for r in it.reprogramacoes.all()]
        return Response(dados)

    @action(detail=True, methods=['post'])
    def dispensar(self, request, pk=None):
        if not eh_gestor(request.user):
            raise PermissionDenied('Só o Gerente Executivo Operacional dispensa vistorias.')
        it = servicos.dispensar(self.get_object(), request.user, request.data.get('justificativa'),
                                bool(request.data.get('confirmado')))
        return Response(self.get_serializer(it).data)

    @action(detail=True, methods=['post'])
    def reprogramar(self, request, pk=None):
        if not eh_gestor(request.user):
            raise PermissionDenied('Só o Gerente Executivo Operacional reprograma vistorias.')
        novo = servicos.reprogramar(self.get_object(), request.user, _int(request.data.get('ano')),
                                    _int(request.data.get('mes')), request.data.get('justificativa'))
        return Response(self.get_serializer(novo).data)

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        if not eh_gestor(request.user):
            raise PermissionDenied()
        it = self.get_object()
        if it.situacao != ProgramaItem.PROGRAMADA or it.vistorias.exists():
            raise ValidationError({'detail': 'Só item programado e sem vistoria pode sair do programa.'})
        just = str(request.data.get('justificativa') or '').strip()
        if not just:
            raise ValidationError({'justificativa': 'Informe a justificativa.'})
        it.situacao = ProgramaItem.CANCELADA
        it.justificativa = just[:500]
        it.decidido_por = request.user
        it.decidido_em = timezone.now()
        it.save()
        servicos.auditar(request.user, 'programa_remover', 'programa_item', it.pk, f'{it.equipamento.tag}: {just}')
        return Response(self.get_serializer(it).data)

    @action(detail=True, methods=['post'])
    def impedimento(self, request, pk=None):
        if not eh_avaliador(request.user):
            raise PermissionDenied('Só avaliadores registram impedimento.')
        execucao.registrar_impedimento(self.get_object(), request.user, request.data.get('motivo'))
        return Response(self.get_serializer(self.get_object()).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='manter')
    def manter(self, request, pk=None):
        """GEO decide manter a vistoria (impedimento sem dispensa nem reprogramação)."""
        if not eh_gestor(request.user):
            raise PermissionDenied()
        it = self.get_object()
        n = it.impedimentos.filter(decisao=Impedimento.PENDENTE).update(
            decisao=Impedimento.MANTIDA, decidido_por=request.user, decidido_em=timezone.now())
        if n:
            servicos.auditar(request.user, 'impedimento_manter', 'programa_item', it.pk, it.equipamento.tag)
        return Response(self.get_serializer(it).data)


# ── Avaliador ──────────────────────────────────────────────────────────────────
class MinhasView(APIView):
    """Lista do avaliador (Figura 3): pendentes do mês, atrasadas, em andamento, devolvidas e suspensos."""
    permission_classes = [NoModulo]

    def get(self, request):
        hoje = timezone.localdate()
        eqs = equipamentos_visiveis(request.user).filter(ativo=True)
        itens = (ProgramaItem.objects.filter(equipamento__in=eqs, situacao=ProgramaItem.PROGRAMADA)
                 .filter(Q(ano__lt=hoje.year) | Q(ano=hoje.year, mes__lte=hoje.month))
                 .filter(ano__gte=hoje.year - 1)
                 .exclude(vistorias__status__in=(Vistoria.CONCLUIDA, Vistoria.VALIDADA))
                 .select_related('equipamento__tipo', 'equipamento__setor', 'equipamento__unidade')
                 .prefetch_related('impedimentos', 'vistorias').order_by('ano', 'mes', 'equipamento__tag'))
        susp = mapa_suspensoes()
        pend, atrasadas = [], []
        for it in itens:
            e = it.equipamento
            andamento = [v for v in it.vistorias.all() if v.status == Vistoria.ANDAMENTO]
            imp = [i for i in it.impedimentos.all() if i.decisao == Impedimento.PENDENTE]
            linha = {'item': it.id, 'ano': it.ano, 'mes': it.mes, 'equipamento': e.pk, 'tag': e.tag,
                     'descricao': e.descricao, 'tipo': e.tipo.descricao, 'setor': e.setor.nome, 'unidade': e.unidade.sigla,
                     'periodicidade': e.periodicidade, 'situacao': situacao_equipamento(e, susp.get(e.pk)),
                     'em_andamento': str(andamento[0].uuid) if andamento else None,
                     'andamento_de': nome(andamento[0].avaliador) if andamento else None,
                     'impedimento': {'motivo': imp[0].motivo, 'em': imp[0].registrado_em} if imp else None}
            (pend if (it.ano, it.mes) == (hoje.year, hoje.month) else atrasadas).append(linha)
        minhas = (Vistoria.objects.filter(avaliador=request.user, status=Vistoria.ANDAMENTO)
                  .select_related('equipamento', 'avaliador', 'unidade', 'setor', 'gerente', 'ficha_versao__ficha', 'item')
                  .prefetch_related('respostas', 'devolucoes'))
        andamento = []
        for v in minhas:
            d = VistoriaListaSerializer(v).data
            dev = v.devolucoes.first()
            d['devolvida'] = {'justificativa': dev.justificativa, 'em': dev.devolvida_em} if dev else None
            andamento.append(d)
        return Response({'mes': hoje.month, 'ano': hoje.year, 'pendentes': pend, 'atrasadas': atrasadas,
                         'andamento': andamento, 'suspensos': resumo_suspensos(eqs)})


class BuscarEquipamentoView(APIView):
    """Pesquisa por TAG para vistoria extraordinária ou fora da lista."""
    permission_classes = [NoModulo]

    def get(self, request):
        q = (request.query_params.get('q') or '').strip()
        qs = equipamentos_visiveis(request.user).filter(ativo=True)
        if q:
            qs = qs.filter(Q(tag__icontains=q) | Q(descricao__icontains=q) | Q(placa__icontains=q))
        # list(): o MySQL não aceita LIMIT dentro de subconsulta IN (NotSupportedError)
        qs = list(qs.select_related('tipo__ficha', 'unidade', 'setor', 'gerente')[:40])
        ids = [e.pk for e in qs]
        susp = mapa_suspensoes(ids)
        hoje = timezone.localdate()
        itens = {i.equipamento_id: i for i in ProgramaItem.objects.filter(
            equipamento_id__in=ids, ano=hoje.year, mes=hoje.month, situacao=ProgramaItem.PROGRAMADA)}
        return Response([{**EquipamentoSerializer(e, context={'suspensoes': susp}).data,
                          'item_do_mes': itens[e.pk].id if e.pk in itens else None} for e in qs])


# ── Vistorias ──────────────────────────────────────────────────────────────────
class VistoriaViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    # quem altera é checado em cada ação: avaliador dono (execucao._do_avaliador) ou GEO (_gestor)
    permission_classes = [NoModulo]
    lookup_field = 'uuid'
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_serializer_class(self):
        return VistoriaListaSerializer if self.action == 'list' else VistoriaSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['suspensoes'] = mapa_suspensoes()
        return ctx

    def get_queryset(self):
        u = self.request.user
        qs = (Vistoria.objects.filter(filtro_equipamentos(u, 'equipamento__'))
              .select_related('equipamento__tipo', 'avaliador', 'unidade', 'setor', 'gerente', 'ficha_versao__ficha',
                              'item', 'validada_por'))
        if self.action == 'list':
            qs = qs.prefetch_related('respostas')
            p = self.request.query_params
            if p.get('status'):
                qs = qs.filter(status__in=p['status'].split(','))
            if p.get('tipo'):
                qs = qs.filter(tipo=p['tipo'])
            if p.get('equipamento'):
                qs = qs.filter(equipamento_id=p['equipamento'])
            if p.get('avaliador'):
                qs = qs.filter(avaliador_id=p['avaliador'])
            for campo in ('unidade', 'setor', 'gerente'):
                if p.get(campo):
                    qs = qs.filter(**{f'{campo}_id': p[campo]})
            if p.get('resultado'):
                r = p['resultado']
                qs = qs.filter(Q(resultado_final=r) | Q(resultado_final='', resultado_inicial=r))
            if p.get('desde'):
                qs = qs.filter(iniciada_em__date__gte=p['desde'])
            if p.get('ate'):
                qs = qs.filter(iniciada_em__date__lte=p['ate'])
            if p.get('ano') and p.get('mes'):
                ini, fim = regras.limites_do_mes(int(p['ano']), int(p['mes']))
                qs = qs.filter(Q(concluida_em__range=(ini, fim)) | Q(concluida_em__isnull=True, iniciada_em__range=(ini, fim)))
            if p.get('com_nc'):
                qs = qs.filter(respostas__valor=Resposta.NC, respostas__cancelada=False).distinct()
            qs = qs[:int(p.get('limite') or 500)]
        else:
            qs = qs.prefetch_related('respostas__evidencias', 'devolucoes__devolvida_por', 'suspensoes',
                                     'respostas__cancelada_por', 'respostas__abonada_por')
        return qs

    def retrieve(self, request, *args, **kwargs):
        v = self.get_object()
        d = VistoriaSerializer(v).data
        d['pendencias'] = execucao.pendencias(v) if v.status == Vistoria.ANDAMENTO else []
        d['pode_editar'] = v.status == Vistoria.ANDAMENTO and v.avaliador_id == request.user.pk
        d['pode_validar'] = v.status == Vistoria.CONCLUIDA and eh_gestor(request.user)
        d['resultado_previsto_final'] = execucao.calcular_resultado(v, final=True) if v.status != Vistoria.ANDAMENTO else ''
        ultimo, quando = execucao.ultima_medicao(v.equipamento, exceto=v)
        d['ultima_medicao'] = {'valor': ultimo, 'em': quando}
        return Response(d)

    def create(self, request):
        if not eh_avaliador(request.user):
            raise PermissionDenied('Só avaliadores executam vistorias.')
        eq = get_object_or_404(equipamentos_visiveis(request.user), pk=request.data.get('equipamento'))
        item = None
        if request.data.get('item'):
            item = get_object_or_404(ProgramaItem, pk=request.data['item'])
        v = execucao.iniciar(eq, request.user, uuid=request.data.get('uuid') or None, item=item,
                             extraordinaria=bool(request.data.get('extraordinaria')), motivo=request.data.get('motivo', ''))
        return Response({'uuid': str(v.uuid)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch'])
    def identificacao(self, request, uuid=None):
        v = execucao.salvar_identificacao(self.get_object(), request.user, request.data)
        return Response({'ok': True, 'medicao_menor': execucao.medicao_menor(v), 'medicao_anterior': v.medicao_anterior})

    @action(detail=True, methods=['post'])
    def responder(self, request, uuid=None):
        r, s = execucao.responder(self.get_object(), request.user, str(request.data.get('codigo', '')),
                                  request.data.get('valor', ''), request.data.get('descricao', ''),
                                  bool(request.data.get('confirmar_critica')), request)
        from .serializers import RespostaSerializer
        return Response({'resposta': RespostaSerializer(r).data,
                         'suspensao': {'id': s.id, 'status': s.status, 'adesivo': s.adesivo} if s else None})

    @action(detail=True, methods=['post'])
    def evidencias(self, request, uuid=None):
        """Upload idempotente pelo ``uuid`` do aparelho (fila offline reenvia sem duplicar)."""
        v = self.get_object()
        ev_uuid = request.data.get('uuid')
        if ev_uuid:
            ja = Evidencia.objects.filter(uuid=ev_uuid).first()
            if ja:
                if ja.vistoria_id != v.pk:
                    raise ValidationError({'uuid': 'uuid em uso.'})
                return Response(EvidenciaSerializer(ja).data)
        if v.avaliador_id != request.user.pk:
            raise PermissionDenied('Só o avaliador da vistoria anexa evidências.')
        if v.status != Vistoria.ANDAMENTO:
            raise ValidationError({'detail': 'Vistoria concluída: evidências não podem ser alteradas.'})
        r = v.respostas.filter(codigo=str(request.data.get('codigo', ''))).first()
        if r is None:
            raise ValidationError({'codigo': 'Questão não encontrada.'})
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            raise ValidationError({'arquivo': 'Envie a foto ou o vídeo.'})
        conteudo, tipo, ct = processar_midia(arquivo)
        extra = {'uuid': ev_uuid} if ev_uuid else {}
        e = Evidencia(**extra, finalidade=Evidencia.NC, vistoria=v, resposta=r, tipo=tipo, content_type=ct,
                      tamanho=conteudo.size, enviada_por=request.user)
        e.arquivo.save(conteudo.name, conteudo, save=False)
        e.save()
        return Response(EvidenciaSerializer(e).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path=r'evidencias/(?P<ev>[0-9a-f-]+)')
    def remover_evidencia(self, request, uuid=None, ev=None):
        v = self.get_object()
        e = get_object_or_404(v.evidencias, uuid=ev)
        if v.avaliador_id != request.user.pk or v.status != Vistoria.ANDAMENTO:
            raise PermissionDenied('Só durante o preenchimento, pelo avaliador.')
        if e.resposta and e.resposta.travada:
            raise ValidationError({'detail': 'Evidência de NC crítica confirmada não pode ser removida.'})
        servicos.auditar(request.user, 'evidencia_remover', 'vistoria', v.uuid, f'questão {e.resposta.codigo if e.resposta else ""}')
        e.arquivo.delete(save=False)
        e.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def concluir(self, request, uuid=None):
        v = execucao.concluir(self.get_object(), request.user)
        return Response(VistoriaSerializer(v).data)

    def _gestor(self):
        if not eh_gestor(self.request.user):
            raise PermissionDenied('Só o Gerente Executivo Operacional.')

    @action(detail=True, methods=['post'])
    def abonar(self, request, uuid=None):
        self._gestor()
        execucao.abonar(self.get_object(), request.user, str(request.data.get('codigo', '')),
                        bool(request.data.get('abonar', True)), request.data.get('justificativa', ''))
        return self.retrieve(request, uuid=uuid)

    @action(detail=True, methods=['post'])
    def validar(self, request, uuid=None):
        self._gestor()
        execucao.validar(self.get_object(), request.user)
        return self.retrieve(request, uuid=uuid)

    @action(detail=True, methods=['post'])
    def devolver(self, request, uuid=None):
        self._gestor()
        execucao.devolver(self.get_object(), request.user, request.data.get('justificativa', ''))
        return self.retrieve(request, uuid=uuid)

    @action(detail=True, methods=['post'], url_path='cancelar-critica')
    def cancelar_critica(self, request, uuid=None):
        self._gestor()
        execucao.cancelar_critica(self.get_object(), request.user, str(request.data.get('codigo', '')),
                                  request.data.get('justificativa', ''))
        return self.retrieve(request, uuid=uuid)


class EvidenciaArquivoView(APIView):
    """Foto/vídeo só pela API, depois de checar quem pede."""
    permission_classes = [NoModulo]

    def get(self, request, uuid):
        e = get_object_or_404(Evidencia.objects.select_related('vistoria__equipamento', 'suspensao__equipamento',
                                                               'nc_critica__suspensao__equipamento'), uuid=uuid)
        eq = (e.vistoria.equipamento if e.vistoria_id else e.suspensao.equipamento if e.suspensao_id
              else e.nc_critica.suspensao.equipamento)
        if not equipamentos_visiveis(request.user).filter(pk=eq.pk).exists():
            raise Http404
        try:
            arq = e.arquivo.open('rb')
        except FileNotFoundError:
            raise Http404
        resp = FileResponse(arq, content_type=e.content_type)
        resp['Cache-Control'] = 'private, max-age=86400'
        return resp


# ── Suspensões ─────────────────────────────────────────────────────────────────
class SuspensaoViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = SuspensaoSerializer
    permission_classes = [NoModulo]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = (Suspensao.objects.filter(filtro_equipamentos(self.request.user, 'equipamento__'))
              .select_related('equipamento__unidade', 'equipamento__setor', 'equipamento__gerente', 'vistoria__avaliador',
                              'liberada_por')
              .prefetch_related('ncs__resposta__evidencias', 'ncs__evidencias', 'ncs__corrigida_por', 'ncs__validada_por',
                                'emails', 'evidencias'))
        p = self.request.query_params
        if p.get('abertas') in ('1', 'true'):
            qs = qs.filter(status__in=(Suspensao.SUSPENSA, Suspensao.AGUARDANDO))
        if p.get('status'):
            qs = qs.filter(status__in=p['status'].split(','))
        if p.get('equipamento'):
            qs = qs.filter(equipamento_id=p['equipamento'])
        if p.get('desde'):
            qs = qs.filter(Q(liberada_em__date__gte=p['desde']) | Q(iniciada_em__date__gte=p['desde']))
        if p.get('ate'):
            qs = qs.filter(iniciada_em__date__lte=p['ate'])
        return qs

    @action(detail=True, methods=['post'])
    def adesivo(self, request, pk=None):
        s = self.get_object()
        afixado = str(request.data.get('afixado')).lower() in ('1', 'true', 'sim')
        foto = request.FILES.get('foto')
        with transaction.atomic():
            execucao.registrar_adesivo(s, request.user, afixado, request.data.get('justificativa', ''))
            if foto:
                conteudo, tipo, ct = processar_midia(foto)
                e = Evidencia(finalidade=Evidencia.ADESIVO, suspensao=s, vistoria=s.vistoria, tipo=tipo, content_type=ct,
                              tamanho=conteudo.size, enviada_por=request.user)
                e.arquivo.save(conteudo.name, conteudo, save=False)
                e.save()
        return Response(self.get_serializer(self.get_queryset().get(pk=s.pk)).data)

    @action(detail=True, methods=['post'])
    def liberar(self, request, pk=None):
        if not pode_liberar(request.user):
            raise PermissionDenied('Só SESMT ou Gerente Executivo Operacional liberam.')
        execucao.liberar(self.get_object(), request.user, request.data.get('observacao', ''))
        return Response(self.get_serializer(self.get_queryset().get(pk=pk)).data)

    @action(detail=True, methods=['post'], url_path=r'ncs/(?P<nc>\d+)/correcao')
    def correcao(self, request, pk=None, nc=None):
        if not pode_corrigir(request.user):
            raise PermissionDenied('Só PCM ou Gerente Executivo Operacional registram correção.')
        s = self.get_object()
        n = get_object_or_404(s.ncs, pk=nc)
        execucao.registrar_correcao(n, request.user, request.data.get('correcao', ''))
        return Response(self.get_serializer(self.get_queryset().get(pk=s.pk)).data)

    @action(detail=True, methods=['post'], url_path=r'ncs/(?P<nc>\d+)/evidencias')
    def evidencia_correcao(self, request, pk=None, nc=None):
        if not pode_corrigir(request.user):
            raise PermissionDenied()
        s = self.get_object()
        n = get_object_or_404(s.ncs, pk=nc)
        if not s.aberta or n.status not in (NCCritica.PENDENTE, NCCritica.CORRIGIDA):
            raise ValidationError({'detail': 'Essa NC não aceita comprovação agora.'})
        ev_uuid = request.data.get('uuid')
        if ev_uuid and Evidencia.objects.filter(uuid=ev_uuid).exists():
            return Response(EvidenciaSerializer(Evidencia.objects.get(uuid=ev_uuid)).data)
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            raise ValidationError({'arquivo': 'Envie a foto ou o vídeo.'})
        conteudo, tipo, ct = processar_midia(arquivo)
        extra = {'uuid': ev_uuid} if ev_uuid else {}
        e = Evidencia(**extra, finalidade=Evidencia.CORRECAO, nc_critica=n, tipo=tipo, content_type=ct,
                      tamanho=conteudo.size, enviada_por=request.user)
        e.arquivo.save(conteudo.name, conteudo, save=False)
        e.save()
        return Response(EvidenciaSerializer(e).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path=r'ncs/(?P<nc>\d+)/rejeitar')
    def rejeitar(self, request, pk=None, nc=None):
        if not pode_liberar(request.user):
            raise PermissionDenied('Só SESMT ou Gerente Executivo Operacional.')
        s = self.get_object()
        execucao.rejeitar_correcao(get_object_or_404(s.ncs, pk=nc), request.user, request.data.get('justificativa', ''))
        return Response(self.get_serializer(self.get_queryset().get(pk=s.pk)).data)

    @action(detail=True, methods=['post'], url_path=r'emails/(?P<email>\d+)/reenviar')
    def reenviar(self, request, pk=None, email=None):
        if not eh_gestor(request.user):
            raise PermissionDenied()
        from . import avisos
        e = get_object_or_404(EmailVistoria, pk=email, suspensao_id=pk)
        if e.enviado_em:
            novo = EmailVistoria.objects.create(tipo=e.tipo, suspensao=e.suspensao, resposta=e.resposta, assunto=e.assunto,
                                                destinatarios='; '.join(avisos.destinatarios(e.suspensao)))
            e = novo
        ok = avisos.enviar(e.pk)
        servicos.auditar(request.user, 'email_reenviar', 'suspensao', pk, e.assunto)
        return Response({'ok': ok})


# ── Painel ─────────────────────────────────────────────────────────────────────
class PainelView(APIView):
    permission_classes = [NoModulo]

    def get(self, request):
        p = request.query_params
        hoje = timezone.localdate()
        ano, mes = _int(p.get('ano'), hoje.year), _int(p.get('mes'), hoje.month)
        eqs = filtrar_equipamentos(equipamentos_visiveis(request.user), p)
        itens = (ProgramaItem.objects.filter(ano=ano, mes=mes, equipamento__in=eqs, situacao__in=servicos.ATIVOS_NO_PROGRAMA)
                 .prefetch_related('vistorias', 'impedimentos'))
        cont = {'programadas': 0, 'realizadas': 0, 'pendentes': 0, 'atrasadas': 0, 'dispensadas': 0,
                'aguardando_validacao': 0, 'impedimentos': 0, 'em_andamento': 0}
        for it in itens:
            cont['programadas'] += 1
            c = servicos.situacao_item(it, list(it.vistorias.all()), list(it.impedimentos.all()), hoje)['codigo']
            if c == 'D':
                cont['dispensadas'] += 1
            elif c in ('R', 'V'):
                cont['realizadas'] += 1
            elif c == 'A' or (c == 'I' and regras.mes_encerrado(ano, mes, hoje)):
                cont['atrasadas'] += 1
            else:
                cont['pendentes'] += 1
            if c == 'I':
                cont['impedimentos'] += 1
            if c == 'E':
                cont['em_andamento'] += 1
        cont['aguardando_validacao'] = Vistoria.objects.filter(equipamento__in=eqs, status=Vistoria.CONCLUIDA).count()
        # situação dos equipamentos (agora)
        ativos = eqs.filter(ativo=True)
        susp = mapa_suspensoes(list(ativos.values_list('id', flat=True)))
        sit = {'OPERACAO': 0, 'MANUTENCAO': 0, 'SUSPENSO': 0, 'AGUARDANDO_LIBERACAO': 0}
        for e in ativos:
            sit[situacao_equipamento(e, susp.get(e.pk))] += 1
        ini, fim = regras.limites_do_mes(ano, mes)
        liberados = Suspensao.objects.filter(equipamento__in=eqs, status=Suspensao.LIBERADA, liberada_em__range=(ini, fim)).count()
        situacao = {'em_operacao': sit['OPERACAO'], 'em_manutencao': sit['MANUTENCAO'],
                    'suspensos': sit['SUSPENSO'] + sit['AGUARDANDO_LIBERACAO'],
                    'aguardando_liberacao': sit['AGUARDANDO_LIBERACAO'], 'liberados_no_periodo': liberados,
                    'ativos': ativos.count()}
        # Indicador: recorte com o vínculo do mês
        filtros = {k: p.get(k) for k in ('unidade', 'setor', 'gerente', 'tipo')}
        base = equipamentos_visiveis(request.user)
        t = regras.trimestre_do_mes(mes)
        dados = indicador.apurar_ano(ano, filtros, base)
        ind_mes = dados['indicadores'].get(mes)
        tri = dados['trimestres'].get(t)
        serie = dados['indicadores']
        ncs_mes = (Resposta.objects.filter(vistoria__equipamento__in=eqs, valor=Resposta.NC, cancelada=False,
                                           vistoria__concluida_em__range=(ini, fim))
                   .values_list('criticidade', flat=True))
        por_crit = {'LEVE': 0, 'MEDIA': 0, 'CRITICA': 0}
        for c in ncs_mes:
            por_crit[c] += 1
        return Response({
            'ano': ano, 'mes': mes, 'programa': cont, 'situacao': situacao, 'suspensos': resumo_suspensos(eqs),
            'indicador_mes': ind_mes, 'indicador_trimestre': tri, 'trimestre': t,
            'serie': [{'mes': m, 'percentual': v['percentual'], 'fechado': v['fechado']} for m, v in sorted(serie.items())],
            'ncs_mes': por_crit,
        })


# ── Resultados ─────────────────────────────────────────────────────────────────
class ResultadosView(APIView):
    permission_classes = [NoModulo]

    def get(self, request):
        p = request.query_params
        ano = _int(p.get('ano'), timezone.localdate().year)
        filtros = {k: p.get(k) for k in ('unidade', 'setor', 'gerente', 'tipo')}
        eqs = equipamentos_visiveis(request.user)
        if p.get('periodicidade'):
            eqs = eqs.filter(periodicidade=p['periodicidade'])
        return Response(indicador.apurar_ano(ano, filtros, eqs))


class ResultadosResumoView(APIView):
    permission_classes = [NoModulo]

    def get(self, request):
        p = request.query_params
        hoje = timezone.localdate()
        ano, mes = _int(p.get('ano'), hoje.year), _int(p.get('mes'), hoje.month)
        por = p.get('por') if p.get('por') in ('unidade', 'setor', 'gerente', 'tipo') else 'setor'
        filtros = {k: p.get(k) for k in ('unidade', 'setor', 'gerente', 'tipo')}
        return Response(indicador.resumo_por(ano, mes, por, equipamentos_visiveis(request.user), filtros))


class FechamentoView(APIView):
    permission_classes = [Gestao]

    def post(self, request):
        acao = request.data.get('acao')
        ano = _int(request.data.get('ano'))
        if acao == 'fechar_mes':
            indicador.fechar_mes(ano, _int(request.data.get('mes')), request.user)
        elif acao == 'reabrir_mes':
            indicador.reabrir_mes(ano, _int(request.data.get('mes')), request.user, request.data.get('justificativa', ''))
        elif acao == 'fechar_trimestre':
            indicador.fechar_trimestre(ano, _int(request.data.get('trimestre')), request.user)
        else:
            raise ValidationError({'acao': 'Ação inválida.'})
        return Response({'ok': True})


class AuditoriaView(APIView):
    permission_classes = [Gestao]

    def get(self, request):
        p = request.query_params
        qs = Auditoria.objects.select_related('usuario')
        if p.get('objeto'):
            qs = qs.filter(objeto=p['objeto'])
        if p.get('objeto_id'):
            qs = qs.filter(objeto_id=p['objeto_id'])
        if p.get('acao'):
            qs = qs.filter(acao=p['acao'])
        if p.get('usuario'):
            qs = qs.filter(usuario_id=p['usuario'])
        if p.get('desde'):
            qs = qs.filter(quando__date__gte=p['desde'])
        if p.get('ate'):
            qs = qs.filter(quando__date__lte=p['ate'])
        if p.get('q'):
            qs = qs.filter(descricao__icontains=p['q'])
        return Response([{'id': a.id, 'quando': a.quando, 'usuario': nome(a.usuario), 'acao': a.acao, 'objeto': a.objeto,
                          'objeto_id': a.objeto_id, 'descricao': a.descricao, 'dados': a.dados}
                         for a in qs[:int(p.get('limite') or 500)]])
