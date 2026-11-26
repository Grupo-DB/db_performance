from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from decimal import Decimal


def upload_image_fabricante(fabricante, filename):
    return f"fabricante_{fabricante.id}-{filename}"


def upload_image_produto(produto, filename):
    return f"produto_{produto.id}-{filename}"


def upload_catalogo_pdf(instance, filename):
    return f"catalogos/pdf/{instance.veiculo_id or 'geral'}/{filename}"


def upload_anexo_pedido(instance, filename):
    return f"pedidos/anexos/{instance.pedido_id}/{filename}"


def upload_imagem_item_nao_catalogado(instance, filename):
    return f"pedidos/nao_catalogados/{instance.pedido_id}/{filename}"


class Fabricante(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    image = models.FileField(upload_to=upload_image_fabricante, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Fabricante'
        verbose_name_plural = 'Fabricantes'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Equipamento(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False, unique=True)
    descricao = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Equipamento'
        verbose_name_plural = 'Equipamentos'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Veiculo(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    modelo = models.CharField(max_length=255, null=False, blank=False)
    fabricante = models.ForeignKey(Fabricante, on_delete=models.RESTRICT, related_name='veiculos')
    equipamento = models.ForeignKey(Equipamento, on_delete=models.RESTRICT, related_name='veiculos')
    descricao = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Veículo'
        verbose_name_plural = 'Veículos'
        ordering = ['nome']
        unique_together = [['fabricante', 'equipamento', 'modelo']]
        indexes = [
            models.Index(fields=['fabricante', 'equipamento']),
        ]

    def __str__(self):
        return f"{self.fabricante.nome} {self.nome} ({self.modelo})"


class Secao(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='secoes', null=True, blank=True)
    descricao = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Seção'
        verbose_name_plural = 'Seções'
        ordering = ['nome']
        indexes = [
            models.Index(fields=['veiculo', 'ativo']),
        ]

    def __str__(self):
        if self.veiculo:
            return f"{self.veiculo.nome} - {self.nome}"
        return self.nome


class Item(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=455, null=False, blank=False)
    apelido = models.CharField(max_length=255, blank=True, null=True)
    descricao = models.TextField(blank=True, null=True)
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE, related_name='itens', null=True, blank=True)
    secao = models.ForeignKey(Secao, on_delete=models.RESTRICT, related_name='itens', null=True, blank=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    cod_catalogo = models.CharField(max_length=100, blank=True, null=True, unique=True)
    cod_minerion = models.CharField(max_length=100, blank=True, null=True, unique=True)
    referencia = models.CharField(max_length=255, blank=True, null=True)
    localizacao = models.CharField(max_length=255, blank=True, null=True)
    image = models.FileField(upload_to=upload_image_produto, blank=True, null=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Item'
        verbose_name_plural = 'Itens'
        ordering = ['nome']
        indexes = [
            models.Index(fields=['veiculo', 'ativo']),
            models.Index(fields=['secao', 'ativo']),
            models.Index(fields=['cod_catalogo']),
            models.Index(fields=['cod_minerion']),
        ]

    def __str__(self):
        return self.nome


class Pedido(models.Model):
    STATUS_CHOICES = [
        ('SOLICITADO', 'Solicitado'),
        ('ACEITO', 'Aceito'),
        ('REJEITADO', 'Rejeitado'),
        ('COTACAO', 'Em Cotação'),
        ('REALIZADO', 'Realizado'),
        ('EM_TRANSPORTE', 'Em Transporte'),
        ('FINALIZADO', 'Finalizado'),
    ]

    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pedidos')
    responsavel = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='pedidos_responsavel'
    )
    numero_referencia = models.CharField(max_length=50, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SOLICITADO')
    motivo_rejeicao = models.TextField(blank=True, null=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(Decimal('0.00'))])
    observacoes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Pedido'
        verbose_name_plural = 'Pedidos'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['usuario', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"Pedido {self.numero_referencia} - {self.usuario.username}"

    def calcular_total(self):
        total = sum(item.subtotal for item in self.itens_pedido.all())
        self.total = total
        self.save(update_fields=['total'])
        return total


class CatalogoPDF(models.Model):
    id = models.AutoField(primary_key=True)
    titulo = models.CharField(max_length=255)
    arquivo = models.FileField(upload_to=upload_catalogo_pdf)
    veiculo = models.ForeignKey(
        Veiculo, on_delete=models.SET_NULL, null=True, blank=True, related_name='catalogos_pdf'
    )
    descricao = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Catálogo PDF'
        verbose_name_plural = 'Catálogos PDF'
        ordering = ['-created_at']

    def __str__(self):
        return self.titulo


class ItemErpCatalogo(models.Model):
    """Mapeamento entre código do item no ERP (ESTQCOD) e código no catálogo PDF."""
    id = models.AutoField(primary_key=True)
    cod_erp = models.CharField(max_length=50, unique=True, db_index=True)
    nome_erp = models.CharField(max_length=455, blank=True, null=True)
    cod_catalogo = models.CharField(max_length=100, blank=True, null=True)
    catalogo = models.ForeignKey(
        CatalogoPDF, on_delete=models.SET_NULL, null=True, blank=True, related_name='itens_mapeados'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Mapeamento Item ERP → Catálogo'
        verbose_name_plural = 'Mapeamentos Item ERP → Catálogo'
        indexes = [
            models.Index(fields=['cod_erp']),
            models.Index(fields=['cod_catalogo']),
        ]

    def __str__(self):
        return f"ERP:{self.cod_erp} → Catálogo:{self.cod_catalogo or '-'}"


class EquipamentoCatalogo(models.Model):
    """Mapeia o campo MARCA do ERP (exibido como 'Equipamento' no front) a um CatalogoPDF."""
    equipamento = models.CharField(max_length=255, unique=True, db_index=True, verbose_name='Equipamento (MARCA ERP)')
    catalogo = models.ForeignKey(
        CatalogoPDF, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mapeamentos_equipamento', verbose_name='Catálogo PDF'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Mapeamento Equipamento → Catálogo'
        verbose_name_plural = 'Mapeamentos Equipamento → Catálogo'
        ordering = ['equipamento']

    def __str__(self):
        return f"{self.equipamento} → {self.catalogo.titulo if self.catalogo else '-'}"


class ItemPedido(models.Model):
    id = models.AutoField(primary_key=True)
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='itens_pedido')
    # Item local (legado) — pode ser nulo quando o item vem do ERP
    item = models.ForeignKey(Item, on_delete=models.RESTRICT, null=True, blank=True)
    # Item do ERP — preenchido quando o produto vem da consulta ERP
    cod_erp = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    nome_produto = models.CharField(max_length=455, blank=True, null=True)
    quantidade = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Item do Pedido'
        verbose_name_plural = 'Itens do Pedido'
        indexes = [
            models.Index(fields=['pedido', 'item']),
            models.Index(fields=['pedido', 'cod_erp']),
        ]

    def __str__(self):
        nome = self.nome_produto or (self.item.nome if self.item else self.cod_erp or '?')
        return f"{nome} x{self.quantidade}"

    @property
    def subtotal(self):
        return self.quantidade * self.preco_unitario

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.pedido.calcular_total()


class AnexoPedido(models.Model):
    id = models.AutoField(primary_key=True)
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='anexos')
    arquivo = models.ImageField(upload_to=upload_anexo_pedido)
    descricao = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Anexo de Pedido'
        verbose_name_plural = 'Anexos de Pedido'
        ordering = ['created_at']

    def __str__(self):
        return f"Anexo {self.id} - Pedido {self.pedido.numero_referencia}"


class ItemPedidoNaoCatalogado(models.Model):
    """Item que o solicitante não encontrou no catálogo; segue junto ao pedido
    para o comprador cadastrar no ERP."""
    id = models.AutoField(primary_key=True)
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='itens_nao_catalogados')
    nome = models.CharField(max_length=455)
    unidade = models.CharField(max_length=50, blank=True, null=True, help_text='Unidade de medida (ex.: PEÇA, UN, METRO)')
    equipamento = models.CharField(max_length=455, blank=True, null=True, help_text='Equipamento a ser aplicado')
    imagem = models.ImageField(upload_to=upload_imagem_item_nao_catalogado, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Item não catalogado'
        verbose_name_plural = 'Itens não catalogados'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.nome} (não catalogado) - Pedido {self.pedido.numero_referencia}"


class PedidoNotificacao(models.Model):
    TIPO_CHOICES = [
        ('CRIACAO',          'Pedido Solicitado'),
        ('STATUS_RECEBIDO',  'Pedido Aceito'),
        ('STATUS_COTACAO',   'Pedido em Cotação'),
        ('STATUS_APROVADO',  'Pedido Aprovado'),
        ('STATUS_REJEITADO', 'Pedido Rejeitado'),
        ('STATUS_REALIZADO', 'Pedido Realizado/Transporte/Finalizado'),
        ('CANCELAMENTO',     'Pedido Cancelado'),
    ]

    id = models.AutoField(primary_key=True)
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='notificacoes')
    usuario_notificado = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notificacoes_pedidos')
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    mensagem = models.TextField()
    lido = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Notificação de Pedido'
        verbose_name_plural = 'Notificações de Pedido'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['usuario_notificado', '-created_at']),
            models.Index(fields=['usuario_notificado', 'lido']),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.pedido.numero_referencia}"


