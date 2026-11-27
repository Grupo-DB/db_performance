import io

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import serializers

from .models import (DestinatarioNotificacao, Equipamento, Evidencia, Ficha, FichaVersao, Impedimento, NCCritica,
                     ProgramaItem, Questao, Resposta, Setor, Suspensao, TipoEquipamento, Unidade, Vistoria)

User = get_user_model()

FOTO_MAX_BYTES = 15 * 1024 * 1024
VIDEO_MAX_BYTES = 60 * 1024 * 1024
FOTO_LADO = 1600
FORMATOS_FOTO = {'JPEG', 'PNG', 'WEBP', 'MPO', 'HEIF', 'HEIC'}
VIDEOS = {'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov', 'video/3gpp': '3gp'}


def nome(u):
    if not u:
        return ''
    return u.get_full_name() or u.username


def processar_midia(arquivo) -> tuple[ContentFile, str, str]:
    """
    Foto: reabre no Pillow, gira pelo EXIF, reduz a 1600 px e regrava em JPEG SEM metadados (some o GPS).
    Vídeo: só tipos da lista e até 60 MB (o aparelho limita a 30 s).
    Devolve (arquivo, tipo FOTO/VIDEO, content_type).
    """
    ct = (getattr(arquivo, 'content_type', '') or '').lower()
    if ct in VIDEOS:
        if arquivo.size > VIDEO_MAX_BYTES:
            raise serializers.ValidationError('Vídeo maior que 60 MB (limite de 30 segundos).')
        return ContentFile(arquivo.read(), name=f'video.{VIDEOS[ct]}'), Evidencia.VIDEO, ct
    if arquivo.size > FOTO_MAX_BYTES:
        raise serializers.ValidationError('Foto maior que 15 MB.')
    try:
        arquivo.seek(0)
        img = Image.open(arquivo)
        if (img.format or '').upper() not in FORMATOS_FOTO:
            raise serializers.ValidationError('Envie foto (JPEG, PNG, WebP) ou vídeo (MP4, WebM, MOV).')
        if img.width * img.height > 80_000_000:
            raise serializers.ValidationError('Foto com resolução grande demais.')
        img = ImageOps.exif_transpose(img).convert('RGB')
        img.thumbnail((FOTO_LADO, FOTO_LADO))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise serializers.ValidationError('Arquivo não é uma foto ou vídeo válido.')
    saida = io.BytesIO()
    img.save(saida, 'JPEG', quality=80, optimize=True)
    return ContentFile(saida.getvalue(), name='foto.jpg'), Evidencia.FOTO, 'image/jpeg'


class UnidadeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unidade
        fields = ['id', 'sigla', 'nome', 'ativo']


class SetorSerializer(serializers.ModelSerializer):
    unidade_sigla = serializers.CharField(source='unidade.sigla', read_only=True)

    class Meta:
        model = Setor
        fields = ['id', 'unidade', 'unidade_sigla', 'codigo', 'nome', 'ativo']


class QuestaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Questao
        fields = ['id', 'codigo', 'grupo', 'descricao', 'criticidade', 'permite_na', 'permite_abono', 'ordem', 'ativa']


class FichaVersaoSerializer(serializers.ModelSerializer):
    questoes = QuestaoSerializer(many=True, read_only=True)
    criada_por_nome = serializers.SerializerMethodField()
    vistorias = serializers.SerializerMethodField()

    class Meta:
        model = FichaVersao
        fields = ['id', 'numero', 'vigente_desde', 'observacao', 'criada_por_nome', 'questoes', 'vistorias']

    def get_criada_por_nome(self, o):
        return nome(o.criada_por)

    def get_vistorias(self, o):
        return o.vistorias.count()


class FichaSerializer(serializers.ModelSerializer):
    versao_atual = serializers.SerializerMethodField()
    tipos = serializers.SerializerMethodField()
    versoes = serializers.SerializerMethodField()

    class Meta:
        model = Ficha
        fields = ['id', 'nome', 'descricao', 'ativa', 'criada_em', 'versao_atual', 'tipos', 'versoes']

    def get_versao_atual(self, o):
        v = o.versao_atual()
        if not v:
            return None
        if self.context.get('resumo'):
            return {'id': v.id, 'numero': v.numero, 'vigente_desde': v.vigente_desde,
                    'questoes': v.questoes.filter(ativa=True).count()}
        return FichaVersaoSerializer(v).data

    def get_tipos(self, o):
        return [{'id': t.id, 'codigo': t.codigo, 'descricao': t.descricao} for t in o.tipos.all()]

    def get_versoes(self, o):
        return [{'id': v.id, 'numero': v.numero, 'vigente_desde': v.vigente_desde, 'observacao': v.observacao,
                 'criada_por_nome': nome(v.criada_por)} for v in o.versoes.order_by('-numero')]


