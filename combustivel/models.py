"""Controle de combustível (tanques próprios, abastecimentos, integração com o SGA).

Hoje o diesel da bomba entra no SGA pelo ``SgaAbastecimento.exe`` (Minerion), que busca os
abastecimentos no CTA Plus e grava a baixa em ``BAIXAESTOQUE`` (ver memória
``erp_baixa_combustivel``). Este app nasce para:

* ler o que já está no SGA (entradas por nota, baixas, horímetros) e transformar em painel e alertas;
* registrar abastecimentos pelo celular, com fotos e conferência na hora;
* entregar esses registros ao SGA de duas formas — arquivo (``LoteIntegracao``) e API de
  leitura por chave (``ChaveIntegracao``), para quando a Minerion apontar o programa para cá.

Fotos e arquivos ficam FORA do MEDIA_ROOT (que o nginx serve sem login): só saem pela API,
depois da checagem de grupo.
"""
import hashlib
import secrets
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone

PRIVADO = FileSystemStorage(
    location=getattr(settings, 'COMBUSTIVEL_PRIVADO', settings.BASE_DIR / 'privado' / 'combustivel'),
    base_url=None,
)

# Códigos do SGA (ESTOQUE.ESTQCOD) e o identificador que a integração usa (PEFITEMIAB).
PRODUTOS = {
    253: {'nome': 'Diesel S-10', 'ident': '10'},
    4122: {'nome': 'Diesel S-500', 'ident': '500'},
    257: {'nome': 'ARLA 32', 'ident': '32'},
}
PRODUTO_CHOICES = [(cod, p['nome']) for cod, p in PRODUTOS.items()]

# Os registros do Manager vão para o SGA com um código próprio, longe da faixa do CTA
# (IABCODAB perto de 100 milhões em 2026) e dentro de um int de 32 bits.
BASE_CODIGO_INTEGRACAO = 1_500_000_000

# Abastecimentos falsos do comando gerar_abastecimentos_teste começam com isto na observação.
# Nascem retidos (alerta de bloqueio), então nunca saem em arquivo nem pela API.
MARCA_TESTE = '[TESTE] '


def _caminho_foto(instancia, nome):
    agora = timezone.now()
    return f'fotos/{agora:%Y/%m}/{uuid.uuid4().hex}.jpg'


def _caminho_lote(instancia, nome):
    agora = timezone.now()
    ext = nome.rsplit('.', 1)[-1].lower() if '.' in nome else 'txt'
    return f'lotes/{agora:%Y/%m}/{uuid.uuid4().hex}.{ext}'


class Tanque(models.Model):
    nome = models.CharField(max_length=80)
    filial = models.PositiveSmallIntegerField(default=0, help_text='Filial do SGA (0 = matriz)')
    produto = models.PositiveIntegerField(choices=PRODUTO_CHOICES, default=253)
    capacidade_l = models.DecimalField(max_digits=10, decimal_places=2)
    estoque_minimo_l = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # O saldo NÃO é guardado aqui: vem do SGA (QUANTESTOQUE da filial + produto), menos o que
    # o Manager registrou e o SGA ainda não baixou. A régua (MedicaoTanque) mostra a diferença.
    bomba_ident = models.CharField(max_length=40, blank=True, default='', help_text='Identificação da bomba na integração')
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['filial', 'nome']

    def __str__(self):
        return self.nome

    @property
    def produto_nome(self):
        return PRODUTOS.get(self.produto, {}).get('nome', str(self.produto))


class MedicaoTanque(models.Model):
    """Régua/leitura do tanque: confere o saldo calculado e mostra a divergência."""
    tanque = models.ForeignKey(Tanque, on_delete=models.CASCADE, related_name='medicoes')
    medido_em = models.DateTimeField(default=timezone.now)
    litros = models.DecimalField(max_digits=10, decimal_places=2)
    saldo_sistema_l = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                          help_text='Saldo do SGA na hora da medição')
    foto = models.ImageField(upload_to=_caminho_foto, storage=PRIVADO, null=True, blank=True)
    observacao = models.CharField(max_length=300, blank=True, default='')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-medido_em']


class LoteIntegracao(models.Model):
    """Arquivo gerado para o SGA (um lote = um conjunto de abastecimentos exportados)."""
    CSV, TXT, JSON = 'CSV', 'TXT', 'JSON'
    FORMATOS = [(CSV, 'CSV (;)'), (TXT, 'TXT (layout fixo)'), (JSON, 'JSON')]
    GERADO, IMPORTADO, CANCELADO = 'GERADO', 'IMPORTADO', 'CANCELADO'
    SITUACOES = [(GERADO, 'Gerado'), (IMPORTADO, 'Importado no SGA'), (CANCELADO, 'Cancelado')]

    formato = models.CharField(max_length=5, choices=FORMATOS)
    situacao = models.CharField(max_length=10, choices=SITUACOES, default=GERADO)
    arquivo = models.FileField(upload_to=_caminho_lote, storage=PRIVADO)
    nome_arquivo = models.CharField(max_length=120)
    sha256 = models.CharField(max_length=64)
    quantidade = models.PositiveIntegerField(default=0)
    litros = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em']