# ── Almoxarifado: parâmetros que deixaram de vir do SGA (12/11/2026) ─────────

class MinimoEstoque(models.Model):
    """Estoque mínimo por item e filial, controlado no app (antes era QESTQESTMIN do SGA)."""
    ORIGENS = [('app', 'Cadastrado no app'), ('sga', 'Importado do SGA')]

    item = models.IntegerField(db_index=True, help_text='ESTQCOD do SGA')
    filial = models.IntegerField(default=0, help_text='FILCOD do SGA; 0 = matriz')
    minimo = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal('0'))])
    origem = models.CharField(max_length=3, choices=ORIGENS, default='app')
    alterado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    alterado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Estoque mínimo'
        verbose_name_plural = 'Estoques mínimos'
        unique_together = ('item', 'filial')

    def __str__(self):
        return f'Item {self.item} / filial {self.filial}: {self.minimo}'


class PrazoAtencaoGrupo(models.Model):
    """Dias de cobertura que acendem o "atenção" num grupo de itens; vale para os subgrupos sem prazo próprio."""
    grupo = models.IntegerField(unique=True, help_text='GALMCOD do SGA')
    dias = models.PositiveIntegerField()
    alterado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    alterado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Prazo de atenção do grupo'
        verbose_name_plural = 'Prazos de atenção dos grupos'

    def __str__(self):
        return f'Grupo {self.grupo}: {self.dias} dias'