class TipoEquipamentoSerializer(serializers.ModelSerializer):
    ficha_nome = serializers.CharField(source='ficha.nome', read_only=True)
    equipamentos = serializers.SerializerMethodField()

    class Meta:
        model = TipoEquipamento
        fields = ['id', 'codigo', 'descricao', 'ficha', 'ficha_nome', 'medicao', 'ativo', 'equipamentos']

    def get_equipamentos(self, o):
        return o.equipamentos.filter(ativo=True).count()


def situacao_equipamento(eq, suspensao=None) -> str:
    if not eq.ativo:
        return 'INATIVO'
    if suspensao is not None:
        return 'AGUARDANDO_LIBERACAO' if suspensao.status == Suspensao.AGUARDANDO else 'SUSPENSO'
    if eq.em_manutencao:
        return 'MANUTENCAO'
    return 'OPERACAO'


class EquipamentoSerializer(serializers.ModelSerializer):
    tipo_descricao = serializers.CharField(source='tipo.descricao', read_only=True)
    ficha_nome = serializers.CharField(source='tipo.ficha.nome', read_only=True)
    medicao = serializers.CharField(source='tipo.medicao', read_only=True)
    unidade_sigla = serializers.CharField(source='unidade.sigla', read_only=True)
    setor_nome = serializers.CharField(source='setor.nome', read_only=True)
    gerente_nome = serializers.SerializerMethodField()
    situacao = serializers.SerializerMethodField()
    suspensao = serializers.SerializerMethodField()

    class Meta:
        model = Equipamento
        fields = ['id', 'tag', 'descricao', 'tipo', 'tipo_descricao', 'ficha_nome', 'medicao', 'marca_modelo', 'placa',
                  'unidade', 'unidade_sigla', 'setor', 'setor_nome', 'gerente', 'gerente_nome', 'periodicidade',
                  'ativo', 'em_manutencao', 'sga_codigo', 'situacao', 'suspensao', 'criado_em', 'atualizado_em']
        read_only_fields = ['criado_em', 'atualizado_em']

    def _susp(self, o):
        mapa = self.context.get('suspensoes')
        if mapa is not None:
            return mapa.get(o.pk)
        return o.suspensoes.filter(status__in=(Suspensao.SUSPENSA, Suspensao.AGUARDANDO)).first()

    def get_gerente_nome(self, o):
        return nome(o.gerente)

    def get_situacao(self, o):
        return situacao_equipamento(o, self._susp(o))

    def get_suspensao(self, o):
        s = self._susp(o)
        return {'id': s.id, 'desde': s.iniciada_em, 'status': s.status} if s else None

    def validate_tag(self, v):
        return v.strip().upper()

    def validate(self, attrs):
        unidade = attrs.get('unidade', getattr(self.instance, 'unidade', None))
        setor = attrs.get('setor', getattr(self.instance, 'setor', None))
        if unidade and setor and setor.unidade_id != unidade.pk:
            raise serializers.ValidationError({'setor': 'O setor não pertence à unidade escolhida.'})
        return attrs


class DestinatarioSerializer(serializers.ModelSerializer):
    unidade_sigla = serializers.CharField(source='unidade.sigla', read_only=True, default='Todas')

    class Meta:
        model = DestinatarioNotificacao
        fields = ['id', 'unidade', 'unidade_sigla', 'papel', 'nome', 'email', 'ativo']


class EvidenciaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    enviada_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = Evidencia
        fields = ['uuid', 'finalidade', 'tipo', 'content_type', 'tamanho', 'criada_em', 'url', 'enviada_por_nome']

    def get_url(self, o):
        return f'/vistorias/evidencias/{o.uuid}/arquivo/'

    def get_enviada_por_nome(self, o):
        return nome(o.enviada_por)


class RespostaSerializer(serializers.ModelSerializer):
    evidencias = serializers.SerializerMethodField()
    travada = serializers.BooleanField(read_only=True)
    cancelada_por_nome = serializers.SerializerMethodField()
    abonada_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = Resposta
        fields = ['id', 'codigo', 'grupo', 'descricao', 'criticidade', 'permite_na', 'permite_abono', 'ordem', 'valor',
                  'descricao_problema', 'respondida_em', 'critica_confirmada_em', 'travada', 'cancelada',
                  'cancelamento_justificativa', 'cancelada_por_nome', 'cancelada_em', 'abonada', 'abono_justificativa',
                  'abonada_por_nome', 'abonada_em', 'evidencias']

    def get_evidencias(self, o):
        return EvidenciaSerializer([e for e in o.evidencias.all() if e.finalidade == Evidencia.NC], many=True).data

    def get_cancelada_por_nome(self, o):
        return nome(o.cancelada_por)

    def get_abonada_por_nome(self, o):
        return nome(o.abonada_por)


