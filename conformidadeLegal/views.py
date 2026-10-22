import logging
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from kanban.models import KanbanColumn, KanbanTask

from . import avisos, ia, importar_relatorio, matriz, normas_tecnicas, relatorio_anual
from .models import (
    TEMAS, ConfiguracaoMonitor, EvidenciaAnexo, ExecucaoMonitor, ExtracaoIA, MatrizItem, MatrizVinculo, MatrizVinculoNorma, Norma, OrgaoMonitor, PalavraChaveMonitor,
    PlanoAcao, PublicacaoMonitorada, Requisito, Terceiro, DocumentoTerceiro, Verificacao, ConfiguracaoAvisos,
)
from .permissions import IsConformidade
from .serializers import nome_usuario
from .serializers import (
    TerceiroSerializer, DocumentoTerceiroSerializer, ConfiguracaoAvisosSerializer,
    ConfiguracaoMonitorSerializer, ExecucaoMonitorSerializer, ExtracaoIASerializer, NormaSerializer,
    OrgaoMonitorSerializer, PalavraChaveSerializer, PlanoAcaoSerializer, PublicacaoDetalheSerializer,
    PublicacaoSerializer, RequisitoSerializer, VerificacaoSerializer,
)
from .tasks import extrair_requisitos, monitorar_diarios

logger = logging.getLogger(__name__)

RESULTADOS_VALIDOS = {r for r, _ in Verificacao.RESULTADOS}
TIPOS_COM_VALIDADE = ('LICENCA', 'OUTORGA', 'TAC')
# Plano em aberto: nem concluído à mão nem com a tarefa do Kanban concluída.
PLANO_ABERTO = Q(concluido_em__isnull=True) & (Q(tarefa__isnull=True) | Q(tarefa__concluido_em__isnull=True))


def _data(valor, campo):
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ValidationError({campo: 'Data inválida (use AAAA-MM-DD).'})


def _usuario(valor, campo):
    if valor in (None, '', 'null'):
        return None
    try:
        return User.objects.get(pk=int(valor))
    except (User.DoesNotExist, ValueError, TypeError):
        raise ValidationError({campo: 'Usuário não encontrado.'})


def _criar_tarefa_kanban(plano: PlanoAcao, coluna_id, usuario) -> KanbanTask:
    """Põe o plano de ação num quadro do Kanban, onde o dia a dia acontece."""
    try:
        coluna = KanbanColumn.objects.select_related('quadro').get(pk=int(coluna_id))
    except (KanbanColumn.DoesNotExist, ValueError, TypeError):
        raise ValidationError({'coluna_id': 'Lista do Kanban não encontrada.'})
    quadro = coluna.quadro
    if not (usuario.is_superuser or quadro.criado_por_id == usuario.id
            or quadro.membros.filter(pk=usuario.pk).exists()):
        raise ValidationError({'coluna_id': 'Você não participa deste quadro do Kanban.'})

    req = plano.requisito
    ref = f' ({req.referencia})' if req.referencia else ''
    descricao = (
        f'{plano.descricao}\n\n'
        f'Requisito legal: {req.norma.identificacao}{ref}\n'
        f'{req.descricao}'
    )
    tarefa = KanbanTask.objects.create(
        coluna=coluna,
        dono=usuario,
        responsavel=plano.responsavel,
        titulo=f'[Conformidade] {plano.descricao[:200]}',
        descricao=descricao,
        prioridade='alta' if req.situacao == 'NAO_ATENDIDO' else 'media',
        tags=['Conformidade Legal'],
        prazo=plano.prazo,
    )
    plano.tarefa = tarefa
    plano.save(update_fields=['tarefa'])
    return tarefa