class PainelInsumosSetor(models.Model):
    """Painel de Insumos de um setor (26/11/2026): o gestor de compras monta e escolhe os chefes que o
    acompanham. O chefe (grupo comprasChefeSetor, posto e tirado sozinho) só vê os painéis dele."""
    nome = models.CharField(max_length=80)
    filial = models.IntegerField(null=True, blank=True, help_text='FILCOD do SGA (0 = matriz); vazio = "Todas as filiais"')
    responsaveis = models.ManyToManyField(User, blank=True, related_name='paineis_insumos_setor')
    criado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Painel de insumos do setor'
        verbose_name_plural = 'Painéis de insumos dos setores'
        ordering = ('nome', 'id')

    def __str__(self):
        return self.nome


class InsumoMonitorado(models.Model):
    """O que aparece no painel de Insumos (17/11/2026): um grupo do SGA (com os subgrupos) ou um item avulso."""
    TIPOS = [('grupo', 'Grupo de itens'), ('item', 'Item')]

    tipo = models.CharField(max_length=5, choices=TIPOS)
    codigo = models.IntegerField(help_text='GALMCOD (grupo) ou ESTQCOD (item) do SGA')
    # 23/11/2026: cada filial tem a própria seleção (pedido do planejamento — trocar de filial não
    # pode obrigar a ligar e desligar itens). Vazio = a seleção de "Todas as filiais".
    filial = models.IntegerField(null=True, blank=True, help_text='FILCOD do SGA (0 = matriz); vazio = "Todas as filiais"')
    # 23/11/2026: painel próprio por usuário. Vazio = o PADRÃO da filial (o que o gestor configura e
    # quem não personalizou vê). Com usuário = o painel dele, criado como cópia do padrão na 1ª mudança.
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='+',
                                help_text='Dono do painel personalizado; vazio = padrão da filial')
    # Foto do cartão: item do SGA cuja foto representa o monitorado. Vazio = automática
    # (o item de maior consumo do cartão que tiver foto).
    foto_item = models.IntegerField(null=True, blank=True, help_text='ESTQCOD da foto do cartão; vazio = automática')
    # 26/11/2026: linha de um painel de setor (aí usuario fica vazio e filial = a do painel).
    painel_setor = models.ForeignKey(PainelInsumosSetor, on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='monitorados')
    ordem = models.PositiveIntegerField(default=0)
    incluido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    incluido_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Insumo monitorado'
        verbose_name_plural = 'Insumos monitorados'
        unique_together = ('usuario', 'painel_setor', 'filial', 'tipo', 'codigo')
        ordering = ('ordem', 'id')

    def __str__(self):
        return f'{self.get_tipo_display()} {self.codigo}'