class VistoriaListaSerializer(serializers.ModelSerializer):
    tag = serializers.CharField(source='equipamento.tag', read_only=True)
    equipamento_descricao = serializers.CharField(source='equipamento.descricao', read_only=True)
    unidade_sigla = serializers.CharField(source='unidade.sigla', read_only=True)
    setor_nome = serializers.CharField(source='setor.nome', read_only=True)
    gerente_nome = serializers.SerializerMethodField()
    avaliador_nome = serializers.SerializerMethodField()
    ficha = serializers.SerializerMethodField()
    item_mes = serializers.SerializerMethodField()
    ncs = serializers.SerializerMethodField()
    suspenso = serializers.SerializerMethodField()

    class Meta:
        model = Vistoria
        fields = ['suspenso', 'uuid', 'equipamento', 'tag', 'equipamento_descricao', 'tipo', 'motivo_extraordinaria', 'unidade_sigla',
                  'setor_nome', 'gerente_nome', 'avaliador', 'avaliador_nome', 'iniciada_em', 'concluida_em', 'status',
                  'resultado_inicial', 'resultado_final', 'validada_em', 'ficha', 'item', 'item_mes', 'ncs']

    def get_gerente_nome(self, o):
        return nome(o.gerente)

    def get_suspenso(self, o):
        """Equipamento com operação suspensa AGORA (selo vermelho da 5.4)."""
        mapa = self.context.get('suspensoes')
        if mapa is not None:
            return o.equipamento_id in mapa
        return o.equipamento.suspensoes.filter(status__in=(Suspensao.SUSPENSA, Suspensao.AGUARDANDO)).exists()

    def get_avaliador_nome(self, o):
        return nome(o.avaliador)

    def get_ficha(self, o):
        return f'{o.ficha_versao.ficha.nome} v{o.ficha_versao.numero}'

    def get_item_mes(self, o):
        return {'ano': o.item.ano, 'mes': o.item.mes} if o.item_id else None

    def get_ncs(self, o):
        cont = {'LEVE': 0, 'MEDIA': 0, 'CRITICA': 0, 'total': 0, 'respondidas': 0, 'questoes': 0}
        for r in o.respostas.all():
            cont['questoes'] += 1
            if r.valor:
                cont['respondidas'] += 1
            if r.valor == Resposta.NC and not r.cancelada:
                cont[r.criticidade] += 1
                cont['total'] += 1
        return cont


class VistoriaSerializer(VistoriaListaSerializer):
    respostas = RespostaSerializer(many=True, read_only=True)
    validada_por_nome = serializers.SerializerMethodField()
    devolucoes = serializers.SerializerMethodField()
    suspensoes = serializers.SerializerMethodField()
    medicao_menor = serializers.SerializerMethodField()
    tag_placa = serializers.CharField(source='equipamento.placa', read_only=True)
    marca_modelo = serializers.CharField(source='equipamento.marca_modelo', read_only=True)
    tipo_equipamento = serializers.CharField(source='equipamento.tipo.descricao', read_only=True)

    class Meta(VistoriaListaSerializer.Meta):
        fields = VistoriaListaSerializer.Meta.fields + [
            'medicao_tipo', 'medicao', 'medicao_anterior', 'medicao_menor', 'medicao_menor_confirmada',
            'acompanhante_nome', 'acompanhante_cargo', 'observacoes', 'validada_por_nome', 'respostas',
            'devolucoes', 'suspensoes', 'tag_placa', 'marca_modelo', 'tipo_equipamento']

    def get_validada_por_nome(self, o):
        return nome(o.validada_por)

    def get_devolucoes(self, o):
        return [{'justificativa': d.justificativa, 'por': nome(d.devolvida_por), 'em': d.devolvida_em}
                for d in o.devolucoes.all()]

    def get_suspensoes(self, o):
        return [{'id': s.id, 'status': s.status, 'adesivo': s.adesivo, 'adesivo_em': s.adesivo_em,
                 'iniciada_em': s.iniciada_em} for s in o.suspensoes.all()]

    def get_medicao_menor(self, o):
        return o.medicao is not None and o.medicao_anterior is not None and o.medicao < o.medicao_anterior


