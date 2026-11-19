"""App Comercial Agro (pedido de 19/11/2026, protótipo "App Comercial Agro").

Vendedor e representante registram contato com produtor (visita, ligação,
WhatsApp), mantêm o perfil do produtor (área, culturas, calagem, análise de
solo → potencial em t/ano) e fazem cotação. Toda cotação passa pelo gestor
(aprova, recusa ou contrapropõe) — decisão do usuário: "começamos com todas";
a regra "só fora do preço padrão" fica pronta em regras.APROVAR_TODAS.
Aprovada, entra na fila do vendedor interno, que lança no SGA (Minerion) e
informa o nº do pedido; o app lê o pedido no SGA e confere com a cotação.

Módulo separado de Pedidos de Venda (pedidosVenda) por escolha do usuário; só a
leitura do SGA é reaproveitada (pedidosVenda.erp). O app nunca grava no SGA.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models

from . import regras


class VendedorAgro(models.Model):
    """Usuário do ManagerDB ↔ códigos REPCOD do SGA (uma pessoa tem um código por região)."""

    PAPEL_CHOICES = [
        ('VENDEDOR', 'Vendedor externo'),
        ('REPRESENTANTE', 'Representante'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendedor_agro')
    papel = models.CharField(max_length=15, choices=PAPEL_CHOICES, default='VENDEDOR')
    carteira = models.CharField(max_length=60, blank=True, default='', help_text='Ex.: "C2 · Centro"')
    repcods = models.JSONField(default=list, blank=True, help_text='Códigos REPCOD do SGA')
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Vendedor agro'
        verbose_name_plural = 'Vendedores agro'
        ordering = ['user__first_name', 'user__username']

    def __str__(self):
        return self.nome

    @property
    def nome(self) -> str:
        return self.user.get_full_name() or self.user.username


class MetaAgro(models.Model):
    """Meta de volume do vendedor no ano (safra = ano civil, decisão de 19/11)."""

    vendedor = models.ForeignKey(VendedorAgro, on_delete=models.CASCADE, related_name='metas')
    ano = models.PositiveIntegerField()
    toneladas = models.DecimalField(max_digits=12, decimal_places=1)

    class Meta:
        unique_together = [('vendedor', 'ano')]
        ordering = ['-ano']


class Produtor(models.Model):
    """Cliente da casa (código do SGA) ou prospect. O perfil fica aqui: preenche uma vez, confirma a cada ano."""

    TIPO_CHOICES = [('PRODUTOR', 'Produtor'), ('REVENDA', 'Revenda'), ('COOPERATIVA', 'Cooperativa')]
    FORNECEDOR_CHOICES = [
        ('CONCORRENTE', 'Concorrente local'),
        ('COOPERATIVA', 'Cooperativa'),
        ('REVENDA', 'Revenda'),
        ('NAO_APLICA', 'Não aplica calcário'),
    ]
    FRETE_CHOICES = [('POSTO', 'Posto fazenda'), ('FOB', 'FOB')]
    CADASTRO_CHOICES = [
        ('PROSPECT', 'Prospect'),           # só no app; o interno ainda vai cadastrar no SGA
        ('CADASTRADO', 'Cadastrado no SGA'),
    ]

    nome = models.CharField(max_length=150)
    documento = models.CharField(max_length=20, blank=True, default='')
    whatsapp = models.CharField(max_length=30, blank=True, default='')
    municipio = models.CharField(max_length=80, blank=True, default='')
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES, default='PRODUTOR')
    cliente_sga = models.IntegerField(null=True, blank=True, unique=True)
    cadastro = models.CharField(max_length=12, choices=CADASTRO_CHOICES, default='PROSPECT', db_index=True)
    # Como entrou no app: já era cliente do SGA ou chegou como prospect (conta "prospects novos").
    origem = models.CharField(max_length=8, choices=[('SGA', 'Cliente do SGA'), ('PROSPECT', 'Prospect')], default='PROSPECT')
    vendedor = models.ForeignKey(VendedorAgro, on_delete=models.SET_NULL, null=True, blank=True, related_name='produtores')

    # Concorrência (o que ele paga hoje)
    fornecedor_atual = models.CharField(max_length=12, choices=FORNECEDOR_CHOICES, blank=True, default='')
    concorrente_nome = models.CharField(max_length=100, blank=True, default='')
    preco_concorrente = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    frete_concorrente = models.CharField(max_length=6, choices=FRETE_CHOICES, blank=True, default='')

    # Perfil do produtor
    area_ha = models.DecimalField(max_digits=10, decimal_places=1, null=True, blank=True)
    culturas = models.JSONField(default=list, blank=True)
    ciclo_anos = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Aplica calcário a cada N anos; 0 = não aplica')
    ultima_aplicacao = models.PositiveSmallIntegerField(null=True, blank=True)
    dose_t_ha = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    cooperativa = models.CharField(max_length=100, blank=True, default='')
    faz_analise = models.BooleanField(null=True, blank=True)
    laudo = models.FileField(upload_to='comercialAgro/laudos/', null=True, blank=True)
    coleta_oferecida = models.BooleanField(default=False)
    perfil_confirmado_ano = models.PositiveSmallIntegerField(null=True, blank=True)

    # Imóvel no CAR (ligado pelo check-in da visita ou pela prospecção)
    car_codigo = models.CharField(max_length=60, blank=True, default='', db_index=True)

    # Pedido de ajuste de cadastro para o interno fazer no SGA (texto livre; vazio = nada pendente)
    ajuste_cadastro = models.TextField(blank=True, default='')
    ajuste_pedido_em = models.DateTimeField(null=True, blank=True)

    criado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    cadastrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cadastrado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Produtor'
        verbose_name_plural = 'Produtores'
        ordering = ['nome']

    def __str__(self):
        return self.nome

    @property
    def potencial_t(self) -> float | None:
        return regras.potencial(self.area_ha, self.dose_t_ha, self.ciclo_anos)


class Contato(models.Model):
    """Todo contato termina com próximo passo e data (regra do protótipo)."""

    TIPO_CHOICES = [('VISITA', 'Visita'), ('LIGACAO', 'Ligação'), ('WHATSAPP', 'WhatsApp')]
    RESULTADO_CHOICES = [
        ('INTERESSADO', 'Interessado · pediu cotação'),
        ('RELACIONAMENTO', 'Relacionamento, sem demanda agora'),
        ('PERDIDO', 'Perdido para concorrente'),
    ]

    produtor = models.ForeignKey(Produtor, on_delete=models.CASCADE, related_name='contatos')
    vendedor = models.ForeignKey(VendedorAgro, on_delete=models.SET_NULL, null=True, blank=True, related_name='contatos')
    autor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='VISITA')
    data_hora = models.DateTimeField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    resultado = models.CharField(max_length=15, choices=RESULTADO_CHOICES)
    observacao = models.TextField(blank=True, default='')
    proximo_passo = models.CharField(max_length=200)
    proximo_data = models.DateField(db_index=True)
    proximo_feito_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_hora']


class Cotacao(models.Model):
    STATUS_CHOICES = [
        ('AGUARDANDO', 'Aguardando o gestor'),
        ('CONTRAPROPOSTA', 'Contraproposta para responder'),
        ('APROVADA', 'Aprovada · aguardando lançamento'),
        ('LANCADA', 'Lançada no SGA'),
        ('RECUSADA', 'Recusada'),
        ('DESISTIU', 'Cliente não aceitou'),
    ]
    ABERTOS = ('AGUARDANDO', 'CONTRAPROPOSTA', 'APROVADA')
    CONDICAO_CHOICES = [
        ('', 'Sem condição'),
        ('SINAL30', 'Sinal de 30% na programação'),
        ('VOLUME_MIN', 'Volume mínimo'),
    ]

    produtor = models.ForeignKey(Produtor, on_delete=models.PROTECT, related_name='cotacoes')
    contato = models.ForeignKey(Contato, on_delete=models.SET_NULL, null=True, blank=True, related_name='cotacoes')
    vendedor = models.ForeignKey(VendedorAgro, on_delete=models.SET_NULL, null=True, blank=True, related_name='cotacoes')
    autor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='AGUARDANDO', db_index=True)

    produto_cod = models.IntegerField()
    produto_nome = models.CharField(max_length=150)
    unidade = models.CharField(max_length=6, blank=True, default='TN')
    filial = models.IntegerField(default=0)
    volume_t = models.DecimalField(max_digits=12, decimal_places=2)
    retirada = models.DateField(help_text='Mês previsto de retirada (dia 1º)')
    preco = models.DecimalField(max_digits=10, decimal_places=2, help_text='R$/t FOB fábrica')
    preco_padrao = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    prazo_dias = models.PositiveSmallIntegerField(default=0)
    justificativa = models.TextField(blank=True, default='')
    pendencia_credito = models.CharField(max_length=200, blank=True, default='')

    # Decisão do gestor (aprovação, recusa ou contraproposta)
    decidido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    decidido_em = models.DateTimeField(null=True, blank=True)
    aprovada_direto = models.BooleanField(default=False, help_text='Aprovada na hora (preço padrão) sem passar pelo gestor')
    contra_preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    contra_prazo = models.PositiveSmallIntegerField(null=True, blank=True)
    contra_condicao = models.CharField(max_length=12, choices=CONDICAO_CHOICES, blank=True, default='')
    recado = models.TextField(blank=True, default='')
    respondida_em = models.DateTimeField(null=True, blank=True)
    aprovada_em = models.DateTimeField(null=True, blank=True, help_text='Entrou na fila do interno')

    # Lançamento no SGA pelo interno e conferência
    pedido_sga = models.IntegerField(null=True, blank=True, db_index=True)
    lancado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    lancado_em = models.DateTimeField(null=True, blank=True)
    conferencia = models.JSONField(default=dict, blank=True)
    divergente = models.BooleanField(default=False)
    corrigido_em = models.DateTimeField(null=True, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Cotação'
        verbose_name_plural = 'Cotações'

    @property
    def preco_final(self) -> Decimal:
        """Preço que vale: o da contraproposta aceita ou o pedido."""
        return self.contra_preco if self.contra_preco is not None and self.respondida_em else self.preco

    @property
    def prazo_final(self) -> int:
        return self.contra_prazo if self.contra_prazo is not None and self.respondida_em else self.prazo_dias


class AreaPlantada(models.Model):
    """IBGE/PAM (SIDRA tabela 5457, variável 8331): hectares plantados por município, cultura e ano."""

    ano = models.PositiveSmallIntegerField()
    municipio_ibge = models.IntegerField(db_index=True)
    municipio = models.CharField(max_length=80)
    cultura = models.CharField(max_length=30)
    hectares = models.DecimalField(max_digits=12, decimal_places=1)

    class Meta:
        unique_together = [('ano', 'municipio_ibge', 'cultura')]


class ImovelCar(models.Model):
    """Imóvel rural do CAR/SICAR (camada pública sicar_imoveis_rs), guardado ao consultar.

    O CAR público não traz nome nem CPF do dono: o vínculo com o produtor é feito pelo
    vendedor (check-in na visita ou "registrar visita" a partir da prospecção).
    """

    codigo = models.CharField(max_length=60, unique=True)
    municipio_ibge = models.IntegerField(db_index=True)
    municipio = models.CharField(max_length=80)
    area_ha = models.DecimalField(max_digits=12, decimal_places=2)
    modulos_fiscais = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=4, blank=True, default='')
    tipo = models.CharField(max_length=4, blank=True, default='')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    geometria = models.JSONField(default=dict, blank=True, help_text='GeoJSON (MultiPolygon), coordenadas com 5 casas')
    lavoura_ha = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    lavoura_pct = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    lavoura_ano = models.PositiveSmallIntegerField(null=True, blank=True)
    buscado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-area_ha']


class BuscaCarMunicipio(models.Model):
    """Quando a lista de imóveis do município foi baixada do CAR (refaz depois de 30 dias)."""

    municipio_ibge = models.IntegerField(unique=True)
    area_minima = models.DecimalField(max_digits=8, decimal_places=1)
    total = models.PositiveIntegerField(default=0)
    buscado_em = models.DateTimeField(auto_now=True)