# ---------------------------------------------------------------------------------------------------------
# 26/11/2026 — Peças da oficina: catálogo do fabricante (PDF importado) e solicitações do chefe da oficina.
# Os desenhos ficam em privado/catalogos_pecas/<catalogo>/ (caminho relativo guardado em `desenho`).
# ---------------------------------------------------------------------------------------------------------

class CatalogoPecas(models.Model):
    """Um catálogo de peças do fabricante (ex.: Randon RK 430M DC13), importado do PDF oficial."""
    nome = models.CharField(max_length=120)
    fabricante = models.CharField(max_length=80, blank=True, default='')
    edicao = models.CharField(max_length=60, blank=True, default='')
    arquivo = models.CharField(max_length=255, blank=True, default='', help_text='PDF original (caminho em privado/)')
    paginas = models.PositiveIntegerField(default=0)
    importado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    importado_em = models.DateTimeField(auto_now=True)
    # 26/11/2026: o PDF sobe pela tela e é lido em segundo plano (Celery); a tela acompanha pela situação.
    STATUS_CHOICES = (('pronto', 'Pronto'), ('importando', 'Importando'), ('erro', 'Erro'))
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pronto')
    erro = models.TextField(blank=True, default='', help_text='Falha da última importação (o catálogo anterior fica)')
    enviado_em = models.DateTimeField(null=True, blank=True, help_text='Quando o último PDF foi enviado')

    class Meta:
        verbose_name = 'Catálogo de peças do fabricante'
        verbose_name_plural = 'Catálogos de peças do fabricante'
        ordering = ('nome', 'id')

    def __str__(self):
        return self.nome


class ConjuntoPecas(models.Model):
    """Uma página (ou sequência de páginas) do catálogo: um conjunto com desenho explodido."""
    catalogo = models.ForeignKey(CatalogoPecas, on_delete=models.CASCADE, related_name='conjuntos')
    codigo = models.CharField(max_length=30, help_text='Código do conjunto no catálogo, ex. "2A300 00.0"')
    nome = models.CharField(max_length=200)
    pagina = models.PositiveIntegerField(help_text='Primeira página no PDF (1 = capa)')
    desenho = models.CharField(max_length=255, blank=True, default='', help_text='JPEG em privado/')
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Conjunto do catálogo'
        verbose_name_plural = 'Conjuntos do catálogo'
        unique_together = ('catalogo', 'codigo')
        ordering = ('catalogo', 'ordem', 'id')

    def __str__(self):
        return f'{self.codigo} {self.nome}'