class Abastecimento(models.Model):
    """Abastecimento registrado no Manager (os do CTA continuam vindo do SGA, só leitura)."""
    REGISTRADO, CONFERIDO, EXPORTADO, BAIXADO, CANCELADO = 'REGISTRADO', 'CONFERIDO', 'EXPORTADO', 'BAIXADO', 'CANCELADO'
    SITUACOES = [
        (REGISTRADO, 'Registrado'), (CONFERIDO, 'Conferido'), (EXPORTADO, 'Enviado ao SGA'),
        (BAIXADO, 'Baixado no SGA'), (CANCELADO, 'Cancelado'),
    ]

    # Gerado no aparelho: reenviar o mesmo registro (internet caiu no meio) não duplica.
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    tanque = models.ForeignKey(Tanque, on_delete=models.PROTECT, related_name='abastecimentos')
    abastecido_em = models.DateTimeField()
    equipamento = models.PositiveIntegerField(help_text='EQUIPAMENTO.EQPCOD no SGA')
    equipamento_nome = models.CharField(max_length=120, blank=True, default='')
    placa = models.CharField(max_length=10, blank=True, default='')
    centro_custo = models.PositiveIntegerField(null=True, blank=True)
    funcionario = models.PositiveIntegerField(help_text='Quem abasteceu — FUNCIONARIO.FUNCOD / FUNIDENTIAB')
    funcionario_nome = models.CharField(max_length=120, blank=True, default='')
    litros = models.DecimalField(max_digits=8, decimal_places=2)
    horimetro = models.DecimalField(max_digits=10, decimal_places=1, null=True, blank=True)
    km = models.DecimalField(max_digits=10, decimal_places=1, null=True, blank=True)
    encerrante_inicial = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    encerrante_final = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    foto_bomba = models.ImageField(upload_to=_caminho_foto, storage=PRIVADO, null=True, blank=True)
    foto_painel = models.ImageField(upload_to=_caminho_foto, storage=PRIVADO, null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    observacao = models.CharField(max_length=400, blank=True, default='')

    situacao = models.CharField(max_length=12, choices=SITUACOES, default=REGISTRADO)
    alertas = models.JSONField(default=list, blank=True)
    bloqueado = models.BooleanField(default=False, help_text='Algum alerta impede o envio ao SGA')
    lote = models.ForeignKey(LoteIntegracao, on_delete=models.SET_NULL, null=True, blank=True, related_name='abastecimentos')
    baixa_sga = models.PositiveIntegerField(null=True, blank=True, help_text='BAIXAESTOQUE.BESTCOD quando baixado')
    erro_sga = models.CharField(max_length=300, blank=True, default='')
    enviado_sga_em = models.DateTimeField(null=True, blank=True)
    baixado_em = models.DateTimeField(null=True, blank=True)
    motivo_cancelamento = models.CharField(max_length=300, blank=True, default='')

    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    conferido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-abastecido_em']
        indexes = [models.Index(fields=['equipamento', 'abastecido_em']), models.Index(fields=['situacao'])]

    def __str__(self):
        return f'{self.equipamento_nome or self.equipamento} · {self.litros} L'

    @property
    def codigo_integracao(self) -> int:
        """O ``IABCODAB`` com que o registro chega ao SGA (e volta em ``BESTIAB``)."""
        return BASE_CODIGO_INTEGRACAO + self.pk


class ChaveIntegracao(models.Model):
    """
    Chave de API para o SGA (ou outro sistema) BUSCAR os abastecimentos. Só o hash fica
    guardado; o segredo aparece uma vez, na criação. Formato enviado:
    ``Authorization: Chave <prefixo>.<segredo>``.
    """
    LEITURA, CONFIRMACAO = 'leitura', 'confirmacao'

    nome = models.CharField(max_length=80)
    prefixo = models.CharField(max_length=12, unique=True)
    hash_segredo = models.CharField(max_length=64)
    pode_confirmar = models.BooleanField(default=True, help_text='Pode devolver o resultado da baixa')
    ips_permitidos = models.TextField(blank=True, default='', help_text='Um IP ou rede por linha; vazio = qualquer')
    ativa = models.BooleanField(default=True)
    expira_em = models.DateTimeField(null=True, blank=True)
    ultimo_uso_em = models.DateTimeField(null=True, blank=True)
    ultimo_ip = models.GenericIPAddressField(null=True, blank=True)
    usos = models.PositiveIntegerField(default=0)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)
    revogada_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-criado_em']

    @staticmethod
    def hash(segredo: str) -> str:
        return hashlib.sha256(segredo.encode()).hexdigest()

    @classmethod
    def gerar(cls, **campos):
        """Cria a chave e devolve ``(chave, texto_completo)`` — o texto não é guardado."""
        prefixo = secrets.token_hex(4)
        segredo = secrets.token_urlsafe(32)
        chave = cls.objects.create(prefixo=prefixo, hash_segredo=cls.hash(segredo), **campos)
        return chave, f'{prefixo}.{segredo}'

    @property
    def valida(self) -> bool:
        return self.ativa and not self.revogada_em and (not self.expira_em or self.expira_em > timezone.now())


class Auditoria(models.Model):
    """Quem fez o quê (cancelar, conferir, exportar, criar/revogar chave, acesso pela API)."""
    quando = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    chave = models.ForeignKey(ChaveIntegracao, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    acao = models.CharField(max_length=40)
    objeto = models.CharField(max_length=80, blank=True, default='')
    ip = models.GenericIPAddressField(null=True, blank=True)
    dados = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-quando']