class NormaViewSet(viewsets.ModelViewSet):
    permission_classes = [IsConformidade]
    serializer_class = NormaSerializer

    def get_queryset(self):
        qs = Norma.objects.select_related('unidade').annotate(total_requisitos=Count('requisitos', filter=Q(requisitos__ativo=True)))
        p = self.request.query_params
        qs = avisos.da_unidade(qs, p.get('unidade'))
        for campo in ('tema', 'esfera', 'situacao', 'tipo'):
            if p.get(campo):
                qs = qs.filter(**{campo: p[campo]})
        if p.get('q'):
            termo = p['q'].strip()
            qs = qs.filter(Q(ementa__icontains=termo) | Q(numero__icontains=termo) | Q(orgao__icontains=termo))
        return qs

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    def perform_update(self, serializer):
        norma = serializer.save()
        # Licença passou a ser de uma unidade: as condicionantes dela vão junto.
        if 'unidade' in serializer.validated_data and norma.unidade_id:
            Requisito.objects.filter(norma=norma).exclude(unidade=norma.unidade_id).update(unidade=norma.unidade_id)

    @staticmethod
    def _impacto(norma) -> dict:
        """O que sai junto com a norma: requisitos e, deles, verificações, evidências e planos de ação."""
        planos = PlanoAcao.objects.filter(requisito__norma=norma)
        return {
            'requisitos': Requisito.objects.filter(norma=norma).count(),
            'verificacoes': Verificacao.objects.filter(requisito__norma=norma).count(),
            'evidencias': EvidenciaAnexo.objects.filter(verificacao__requisito__norma=norma).count(),
            'planos': planos.count(),
            # A tarefa do Kanban fica (o vínculo é do plano para a tarefa); só perde a referência.
            'planos_com_tarefa': planos.filter(tarefa__isnull=False).count(),
            'extracoes_ia': norma.extracoes.count(),
        }

    @action(detail=True, methods=['get'])
    def exclusao(self, request, pk=None):
        """Prévia da exclusão: quanto vai junto. A tela mostra antes de confirmar."""
        return Response(self._impacto(self.get_object()))

    def destroy(self, request, *args, **kwargs):
        """
        Exclui a norma COM os requisitos (e verificações, evidências e planos deles, em cascata).
        Com requisitos, exige ``?com_requisitos=1`` — confirmação explícita, para uma chamada solta
        não apagar o histórico de auditoria. Os arquivos (PDF da norma e anexos das evidências) saem
        do disco depois que o banco confirmou.
        """
        norma = self.get_object()
        impacto = self._impacto(norma)
        if impacto['requisitos'] and str(request.query_params.get('com_requisitos', '')).lower() not in ('1', 'true', 'sim'):
            return Response({
                'detail': f"Esta norma tem {impacto['requisitos']} requisito(s). Confirme a exclusão junto com eles.",
                'impacto': impacto,
            }, status=status.HTTP_409_CONFLICT)
        arquivos = [f for f in EvidenciaAnexo.objects.filter(verificacao__requisito__norma=norma).values_list('arquivo', flat=True) if f]
        if norma.arquivo:
            arquivos.append(norma.arquivo.name)
        # O logo do relatório pode ter sido copiado para outra norma: só sai se ninguém mais usa.
        logo = norma.relatorio_logo.name if norma.relatorio_logo else None
        identificacao, pk = str(norma), norma.pk
        with transaction.atomic():
            Requisito.objects.filter(norma=norma).delete()
            norma.delete()
        if logo and not Norma.objects.filter(relatorio_logo=logo).exists():
            arquivos.append(logo)
        for nome in arquivos:
            if not EvidenciaAnexo.objects.filter(arquivo=nome).exists() and not Norma.objects.filter(arquivo=nome).exists():
                try:
                    default_storage.delete(nome)
                except OSError:
                    logger.warning('Conformidade: arquivo %s não pôde ser apagado do disco', nome)
        logger.info('Conformidade: norma %s (%s) excluída por %s com %s', pk, identificacao, request.user, impacto)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get', 'post'], url_path='extracao-ia')
    def extracao_ia(self, request, pk=None):
        """
        GET: a extração mais recente desta norma (ou null). POST: pede uma nova
        leitura do PDF anexado. Roda no Celery — um PDF longo leva minutos, mais
        que o timeout do gunicorn — e a tela acompanha pelo GET.
        """
        norma = self.get_object()
        if request.method == 'GET':
            ultima = norma.extracoes.first()
            if ultima and ultima.status == 'CONCLUIDA' and ultima.normas_citadas is None:
                _preencher_nbrs_pela_regex(ultima)
            return Response({
                'configurada': ia.configurada(),
                'extracao': ExtracaoIASerializer(ultima).data if ultima else None,
                'total_paginas': _total_paginas(norma),
            })

        if not ia.configurada():
            return Response({'detail': 'A IA ainda não foi configurada no servidor.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not norma.arquivo or not norma.arquivo.name.lower().endswith('.pdf'):
            raise ValidationError({'detail': 'Anexe o PDF do documento à norma antes de pedir a leitura.'})
        em_andamento = norma.extracoes.filter(status='PROCESSANDO').first()
        if em_andamento:
            return Response(ExtracaoIASerializer(em_andamento).data, status=status.HTTP_202_ACCEPTED)

        # Páginas opcionais ("20-21, 24-35"): validadas aqui para o erro voltar na hora,
        # e não minutos depois como extração com status ERRO.
        texto_paginas = (request.data.get('paginas') or '').strip()
        paginas = ''
        if texto_paginas:
            total = _total_paginas(norma)
            if not total:
                raise ValidationError({'paginas': 'Não foi possível contar as páginas deste PDF.'})
            try:
                paginas = ia.descrever_paginas(ia.interpretar_paginas(texto_paginas, total))
            except ia.PaginasInvalidas as e:
                raise ValidationError({'paginas': str(e)})

        extracao = ExtracaoIA.objects.create(norma=norma, criado_por=request.user, modelo=ia.modelo(),
                                             paginas=paginas)
        transaction.on_commit(lambda: extrair_requisitos.delay(extracao.id))
        return Response(ExtracaoIASerializer(extracao).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'], url_path='monitorar-nbr')
    def monitorar_nbr(self, request, pk=None):
        """
        Põe NBRs citadas por esta norma no monitor das Novidades legais: uma palavra-chave
        por NBR, valendo para ato de qualquer órgão do DOU. ``{"codigos": ["ABNT NBR 10004", ...]}``.
        A que já existe é reativada (e passa a valer em qualquer órgão), sem duplicar.
        """
        norma = self.get_object()
        codigos = request.data.get('codigos') or []
        if not isinstance(codigos, list) or not codigos:
            raise ValidationError({'codigos': 'Informe ao menos uma NBR.'})
        criadas, reativadas = [], []
        with transaction.atomic():
            for codigo in codigos[:200]:
                item = normas_tecnicas.canonico(str(codigo))
                if not item:
                    continue
                rotulo = normas_tecnicas.rotulo_monitor(item)
                palavra, nova = PalavraChaveMonitor.objects.get_or_create(rotulo=rotulo, defaults={
                    'termos': normas_tecnicas.termos_monitor(item), 'qualquer_orgao': True, 'norma_origem': norma})
                if nova:
                    criadas.append(rotulo)
                elif not (palavra.ativo and palavra.qualquer_orgao):
                    palavra.ativo, palavra.qualquer_orgao = True, True
                    palavra.save(update_fields=['ativo', 'qualquer_orgao', 'atualizado_em'])
                    reativadas.append(rotulo)
        if not criadas and not reativadas and not any(normas_tecnicas.canonico(str(c)) for c in codigos):
            raise ValidationError({'codigos': 'Nenhum código de NBR reconhecido.'})
        ultima = norma.extracoes.first()
        return Response({'criadas': criadas, 'reativadas': reativadas,
                         'extracao': ExtracaoIASerializer(ultima).data if ultima else None})

    # ── Relatório Anual de Acompanhamento ───────────────────────────────

    def _periodo_relatorio(self, request):
        inicio_padrao, fim_padrao = relatorio_anual.periodo_padrao()
        inicio = _data(request.query_params.get('inicio'), 'inicio') or inicio_padrao
        fim = _data(request.query_params.get('fim'), 'fim') or fim_padrao
        if inicio > fim:
            raise ValidationError({'inicio': 'O início do período é depois do fim.'})
        return inicio, fim

    def _montar_relatorio(self, norma, request):
        inicio, fim = self._periodo_relatorio(request)
        return relatorio_anual.montar(norma, inicio, fim, url_de=lambda a: request.build_absolute_uri(a.arquivo.url))

    @action(detail=True, methods=['get', 'patch'], url_path='relatorio-anual')
    def relatorio_anual_previa(self, request, pk=None):
        """
        GET ?inicio=&fim=: prévia do relatório (condicionantes na ordem, resposta do
        período, fotos, o que falta). PATCH: salva capa/apresentação da licença.
        """
        norma = self.get_object()
        if request.method == 'PATCH':
            norma.relatorio_anual = {**(norma.relatorio_anual or {}),
                                     **relatorio_anual.limpar_configuracao(request.data)}
            norma.save(update_fields=['relatorio_anual', 'atualizado_em'])
        return Response(relatorio_anual.para_json(self._montar_relatorio(norma, request)))

    @action(detail=True, methods=['get'], url_path='relatorio-anual/arquivo')
    def relatorio_anual_arquivo(self, request, pk=None):
        """O documento: ?formato=docx (padrão) ou pdf, com o mesmo período da prévia."""
        norma = self.get_object()
        formato = (request.query_params.get('formato') or 'docx').lower()
        if formato not in ('docx', 'pdf'):
            raise ValidationError({'formato': 'Use docx ou pdf.'})
        dados = self._montar_relatorio(norma, request)
        if formato == 'pdf':
            conteudo, tipo = relatorio_anual.gerar_pdf(dados), 'application/pdf'
        else:
            conteudo = relatorio_anual.gerar_docx(dados)
            tipo = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        resposta = HttpResponse(conteudo, content_type=tipo)
        resposta['Content-Disposition'] = f'attachment; filename="{relatorio_anual.nome_arquivo(dados, formato)}"'
        resposta['Access-Control-Expose-Headers'] = 'Content-Disposition'
        return resposta

    @action(detail=True, methods=['post'], url_path='relatorio-anual/repetir')
    def relatorio_anual_repetir(self, request, pk=None):
        """
        "Nada mudou desde o ano passado": registra de novo a última resposta (atendida)
        das condicionantes escolhidas, com data dentro do período. A verificação nova é
        uma VCL de verdade — quem repetiu e quando ficam gravados, e a observação diz de
        onde o texto veio. ``{"requisitos": [ids], "data": "AAAA-MM-DD", "fotos": bool}``.
        Fotos do ano anterior só vão junto se pedido: foto velha como evidência de hoje
        é justamente o que a fiscalização questiona.
        """
        norma = self.get_object()
        inicio, fim = self._periodo_relatorio(request)
        data_vcl = _data(request.data.get('data'), 'data') or min(fim, date.today())
        if not (inicio <= data_vcl <= fim):
            raise ValidationError({'data': 'A data precisa estar dentro do período do relatório.'})
        if data_vcl > date.today():
            raise ValidationError({'data': 'A verificação não pode ter data futura.'})
        ids = request.data.get('requisitos') or []
        if not isinstance(ids, list) or not ids:
            raise ValidationError({'requisitos': 'Nenhuma condicionante escolhida.'})
        levar_fotos = bool(request.data.get('fotos'))

        repetidas, ignoradas = 0, []
        with transaction.atomic():
            for req in Requisito.objects.filter(norma=norma, pk__in=ids, ativo=True):
                ultima = req.verificacoes.order_by('-data', '-id').first()
                motivo = None
                if req.aplicabilidade != 'APLICAVEL':
                    motivo = 'não está como aplicável'
                elif ultima is None or not ultima.evidencia.strip():
                    motivo = 'não tem resposta anterior'
                elif ultima.data >= inicio:
                    motivo = 'já tem resposta no período'
                elif ultima.resultado != 'ATENDIDO':
                    motivo = 'a última verificação não foi "Atendido"'
                if motivo:
                    ignoradas.append({'requisito': req.pk, 'referencia': req.referencia, 'motivo': motivo})
                    continue
                anexos = list(ultima.anexos.all()) if levar_fotos else []
                _registrar_vcl(req, {
                    'evidencia': ultima.evidencia,
                    'observacao': f'Resposta repetida da verificação de {ultima.data:%d/%m/%Y} (relatório anual).',
                }, 'ATENDIDO', data_vcl, request.user, anexos)
                repetidas += 1

        dados = relatorio_anual.para_json(self._montar_relatorio(norma, request))
        return Response({'repetidas': repetidas, 'ignoradas': ignoradas, 'relatorio': dados})

    @action(detail=True, methods=['post'], url_path='relatorio-anual/legendas')
    def relatorio_anual_legendas(self, request, pk=None):
        """Legenda das fotos ("Figura N: …"): ``{"legendas": {"<anexo id>": "texto"}}``."""
        norma = self.get_object()
        legendas = request.data.get('legendas') or {}
        if not isinstance(legendas, dict) or not legendas:
            raise ValidationError({'legendas': 'Nada para salvar.'})
        try:
            ids = {int(k): str(v or '').strip()[:300] for k, v in legendas.items()}
        except (TypeError, ValueError):
            raise ValidationError({'legendas': 'Identificador de foto inválido.'})
        anexos = EvidenciaAnexo.objects.filter(pk__in=ids, verificacao__requisito__norma=norma)
        if anexos.count() != len(ids):
            raise ValidationError({'legendas': 'Alguma foto não pertence a esta licença.'})
        for a in anexos:
            a.legenda = ids[a.pk]
            a.save(update_fields=['legenda'])
        return Response({'salvas': len(ids)})

    @action(detail=True, methods=['post', 'delete'], url_path='relatorio-anual/logo')
    def relatorio_anual_logo(self, request, pk=None):
        """POST (multipart `arquivo`): logo próprio na capa. DELETE: volta ao logo do grupo."""
        norma = self.get_object()
        if request.method == 'DELETE':
            if norma.relatorio_logo:
                norma.relatorio_logo.delete(save=False)
            norma.relatorio_logo = None
        else:
            arquivo = request.FILES.get('arquivo')
            if not arquivo:
                raise ValidationError({'arquivo': 'Envie a imagem do logo.'})
            if not arquivo.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp')):
                raise ValidationError({'arquivo': 'Use uma imagem PNG ou JPG.'})
            if norma.relatorio_logo:
                norma.relatorio_logo.delete(save=False)
            norma.relatorio_logo = arquivo
        norma.save(update_fields=['relatorio_logo', 'atualizado_em'])
        return Response(relatorio_anual.para_json(self._montar_relatorio(norma, request)))

    @action(detail=True, methods=['post'], url_path='relatorio-anual/importar')
    def relatorio_anual_importar(self, request, pk=None):
        """
        Importa as respostas de um relatório anual já entregue (PDF do Word). Multipart:
        `arquivo`; `aplicar=1` grava (sem ele, só a prévia); `data` das verificações
        (padrão: o mês da capa); `criar_faltantes`, `tirar_ausentes` (padrão 1).
        """
        norma = self.get_object()
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            raise ValidationError({'arquivo': 'Envie o PDF do relatório.'})
        try:
            lido = importar_relatorio.ler(arquivo.read())
        except importar_relatorio.PdfIlegivel as e:
            raise ValidationError({'arquivo': str(e)})
        planejado = importar_relatorio.planejar(norma, lido)
        if request.data.get('aplicar') not in ('1', 'true', True):
            return Response(importar_relatorio.resumo_json(norma, lido, planejado))

        data_vcl = _data(request.data.get('data'), 'data') or lido['data'] or date.today()
        if data_vcl > date.today():
            raise ValidationError({'data': 'A data das verificações não pode ser futura.'})
        sim = lambda campo: request.data.get(campo, '1') not in ('0', 'false', False)  # noqa: E731
        resultado = importar_relatorio.aplicar(
            norma, lido, request.user, data_vcl, criar_faltantes=sim('criar_faltantes'),
            tirar_ausentes=sim('tirar_ausentes'), nome_pdf=arquivo.name)
        norma.refresh_from_db()
        return Response({**resultado, 'data': data_vcl.isoformat(),
                         'relatorio': relatorio_anual.para_json(self._montar_relatorio(norma, request))})


def _preencher_nbrs_pela_regex(extracao):
    """Leitura feita antes das NBRs existirem: acha as citações no texto do PDF, sem gastar IA."""
    norma = extracao.norma
    lista = []
    if norma.arquivo and norma.arquivo.name.lower().endswith('.pdf'):
        try:
            with norma.arquivo.open('rb') as f:
                conteudo = f.read()
            paginas = ia.interpretar_paginas(extracao.paginas, ia.contar_paginas(conteudo)) if extracao.paginas else None
            lista = normas_tecnicas.do_texto(normas_tecnicas.textos_do_pdf(conteudo, paginas))
        except Exception:  # noqa: BLE001 — sem arquivo legível, fica lista vazia
            logger.warning('NBRs da extração %s: PDF ilegível', extracao.id)
    extracao.normas_citadas = lista
    extracao.save(update_fields=['normas_citadas'])


LIMITE_LOTE = 500
# O que a edição em lote pode mudar. Norma, descrição e referência são de cada requisito.
CAMPOS_LOTE = ('secao', 'aplicabilidade', 'justificativa', 'unidade', 'responsavel', 'periodicidade_meses', 'tema', 'ativo', 'terceiros',
               'dias_aviso')


def _validar_vcl(d):
    resultado = d.get('resultado')
    if resultado not in RESULTADOS_VALIDOS:
        raise ValidationError({'resultado': 'Informe Atendido, Parcial ou Não atendido.'})
    data_vcl = _data(d.get('data'), 'data') or date.today()
    if data_vcl > date.today():
        raise ValidationError({'data': 'A verificação não pode ter data futura.'})
    return resultado, data_vcl


def _registrar_vcl(req, d, resultado, data_vcl, usuario, anexos):
    """
    Cria a VCL, liga os anexos e recalcula a situação. `anexos` são uploads (gravados
    agora) ou EvidenciaAnexo já gravados — no lote, o arquivo vai para o disco uma vez
    só e as outras verificações apontam para o mesmo caminho. Devolve (vcl, anexos
    gravados), para o próximo requisito do lote reaproveitar.
    """
    vcl = Verificacao.objects.create(
        requisito=req, data=data_vcl, resultado=resultado,
        evidencia=d.get('evidencia', '') or '', observacao=d.get('observacao', '') or '',
        verificado_por=usuario,
    )
    gravados = []
    for a in anexos:
        if isinstance(a, EvidenciaAnexo):
            gravados.append(EvidenciaAnexo.objects.create(verificacao=vcl, arquivo=a.arquivo.name, nome=a.nome,
                                                          tamanho=a.tamanho, legenda=a.legenda))
        else:
            gravados.append(EvidenciaAnexo.objects.create(verificacao=vcl, arquivo=a, nome=a.name))
    req.recalcular_situacao()
    return vcl, gravados


def _abrir_plano(req, vcl, d, usuario):
    return PlanoAcao.objects.create(
        requisito=req, verificacao=vcl, descricao=d['plano_descricao'].strip(),
        responsavel=_usuario(d.get('plano_responsavel'), 'plano_responsavel') or req.responsavel,
        prazo=_data(d.get('plano_prazo'), 'plano_prazo'), criado_por=usuario,
        # Sem escolha na tela, o plano fica com o prestador do requisito.
        terceiro=_terceiro(d.get('plano_terceiro')) or _terceiro_unico(req),
    )


def _terceiro_unico(req):
    """Sem escolha na tela, o plano fica com o prestador do requisito — se for um só."""
    terceiros = list(req.terceiros.all()[:2])
    return terceiros[0] if len(terceiros) == 1 else None


def _terceiro(valor):
    if valor in (None, '', 'null'):
        return None
    try:
        return Terceiro.objects.get(pk=int(valor))
    except (ValueError, Terceiro.DoesNotExist):
        raise ValidationError({'plano_terceiro': 'Terceiro não encontrado.'})


def _total_paginas(norma) -> int | None:
    """Páginas do PDF da norma; None quando não há PDF ou ele não abre."""
    if not norma.arquivo or not norma.arquivo.name.lower().endswith('.pdf'):
        return None
    try:
        with norma.arquivo.open('rb') as f:
            return ia.contar_paginas(f.read())
    except Exception:  # noqa: BLE001 — PDF corrompido não pode derrubar a tela
        return None


class RequisitoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsConformidade]
    serializer_class = RequisitoSerializer

    def get_queryset(self):
        qs = (Requisito.objects
              .select_related('norma', 'responsavel__colaborador', 'unidade')
              .prefetch_related('terceiros')
              .annotate(planos_abertos=Count('planos', filter=Q(planos__concluido_em__isnull=True)
                                             & (Q(planos__tarefa__isnull=True) | Q(planos__tarefa__concluido_em__isnull=True)))))
        p = self.request.query_params
        if p.get('ativo', '1') != 'todos':
            qs = qs.filter(ativo=True)
        for campo in ('norma', 'tema', 'aplicabilidade', 'situacao', 'responsavel', 'origem'):
            if p.get(campo):
                qs = qs.filter(**{campo: p[campo]})
        if p.get('terceiro'):
            qs = qs.filter(terceiros=p['terceiro'])
        qs = avisos.da_unidade(qs, p.get('unidade'))
        if p.get('vencidos') == '1':
            qs = qs.filter(aplicabilidade='APLICAVEL', proxima_verificacao__lt=date.today())
        if p.get('q'):
            termo = p['q'].strip()
            qs = qs.filter(Q(descricao__icontains=termo) | Q(referencia__icontains=termo)
                           | Q(norma__ementa__icontains=termo) | Q(norma__numero__icontains=termo)
                           | Q(unidade__nome__icontains=termo) | Q(secao__icontains=termo))
        return qs.order_by('norma__tema', 'norma_id', 'id')

    def perform_create(self, serializer):
        req = serializer.save(criado_por=self.request.user)
        # Sem verificação ainda, o primeiro vencimento é o prazo legal (se houver).
        if req.prazo_legal and not req.proxima_verificacao:
            req.recalcular_situacao()

    def perform_update(self, serializer):
        req = serializer.save()
        # Periodicidade ou prazo legal mudaram: a próxima data precisa acompanhar.
        if {'periodicidade_meses', 'prazo_legal'} & set(serializer.validated_data):
            req.recalcular_situacao()

    @action(detail=False, methods=['get'])
    def resumo(self, request):
        """
        Números do painel. Só requisitos ativos; situação conta só os aplicáveis.
        Filtros opcionais: tema, responsavel, unidade, norma, terceiro. A antecedência
        de cada lista vem da configuração de avisos.
        """
        hoje = date.today()
        filtros = avisos.ler_filtros(request.query_params)
        cfg = ConfiguracaoAvisos.atual()
        ativos = avisos.filtrar_requisitos(Requisito.objects.filter(ativo=True), filtros)
        aplicaveis = ativos.filter(aplicabilidade='APLICAVEL')

        por_situacao = dict(aplicaveis.values_list('situacao').annotate(n=Count('id')))
        avaliados = sum(por_situacao.get(s, 0) for s in ('ATENDIDO', 'PARCIAL', 'NAO_ATENDIDO'))
        rotulos_tema = dict(TEMAS)
        por_tema = []
        for linha in (aplicaveis.values('tema')
                      .annotate(total=Count('id'),
                                atendidos=Count('id', filter=Q(situacao='ATENDIDO')),
                                nao_atendidos=Count('id', filter=Q(situacao='NAO_ATENDIDO')),
                                parciais=Count('id', filter=Q(situacao='PARCIAL')),
                                nao_avaliados=Count('id', filter=Q(situacao='NAO_AVALIADO')))
                      .order_by('-total')):
            linha['rotulo'] = rotulos_tema.get(linha['tema'], linha['tema'])
            por_tema.append(linha)

        planos = avisos.planos_abertos(filtros)
        pend = avisos.pendencias(filtros, hoje)
        a_vencer = sum(1 for r in pend['verificacoes'] if r.proxima_verificacao >= hoje)
        terceiros = _resumo_terceiros(hoje, filtros.get('unidade'))
        if filtros.get('terceiro'):
            terceiros['alertas'] = [a for a in terceiros['alertas'] if str(a['terceiro']) == str(filtros['terceiro'])]

        return Response({
            'filtros': filtros,
            'prazos': {'verificacao': cfg.dias_verificacao, 'plano': cfg.dias_plano,
                       'licenca': cfg.dias_licenca, 'documento': cfg.dias_documento},
            'total': ativos.count(),
            'aplicaveis': aplicaveis.count(),
            'em_analise': ativos.filter(aplicabilidade='EM_ANALISE').count(),
            'nao_aplicaveis': ativos.filter(aplicabilidade='NAO_APLICAVEL').count(),
            'por_situacao': {s: por_situacao.get(s, 0) for s, _ in Requisito.SITUACOES},
            # Parcial conta meio: atendeu a parte, mas o auditor vai apontar o resto.
            'indice_conformidade': round(
                100 * (por_situacao.get('ATENDIDO', 0) + 0.5 * por_situacao.get('PARCIAL', 0)) / avaliados, 1
            ) if avaliados else None,
            'verificacoes_vencidas': aplicaveis.filter(proxima_verificacao__lt=hoje).count(),
            # Dentro da antecedência de cada requisito (a dele ou a geral), ainda não vencidas.
            'verificacoes_a_vencer': a_vencer,
            # Nome antigo, mantido para telas ainda não publicadas.
            'verificacoes_30_dias': a_vencer,
            'planos_abertos': planos.count(),
            'planos_atrasados': planos.filter(prazo__lt=hoje).count(),
            'por_tema': por_tema,
            'validades': [
                {'id': n.id, 'identificacao': n.identificacao, 'ementa': n.ementa, 'validade': n.validade,
                 'dias': (n.validade - hoje).days}
                for n in pend['licencas']
            ],
            'proximas': RequisitoSerializer(pend['verificacoes'][:15], many=True, context={'request': request}).data,
            'planos_proximos': PlanoAcaoSerializer(pend['planos'][:15], many=True, context={'request': request}).data,
            'terceiros': terceiros,
            'unidades': unidades_ativas(),
        })

    @action(detail=True, methods=['post'])
    def verificar(self, request, pk=None):
        """
        Registra uma VCL. Multipart: resultado, data, evidencia, observacao,
        arquivos (vários). Se vier `plano_descricao`, já abre o plano de ação —
        e, com `coluna_id`, a tarefa no Kanban.
        """
        req = self.get_object()
        if req.aplicabilidade != 'APLICAVEL':
            raise ValidationError({'detail': 'Só requisitos aplicáveis são verificados. Defina a aplicabilidade antes.'})
        d = request.data
        resultado, data_vcl = _validar_vcl(d)
        if resultado != 'ATENDIDO' and not (d.get('plano_descricao') or '').strip() \
                and not req.planos.filter(PLANO_ABERTO).exists():
            # Sem plano, o "não atendido" fica parado sem dono — é o que a ISO cobra.
            raise ValidationError({'plano_descricao': 'Descreva o plano de ação para o que não foi atendido.'})

        with transaction.atomic():
            vcl, _ = _registrar_vcl(req, d, resultado, data_vcl, request.user, request.FILES.getlist('arquivos'))
            plano = None
            if (d.get('plano_descricao') or '').strip():
                plano = _abrir_plano(req, vcl, d, request.user)
                if d.get('coluna_id'):
                    _criar_tarefa_kanban(plano, d['coluna_id'], request.user)

        req.refresh_from_db()
        ctx = {'request': request}
        return Response({
            'requisito': RequisitoSerializer(self.get_queryset().get(pk=req.pk), context=ctx).data,
            'verificacao': VerificacaoSerializer(vcl, context=ctx).data,
            'plano': PlanoAcaoSerializer(plano, context=ctx).data if plano else None,
        }, status=status.HTTP_201_CREATED)

    def _requisitos_do_lote(self, valor) -> list:
        """`ids` em lista JSON, repetido no multipart ou "1,2,3" → os requisitos, todos existentes."""
        if hasattr(self.request.data, 'getlist') and len(self.request.data.getlist('ids')) > 1:
            valor = self.request.data.getlist('ids')
        if isinstance(valor, str):
            valor = valor.split(',')
        try:
            ids = {int(i) for i in (valor or []) if str(i).strip()}
        except (TypeError, ValueError):
            raise ValidationError({'ids': 'Lista de requisitos inválida.'})
        if not ids:
            raise ValidationError({'ids': 'Nenhum requisito selecionado.'})
        if len(ids) > LIMITE_LOTE:
            raise ValidationError({'ids': f'No máximo {LIMITE_LOTE} requisitos por vez.'})
        reqs = list(Requisito.objects.filter(pk__in=ids).order_by('id'))
        if len(reqs) != len(ids):
            raise ValidationError({'ids': 'Algum requisito selecionado não existe mais. Recarregue a lista.'})
        return reqs

    @action(detail=False, methods=['post'], url_path='editar-lote')
    def editar_lote(self, request):
        """
        Aplica os mesmos campos a vários requisitos: ``{"ids": [...], "campos": {...}}``.
        Só os campos enviados mudam — é a triagem das sugestões da IA ("estes 15 não se
        aplicam") sem abrir um por um. Tudo ou nada: um inválido desfaz o lote.
        """
        reqs = self._requisitos_do_lote(request.data.get('ids'))
        campos = {k: v for k, v in (request.data.get('campos') or {}).items() if k in CAMPOS_LOTE}
        if not campos:
            raise ValidationError({'campos': 'Nada para alterar.'})
        ctx = {'request': request}
        with transaction.atomic():
            for req in reqs:
                s = RequisitoSerializer(req, data=campos, partial=True, context=ctx)
                s.is_valid(raise_exception=True)
                req = s.save()
                if 'periodicidade_meses' in s.validated_data:
                    req.recalcular_situacao()
        return Response(RequisitoSerializer(self.get_queryset().filter(pk__in=[r.pk for r in reqs]),
                                            many=True, context=ctx).data)

    @action(detail=False, methods=['post'], url_path='verificar-lote')
    def verificar_lote(self, request):
        """
        Mesma VCL para vários requisitos — o caso do laudo único que comprova vários
        itens. Multipart como em `verificar`, mais `ids`. Os anexos são gravados UMA vez
        e ligados a todas as verificações. Fora de "Atendido", requisito sem plano aberto
        ganha um plano com a descrição informada (a tarefa no Kanban, se quiser, sai
        depois pela tela de planos — uma por plano).
        """
        reqs = self._requisitos_do_lote(request.data.get('ids'))
        fora = [r for r in reqs if r.aplicabilidade != 'APLICAVEL']
        if fora:
            raise ValidationError({'ids': f'{len(fora)} dos selecionados não estão como "Aplicável". '
                                          'Só requisitos aplicáveis são verificados.'})
        d = request.data
        resultado, data_vcl = _validar_vcl(d)
        descricao_plano = (d.get('plano_descricao') or '').strip()
        com_plano = set(Requisito.objects.filter(pk__in=[r.pk for r in reqs], planos__in=PlanoAcao.objects.filter(PLANO_ABERTO))
                        .values_list('pk', flat=True))
        if resultado != 'ATENDIDO' and not descricao_plano and any(r.pk not in com_plano for r in reqs):
            raise ValidationError({'plano_descricao': 'Descreva o plano de ação para o que não foi atendido.'})

        planos = 0
        with transaction.atomic():
            anexos = request.FILES.getlist('arquivos')
            for req in reqs:
                vcl, anexos = _registrar_vcl(req, d, resultado, data_vcl, request.user, anexos)
                if resultado != 'ATENDIDO' and descricao_plano and req.pk not in com_plano:
                    _abrir_plano(req, vcl, d, request.user)
                    planos += 1

        return Response({
            'requisitos': RequisitoSerializer(self.get_queryset().filter(pk__in=[r.pk for r in reqs]), many=True,
                                              context={'request': request}).data,
            'verificacoes': len(reqs),
            'planos': planos,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='criar-lote')
    def criar_lote(self, request):
        """
        Cria vários requisitos de uma norma de uma vez (a tela de revisão da
        extração por IA manda os itens aprovados). ``{"norma": id, "itens": [...]}``.
        """
        norma_id = request.data.get('norma')
        itens = request.data.get('itens') or []
        if not isinstance(itens, list) or not itens:
            raise ValidationError({'itens': 'Nenhum requisito recebido.'})
        criados = []
        with transaction.atomic():
            for item in itens:
                s = RequisitoSerializer(data={**item, 'norma': norma_id}, context={'request': request})
                s.is_valid(raise_exception=True)
                req = s.save(criado_por=request.user)
                if req.prazo_legal:
                    req.recalcular_situacao()
                criados.append(req.pk)
        return Response(RequisitoSerializer(self.get_queryset().filter(pk__in=criados), many=True,
                                            context={'request': request}).data, status=status.HTTP_201_CREATED)


class VerificacaoViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin,
                         viewsets.GenericViewSet):
    """Histórico. Criar é pelo `requisitos/{id}/verificar/`; editar não existe —
    VCL errada se apaga e registra de novo, para a trilha ficar honesta."""

    permission_classes = [IsConformidade]
    serializer_class = VerificacaoSerializer

    def get_queryset(self):
        qs = Verificacao.objects.select_related('verificado_por__colaborador').prefetch_related('anexos')
        if self.request.query_params.get('requisito'):
            qs = qs.filter(requisito=self.request.query_params['requisito'])
        return qs

    def perform_destroy(self, instance):
        req = instance.requisito
        anexos = list(instance.anexos.all())
        instance.delete()
        # A verificação em lote liga o MESMO arquivo a várias verificações: só sai do
        # disco quando a última que aponta para ele for embora.
        for anexo in anexos:
            if not EvidenciaAnexo.objects.filter(arquivo=anexo.arquivo.name).exists():
                anexo.arquivo.delete(save=False)
        req.recalcular_situacao()


class PlanoAcaoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsConformidade]
    serializer_class = PlanoAcaoSerializer

    def get_queryset(self):
        qs = PlanoAcao.objects.select_related(
            'requisito__norma', 'responsavel__colaborador', 'tarefa__coluna__quadro', 'terceiro')
        p = self.request.query_params
        if p.get('requisito'):
            qs = qs.filter(requisito=p['requisito'])
        if p.get('terceiro'):
            qs = qs.filter(terceiro=p['terceiro'])
        if p.get('abertos') == '1':
            qs = qs.filter(PLANO_ABERTO)
        return avisos.da_unidade(qs, p.get('unidade'), 'requisito__unidade')

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    @action(detail=True, methods=['post'], url_path='gerar-tarefa')
    def gerar_tarefa(self, request, pk=None):
        plano = self.get_object()
        if plano.tarefa_id:
            raise ValidationError({'detail': 'Este plano já tem tarefa no Kanban.'})
        _criar_tarefa_kanban(plano, request.data.get('coluna_id'), request.user)
        return Response(self.get_serializer(self.get_queryset().get(pk=plano.pk)).data)

    @action(detail=True, methods=['post'])
    def concluir(self, request, pk=None):
        plano = self.get_object()
        plano.concluido_em = None if request.data.get('reabrir') else timezone.now()
        plano.save(update_fields=['concluido_em'])
        return Response(self.get_serializer(plano).data)


def unidades_ativas() -> list:
    """Filiais ativas do cadastro da Gestão de Pessoas — a Matriz primeiro."""
    from avaliacoes.management.models import Filial
    lista = [{'id': f.id, 'nome': f.nome, 'cidade': f.cidade, 'estado': f.estado}
             for f in Filial.objects.filter(ativa=True)]
    return sorted(lista, key=lambda u: (u['nome'].lower() != 'matriz', u['nome'].lower()))


class UnidadesView(APIView):
    """Unidades para o seletor do módulo (matriz, filiais)."""
    permission_classes = [IsConformidade]

    def get(self, request):
        return Response(unidades_ativas())


class ResponsaveisView(APIView):
    """
    Pessoas que podem ser responsáveis por requisito ou plano: usuários ativos, com o
    nome do cadastro de colaboradores. Própria do módulo — a lista geral de usuários
    (management/get_users) é usada pelo Kanban e mostra o login.
    """

    permission_classes = [IsConformidade]

    def get(self, request):
        import unicodedata
        usuarios = User.objects.filter(is_active=True).select_related('colaborador')
        lista = [{'id': u.id, 'nome': nome_usuario(u), 'login': u.username} for u in usuarios]

        def chave(item):
            sem_acento = unicodedata.normalize('NFKD', item['nome']).encode('ascii', 'ignore').decode()
            return sem_acento.casefold()

        return Response(sorted(lista, key=chave))


class PublicacaoViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Novidades legais: o que a coleta dos diários oficiais achou. A equipe descarta ou
    cadastra como norma; nada é criado sem essa decisão.
    """

    permission_classes = [IsConformidade]

    def get_serializer_class(self):
        return PublicacaoDetalheSerializer if self.action == 'retrieve' else PublicacaoSerializer

    def get_queryset(self):
        qs = PublicacaoMonitorada.objects.select_related('norma', 'avaliado_por__colaborador')
        p = self.request.query_params
        for campo in ('status', 'relevancia', 'fonte'):
            if p.get(campo):
                qs = qs.filter(**{campo: p[campo]})
        if p.get('dias'):
            try:
                qs = qs.filter(data_publicacao__gte=date.today() - timedelta(days=int(p['dias'])))
            except ValueError:
                pass
        return qs

    def _avaliar(self, pub, status_novo, request, **extra):
        pub.status = status_novo
        pub.avaliado_por = request.user if status_novo != 'NOVA' else None
        pub.avaliado_em = timezone.now() if status_novo != 'NOVA' else None
        for k, v in extra.items():
            setattr(pub, k, v)
        pub.save()
        return Response(PublicacaoSerializer(pub, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def descartar(self, request, pk=None):
        return self._avaliar(self.get_object(), 'DESCARTADA', request,
                             motivo_descarte=(request.data.get('motivo') or '').strip()[:2000])

    @action(detail=True, methods=['post'])
    def reabrir(self, request, pk=None):
        pub = self.get_object()
        if pub.status == 'CADASTRADA':
            raise ValidationError({'detail': 'Já virou norma. Para desfazer, exclua ou revogue a norma.'})
        return self._avaliar(pub, 'NOVA', request, motivo_descarte='')

    @action(detail=True, methods=['post'], url_path='cadastrar-norma')
    def cadastrar_norma(self, request, pk=None):
        """
        Cria a norma a partir da publicação: tipo, número, ano e órgão tirados do
        título, link oficial e um PDF com o texto publicado — pronto para a leitura
        por IA. A tela abre a norma em seguida para a pessoa revisar.
        """
        from django.core.files.base import ContentFile
        from . import monitor

        pub = self.get_object()
        if pub.status == 'CADASTRADA' and pub.norma_id:
            raise ValidationError({'detail': 'Esta publicação já foi cadastrada como norma.'})
        with transaction.atomic():
            norma = Norma(**monitor.dados_de_norma(pub), criado_por=request.user)
            nome = f'{pub.fonte.lower()}_{pub.data_publicacao:%Y%m%d}_{pub.id_externo}.pdf'
            norma.arquivo.save(nome, ContentFile(monitor.pdf_da_publicacao(pub)), save=False)
            norma.save()
            self._avaliar(pub, 'CADASTRADA', request, norma=norma)
        return Response({
            'norma': NormaSerializer(norma, context={'request': request}).data,
            'publicacao': PublicacaoSerializer(pub, context={'request': request}).data,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def situacao(self, request):
        """Última coleta de cada fonte (é daqui que a tela avisa que uma fonte parou) e a fila."""
        fontes = []
        for fonte, rotulo in PublicacaoMonitorada.FONTES:
            ultimas = list(ExecucaoMonitor.objects.filter(fonte=fonte).order_by('-iniciado_em')[:10])
            if not ultimas:
                continue
            falhas = 0
            for e in ultimas:
                if e.ok:
                    break
                falhas += 1
            u = ultimas[0]
            fontes.append({
                'fonte': fonte, 'rotulo': rotulo, 'ok': u.ok, 'erro': u.erro, 'data_referencia': u.data_referencia,
                'concluido_em': u.concluido_em, 'falhas_seguidas': falhas,
                'ultima_ok': next((e.concluido_em for e in ultimas if e.ok), None),
            })
        return Response({
            'fontes': fontes,
            'para_avaliar': PublicacaoMonitorada.objects.filter(status='NOVA').count(),
            'relevantes': PublicacaoMonitorada.objects.filter(status='NOVA', relevancia__in=['ALTA', 'MEDIA']).count(),
        })

    @action(detail=False, methods=['post'])
    def coletar(self, request):
        """Roda a coleta agora (além dos horários agendados)."""
        monitorar_diarios.delay()
        return Response({'detail': 'Coleta iniciada. As novidades aparecem em alguns minutos.'},
                        status=status.HTTP_202_ACCEPTED)


# ── Configurações do monitor (tela "Configurações do monitor") ───────────
JANELA_ESTATISTICA = 90  # dias de publicações para as contagens da tela


def _publicacoes_recentes():
    desde = date.today() - timedelta(days=JANELA_ESTATISTICA)
    return list(PublicacaoMonitorada.objects.filter(criado_em__date__gte=desde).values('palavras', 'status', 'origem'))


class PalavraChaveViewSet(viewsets.ModelViewSet):
    """Palavras-chave do monitor. A lista traz quantas publicações cada uma trouxe nos
    últimos 90 dias e o que a equipe fez com elas — é o que mostra quem só traz ruído."""

    permission_classes = [IsConformidade]
    serializer_class = PalavraChaveSerializer
    queryset = PalavraChaveMonitor.objects.all()

    def list(self, request, *args, **kwargs):
        dados = self.get_serializer(self.get_queryset(), many=True).data
        pubs = _publicacoes_recentes()
        for d in dados:
            minhas = [p for p in pubs if d['rotulo'] in (p['palavras'] or [])]
            d['disparos'] = len(minhas)
            d['descartadas'] = sum(1 for p in minhas if p['status'] == 'DESCARTADA')
            d['viraram_norma'] = sum(1 for p in minhas if p['status'] == 'CADASTRADA')
        return Response(dados)


class OrgaoMonitorViewSet(viewsets.ModelViewSet):
    permission_classes = [IsConformidade]
    serializer_class = OrgaoMonitorSerializer
    queryset = OrgaoMonitor.objects.all()

    def list(self, request, *args, **kwargs):
        dados = self.get_serializer(self.get_queryset(), many=True).data
        pubs = _publicacoes_recentes()
        for d in dados:
            minhas = [p for p in pubs if p['origem'] == d['rotulo']]
            d['trazidas'] = len(minhas)
            d['descartadas'] = sum(1 for p in minhas if p['status'] == 'DESCARTADA')
            d['viraram_norma'] = sum(1 for p in minhas if p['status'] == 'CADASTRADA')
        return Response(dados)


class ConfiguracaoMonitorView(APIView):
    permission_classes = [IsConformidade]

    def get(self, request):
        cfg = ConfiguracaoMonitor.atual()
        dados = ConfiguracaoMonitorSerializer(cfg).data
        # O que vale hoje (o da tela ou, vazio, o do servidor) — para a tela mostrar de onde vem.
        dados['perfil_servidor'] = getattr(settings, 'CONFORMIDADE_IA_PERFIL_EMPRESA', '')
        return Response(dados)

    def patch(self, request):
        cfg = ConfiguracaoMonitor.atual()
        s = ConfiguracaoMonitorSerializer(cfg, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save(atualizado_por=request.user)
        return self.get(request)


class ExecucoesMonitorView(APIView):
    """As últimas coletas, de todas as fontes."""

    permission_classes = [IsConformidade]

    def get(self, request):
        qs = ExecucaoMonitor.objects.order_by('-iniciado_em')[:80]
        return Response(ExecucaoMonitorSerializer(qs, many=True).data)


class TestarPalavrasView(APIView):
    """Cola um trecho e vê quais palavras-chave ativas disparariam (nada é gravado)."""

    permission_classes = [IsConformidade]

    def post(self, request):
        from . import monitor
        texto = (request.data.get('texto') or '')[:50000]
        return Response({'palavras': monitor.palavras_encontradas(texto, monitor.carregar_palavras())})


# ── Terceiros ─────────────────────────────────────────────────────────────
def _resumo_terceiros(hoje, unidade=None):
    """Painel: terceiros ativos irregulares/a vencer e os documentos exigidos que pedem atenção."""
    terceiros = list(avisos.da_unidade(Terceiro.objects.filter(ativo=True), unidade).prefetch_related('documentos'))
    alertas = []
    for t in terceiros:
        for d in t.documentos_vigentes():
            if d.obrigatorio and d.situacao in ('VENCIDO', 'A_VENCER', 'PENDENTE'):
                alertas.append({'terceiro': t.id, 'terceiro_nome': str(t), 'documento': d.id,
                                'tipo_rotulo': d.get_tipo_display(), 'descricao': d.descricao,
                                'situacao': d.situacao, 'validade': d.validade, 'dias': d.dias_para_vencer})
    ordem = {'VENCIDO': 0, 'PENDENTE': 1, 'A_VENCER': 2}
    alertas.sort(key=lambda a: (ordem[a['situacao']], a['dias'] if a['dias'] is not None else 0))
    situacoes = [t.situacao_documental() for t in terceiros]
    return {
        'ativos': len(terceiros),
        'irregulares': situacoes.count('IRREGULAR'),
        'a_vencer': situacoes.count('A_VENCER'),
        'documentos_vencidos': sum(a['situacao'] == 'VENCIDO' for a in alertas),
        'documentos_pendentes': sum(a['situacao'] == 'PENDENTE' for a in alertas),
        'alertas': alertas[:15],
    }


class TerceiroViewSet(viewsets.ModelViewSet):
    """Prestadores de serviço. ``?situacao=IRREGULAR|A_VENCER|REGULAR|SEM_EXIGENCIA``, ``?ativo=todos``."""
    permission_classes = [IsConformidade]
    serializer_class = TerceiroSerializer

    def get_queryset(self):
        qs = (Terceiro.objects.prefetch_related('documentos__enviado_por__colaborador')
              .annotate(total_requisitos=Count('requisitos', filter=Q(requisitos__ativo=True), distinct=True),
                        planos_abertos=Count('planos', filter=Q(planos__concluido_em__isnull=True)
                                             & (Q(planos__tarefa__isnull=True) | Q(planos__tarefa__concluido_em__isnull=True)),
                                             distinct=True)))
        p = self.request.query_params
        if p.get('ativo', '1') != 'todos':
            qs = qs.filter(ativo=True)
        if p.get('categoria'):
            qs = qs.filter(categoria=p['categoria'])
        qs = avisos.da_unidade(qs, p.get('unidade'))
        if p.get('q'):
            termo = p['q'].strip()
            qs = qs.filter(Q(razao_social__icontains=termo) | Q(nome_fantasia__icontains=termo)
                           | Q(cnpj__icontains=termo) | Q(servico__icontains=termo))
        return qs

    def list(self, request, *args, **kwargs):
        lista = self.get_queryset()
        situacao = request.query_params.get('situacao')
        if situacao:
            lista = [t for t in lista if t.situacao_documental() == situacao]
        return Response(self.get_serializer(lista, many=True).data)

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    def destroy(self, request, *args, **kwargs):
        terceiro = self.get_object()
        if terceiro.documentos.exists() or terceiro.requisitos.exists() or terceiro.planos.exists():
            return Response({'detail': 'Este terceiro tem documentos, requisitos ou planos ligados. Inative-o em vez de '
                                       'excluir — os documentos são evidência de que ele estava regular.'},
                            status=status.HTTP_400_BAD_REQUEST)
        terceiro.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DocumentoTerceiroViewSet(viewsets.ModelViewSet):
    """
    Documentos dos terceiros. ``?terceiro=<id>``; ``?historico=1`` inclui as versões
    substituídas. Multipart com ``arquivo``. Renovar (``/renovar/``) guarda a versão
    anterior em vez de sobrescrever o arquivo.
    """
    permission_classes = [IsConformidade]
    serializer_class = DocumentoTerceiroSerializer

    def get_queryset(self):
        qs = DocumentoTerceiro.objects.select_related('terceiro', 'enviado_por__colaborador')
        p = self.request.query_params
        if p.get('terceiro'):
            qs = qs.filter(terceiro=p['terceiro'])
        # Só a listagem esconde as versões antigas; no detalhe elas existem (e dizem "já renovado").
        if self.action == 'list' and p.get('historico') != '1':
            qs = qs.filter(substituido_em__isnull=True)
        return qs

    def perform_create(self, serializer):
        enviado = self.request.user if serializer.validated_data.get('arquivo') else None
        serializer.save(enviado_por=enviado)

    def perform_update(self, serializer):
        if serializer.instance.substituido_em:
            raise ValidationError({'detail': 'Versão antiga do documento: só a atual pode ser alterada.'})
        extra = {'enviado_por': self.request.user} if serializer.validated_data.get('arquivo') else {}
        serializer.save(**extra)

    def perform_destroy(self, instance):
        if instance.arquivo:
            instance.arquivo.delete(save=False)
        instance.delete()

    @action(detail=True, methods=['post'])
    def renovar(self, request, pk=None):
        """Nova versão do documento (arquivo + datas); a anterior vai para o histórico."""
        antigo = self.get_object()
        if antigo.substituido_em:
            raise ValidationError({'detail': 'Este documento já foi renovado.'})
        if not request.data.get('arquivo'):
            raise ValidationError({'arquivo': 'Anexe o documento renovado.'})
        dados = {
            'terceiro': antigo.terceiro_id, 'tipo': antigo.tipo, 'obrigatorio': antigo.obrigatorio, 'dias_aviso': antigo.dias_aviso,
            'descricao': request.data.get('descricao', antigo.descricao), 'orgao': request.data.get('orgao', antigo.orgao),
            'numero': request.data.get('numero', antigo.numero), 'emissao': request.data.get('emissao') or None,
            'validade': request.data.get('validade') or None, 'arquivo': request.data.get('arquivo'),
        }
        s = self.get_serializer(data=dados)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            novo = s.save(enviado_por=request.user)
            antigo.substituido_em = timezone.now()
            antigo.save(update_fields=['substituido_em'])
        return Response(self.get_serializer(novo).data, status=status.HTTP_201_CREATED)



class AvisosView(APIView):
    """Configuração dos avisos: prazos de antecedência e e-mail (GET / PATCH)."""
    permission_classes = [IsConformidade]

    def get(self, request):
        return Response(ConfiguracaoAvisosSerializer(ConfiguracaoAvisos.atual()).data)

    def patch(self, request):
        cfg = ConfiguracaoAvisos.atual()
        s = ConfiguracaoAvisosSerializer(cfg, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save(atualizado_por=request.user)
        from .models import limpar_cache_avisos
        limpar_cache_avisos()
        return self.get(request)


class AvisosTesteView(APIView):
    """Manda agora o resumo completo para um endereço (o do usuário, se não vier ``email``)."""
    permission_classes = [IsConformidade]

    def post(self, request):
        email = (request.data.get('email') or request.user.email or '').strip()
        if not email:
            raise ValidationError({'email': 'Seu usuário não tem e-mail cadastrado. Informe um endereço.'})
        try:
            r = avisos.enviar_avisos(so_para=email)
        except Exception as e:  # noqa: BLE001 — SMTP fora do ar vira mensagem na tela
            logger.warning('Teste de avisos para %s falhou: %s', email, e)
            return Response({'detail': f'O servidor de e-mail recusou o envio: {e}'[:300]},
                            status=status.HTTP_502_BAD_GATEWAY)
        if r['sem_pendencias']:
            return Response({'detail': 'Nada pede atenção agora — o e-mail só sai quando há pendências.', 'email': email})
        return Response({'detail': f'E-mail de teste enviado para {email}.', 'email': email})


class AvisosDestinatariosView(APIView):
    """Prévia: quem receberia o e-mail hoje e quantos itens cada um."""
    permission_classes = [IsConformidade]

    def get(self, request):
        cfg = ConfiguracaoAvisos.atual()
        lista = []
        for email, nome, filtros, completo in avisos.destinatarios(cfg):
            msg = avisos.montar_email(avisos.pendencias(filtros), nome, completo)
            lista.append({'email': email, 'nome': nome, 'completo': completo, 'itens': msg[2] if msg else 0})
        return Response({'dia_de_enviar': avisos.dia_de_enviar(cfg), 'destinatarios': lista})


# ── Matriz de requisitos legais (planilha do SGI) ───────────────────────────────
class MatrizItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MatrizItem
        fields = ['id', 'ordem', 'atividade', 'obrigacoes', 'referencias', 'controles', 'evidencias', 'responsavel_sugerido',
                  'frequencia', 'situacao_manual', 'justificativa', 'pendencias_manual', 'atualizado_em']
        read_only_fields = ['atualizado_em']

    def validate(self, attrs):
        if attrs.get('situacao_manual') and not (attrs.get('justificativa') or getattr(self.instance, 'justificativa', '')):
            raise ValidationError({'justificativa': 'Diga por que a situação foi definida à mão.'})
        return attrs

    def to_representation(self, item):
        dados = super().to_representation(item)
        dados.update(matriz.situacao(item))
        if self.context.get('detalhe'):
            dados['vinculos'] = [{
                'id': v.id, 'requisito': v.requisito_id, 'texto': v.requisito.descricao[:300], 'referencia': v.requisito.referencia,
                'norma': v.requisito.norma.identificacao, 'norma_id': v.requisito.norma_id, 'situacao': v.requisito.situacao,
                'aplicabilidade': v.requisito.aplicabilidade, 'ultima_verificacao': v.requisito.ultima_verificacao,
                'proxima_verificacao': v.requisito.proxima_verificacao, 'automatico': v.automatico, 'motivo': v.motivo,
            } for v in item.vinculos.all() if not v.excluido and v.requisito.ativo]
            dados['vinculos_normas'] = [{
                'id': v.id, 'norma': v.norma_id, 'identificacao': v.norma.identificacao, 'tipo': v.norma.tipo,
                'validade': v.norma.validade, 'situacao': v.norma.situacao, 'automatico': v.automatico, 'motivo': v.motivo,
            } for v in item.vinculos_normas.all() if not v.excluido]
        return dados


class MatrizViewSet(viewsets.ModelViewSet):
    """
    Matriz de requisitos legais. A situação de cada atividade vem dos requisitos e licenças
    ligados (ver ``matriz.py``); importar a planilha cria/atualiza e já liga ao que está cadastrado.
    """
    permission_classes = [IsConformidade]
    serializer_class = MatrizItemSerializer

    def get_queryset(self):
        return matriz.queryset_itens()

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'detalhe': self.action != 'list'}

    def perform_create(self, serializer):
        item = serializer.save(criado_por=self.request.user)
        matriz.vincular_automatico([item])

    @action(detail=False, methods=['get'])
    def resumo(self, request):
        return Response(matriz.resumo())

    @action(detail=False, methods=['post'])
    def importar(self, request):
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            raise ValidationError({'arquivo': 'Envie a planilha (.xlsx).'})
        if arquivo.size > 5 * 1024 * 1024:
            raise ValidationError({'arquivo': 'Planilha maior que 5 MB.'})
        if not arquivo.name.lower().endswith(('.xlsx', '.xlsm')):
            raise ValidationError({'arquivo': 'Envie no formato .xlsx (Excel).'})
        try:
            resultado = matriz.importar_planilha(arquivo, request.user)
        except ValueError as exc:
            raise ValidationError({'arquivo': str(exc)})
        logger.info('Conformidade: matriz importada por %s: %s', request.user, resultado)
        return Response({**resultado, 'resumo': matriz.resumo()}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='vincular-automatico')
    def vincular(self, request):
        """Procura de novo (ex.: depois de cadastrar uma licença). Não traz de volta o que foi tirado à mão."""
        return Response({'novos': matriz.vincular_automatico(), 'resumo': matriz.resumo()})

    @action(detail=False, methods=['get'])
    def exportar(self, request):
        resp = HttpResponse(matriz.exportar_planilha(),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="matriz_requisitos_{date.today():%Y%m%d}.xlsx"'
        return resp

    @action(detail=True, methods=['post', 'delete'])
    def vinculos(self, request, pk=None):
        """POST {requisito} ou {norma} liga à mão; DELETE ?requisito= / ?norma= tira (a automática fica marcada para não voltar)."""
        item = self.get_object()
        origem = request.data if request.method == 'POST' else request.query_params
        rid, nid = origem.get('requisito'), origem.get('norma')
        if not (rid or nid):
            raise ValidationError({'detail': 'Informe o requisito ou a norma.'})
        if request.method == 'POST':
            if rid:
                req = Requisito.objects.filter(pk=rid).first()
                if not req:
                    raise ValidationError({'requisito': 'Requisito não encontrado.'})
                MatrizVinculo.objects.update_or_create(item=item, requisito=req, defaults={'excluido': False, 'automatico': False, 'motivo': 'Ligado à mão'})
            if nid:
                norma = Norma.objects.filter(pk=nid).first()
                if not norma:
                    raise ValidationError({'norma': 'Norma não encontrada.'})
                MatrizVinculoNorma.objects.update_or_create(item=item, norma=norma, defaults={'excluido': False, 'automatico': False, 'motivo': 'Ligada à mão'})
        else:
            modelo, campo, valor = (MatrizVinculo, 'requisito_id', rid) if rid else (MatrizVinculoNorma, 'norma_id', nid)
            v = modelo.objects.filter(item=item, **{campo: valor}).first()
            if v and v.automatico:
                v.excluido = True
                v.save(update_fields=['excluido'])
            elif v:
                v.delete()
        item = self.get_queryset().get(pk=item.pk)
        return Response(self.get_serializer(item).data)