class PecaCatalogo(models.Model):
    """Uma linha da tabela do conjunto. `faixas` = [[início, fim], ...] de número de série em que vale."""
    conjunto = models.ForeignKey(ConjuntoPecas, on_delete=models.CASCADE, related_name='pecas')
    fig = models.CharField(max_length=10, help_text='Número no desenho')
    codigo = models.CharField(max_length=30, blank=True, default='', db_index=True)
    quantidade = models.CharField(max_length=10, blank=True, default='', help_text='Como no catálogo ("01", "CN")')
    descricao = models.CharField(max_length=300)
    nota = models.CharField(max_length=200, blank=True, default='')
    ver = models.CharField(max_length=30, blank=True, default='', help_text='Subconjunto com página própria')
    faixas = models.JSONField(default=list, blank=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Peça do catálogo'
        verbose_name_plural = 'Peças do catálogo'
        ordering = ('conjunto', 'ordem', 'id')

    def __str__(self):
        return f'{self.fig} {self.codigo} {self.descricao}'


class EquipamentoPecas(models.Model):
    """Equipamento do SGA (EQPCOD) → catálogo do fabricante e número de série (filtra as faixas)."""
    equipamento = models.IntegerField(unique=True, help_text='EQPCOD do SGA')
    nome = models.CharField(max_length=200, blank=True, default='', help_text='Nome no SGA quando foi ligado')
    catalogo = models.ForeignKey(CatalogoPecas, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='equipamentos')
    serie = models.PositiveIntegerField(null=True, blank=True, help_text='Nº de série do catálogo (colunas Início/Fim)')
    alterado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    alterado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Equipamento × catálogo de peças'
        verbose_name_plural = 'Equipamentos × catálogos de peças'

    def __str__(self):
        return f'{self.equipamento} {self.nome}'


class SolicitacaoPecas(models.Model):
    """Pedido de peças do chefe da oficina para um equipamento. Fica só no Manager (o comprador lança no SGA)."""
    STATUS = [
        ('aberta', 'Aberta'),
        ('em_compra', 'Em compra'),
        ('atendida', 'Atendida'),
        ('cancelada', 'Cancelada'),
    ]
    numero = models.PositiveIntegerField(unique=True, null=True, blank=True)
    equipamento = models.IntegerField(null=True, blank=True, help_text='EQPCOD do SGA')
    equipamento_nome = models.CharField(max_length=200, blank=True, default='')
    catalogo = models.ForeignKey(CatalogoPecas, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    serie = models.PositiveIntegerField(null=True, blank=True)
    solicitante = models.ForeignKey(User, on_delete=models.PROTECT, related_name='solicitacoes_pecas')
    status = models.CharField(max_length=10, choices=STATUS, default='aberta', db_index=True)
    urgente = models.BooleanField(default=False)
    observacao = models.TextField(blank=True, default='')
    resposta = models.TextField(blank=True, default='', help_text='Recado do comprador')
    tratado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Solicitação de peças da oficina'
        verbose_name_plural = 'Solicitações de peças da oficina'
        ordering = ('-criado_em', '-id')

    def __str__(self):
        return f'Solicitação {self.numero or self.pk} — {self.equipamento_nome}'


class ItemSolicitacaoPecas(models.Model):
    solicitacao = models.ForeignKey(SolicitacaoPecas, on_delete=models.CASCADE, related_name='itens')
    peca = models.ForeignKey(PecaCatalogo, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    codigo = models.CharField(max_length=30, blank=True, default='', help_text='Código do fabricante')
    descricao = models.CharField(max_length=300)
    conjunto = models.CharField(max_length=250, blank=True, default='', help_text='Conjunto e figura, para achar no catálogo')
    quantidade = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    item_sga = models.IntegerField(null=True, blank=True, help_text='ESTQCOD sugerido no momento do pedido')
    observacao = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        verbose_name = 'Item da solicitação de peças'
        verbose_name_plural = 'Itens das solicitações de peças'
        ordering = ('id',)