class NCCriticaSerializer(serializers.ModelSerializer):
    codigo = serializers.CharField(source='resposta.codigo', read_only=True)
    descricao = serializers.CharField(source='resposta.descricao', read_only=True)
    grupo = serializers.CharField(source='resposta.grupo', read_only=True)
    descricao_problema = serializers.CharField(source='resposta.descricao_problema', read_only=True)
    confirmada_em = serializers.DateTimeField(source='resposta.critica_confirmada_em', read_only=True)
    vistoria = serializers.UUIDField(source='resposta.vistoria.uuid', read_only=True)
    evidencias_nc = serializers.SerializerMethodField()
    evidencias = serializers.SerializerMethodField()
    corrigida_por_nome = serializers.SerializerMethodField()
    validada_por_nome = serializers.SerializerMethodField()
    rejeitada_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = NCCritica
        fields = ['id', 'codigo', 'descricao', 'grupo', 'descricao_problema', 'confirmada_em', 'vistoria', 'status',
                  'correcao', 'corrigida_por_nome', 'corrigida_em', 'validada_por_nome', 'validada_em', 'rejeicao',
                  'rejeicoes', 'rejeitada_por_nome', 'rejeitada_em', 'evidencias_nc', 'evidencias']

    def get_rejeitada_por_nome(self, o):
        return nome(o.rejeitada_por)

    def get_evidencias_nc(self, o):
        return EvidenciaSerializer(o.resposta.evidencias.filter(finalidade=Evidencia.NC), many=True).data

    def get_evidencias(self, o):
        return EvidenciaSerializer(o.evidencias.all(), many=True).data

    def get_corrigida_por_nome(self, o):
        return nome(o.corrigida_por)

    def get_validada_por_nome(self, o):
        return nome(o.validada_por)


class SuspensaoSerializer(serializers.ModelSerializer):
    tag = serializers.CharField(source='equipamento.tag', read_only=True)
    equipamento_descricao = serializers.CharField(source='equipamento.descricao', read_only=True)
    unidade_sigla = serializers.CharField(source='equipamento.unidade.sigla', read_only=True)
    setor_nome = serializers.CharField(source='equipamento.setor.nome', read_only=True)
    gerente_nome = serializers.SerializerMethodField()
    vistoria_uuid = serializers.UUIDField(source='vistoria.uuid', read_only=True)
    avaliador_nome = serializers.SerializerMethodField()
    liberada_por_nome = serializers.SerializerMethodField()
    ncs = NCCriticaSerializer(many=True, read_only=True)
    evidencias_adesivo = serializers.SerializerMethodField()
    emails = serializers.SerializerMethodField()

    class Meta:
        model = Suspensao
        fields = ['id', 'equipamento', 'tag', 'equipamento_descricao', 'unidade_sigla', 'setor_nome', 'gerente_nome',
                  'vistoria_uuid', 'avaliador_nome', 'status', 'iniciada_em', 'adesivo', 'adesivo_em',
                  'adesivo_justificativa', 'liberada_por_nome', 'liberada_em', 'liberacao_observacao', 'encerrada_em',
                  'ncs', 'evidencias_adesivo', 'emails']

    def get_gerente_nome(self, o):
        return nome(o.equipamento.gerente)

    def get_avaliador_nome(self, o):
        return nome(o.vistoria.avaliador)

    def get_liberada_por_nome(self, o):
        return nome(o.liberada_por)

    def get_evidencias_adesivo(self, o):
        return EvidenciaSerializer(o.evidencias.filter(finalidade=Evidencia.ADESIVO), many=True).data

    def get_emails(self, o):
        return [{'id': e.id, 'tipo': e.tipo, 'assunto': e.assunto, 'destinatarios': e.destinatarios,
                 'criado_em': e.criado_em, 'enviado_em': e.enviado_em, 'tentativas': e.tentativas, 'erro': e.erro}
                for e in o.emails.all()]


class ProgramaItemSerializer(serializers.ModelSerializer):
    tag = serializers.CharField(source='equipamento.tag', read_only=True)
    decidido_por_nome = serializers.SerializerMethodField()
    impedimentos = serializers.SerializerMethodField()

    class Meta:
        model = ProgramaItem
        fields = ['id', 'equipamento', 'tag', 'ano', 'mes', 'situacao', 'justificativa', 'decidido_por_nome',
                  'decidido_em', 'origem', 'manual', 'impedimentos']

    def get_decidido_por_nome(self, o):
        return nome(o.decidido_por)

    def get_impedimentos(self, o):
        return [{'id': i.id, 'motivo': i.motivo, 'registrado_por': nome(i.registrado_por), 'registrado_em': i.registrado_em,
                 'decisao': i.decisao, 'decidido_por': nome(i.decidido_por), 'decidido_em': i.decidido_em}
                for i in o.impedimentos.all()]


class ImpedimentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Impedimento
        fields = ['id', 'item', 'motivo', 'registrado_em', 'decisao']
