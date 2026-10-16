"""Controle de uniformes (planilha "UNIFORMES DE INVERNO_2026").

A planilha tinha a aba VALORES (preço e regras) e quatro abas de pedidos —
feminino/masculino × ganha/compra — com uma coluna por peça ("1 (P)", "2 (GG)"), o
zíper do soft e as datas de entrega (a jaqueta chegou depois e tinha coluna própria).
Aqui: ``Campanha`` (Inverno/2026) → ``Peca`` (preço, faixas por tamanho) e
``Pedido`` (uma pessoa, uma modalidade) → ``ItemPedido`` (peça, quantidade, tamanho, entrega).
"""
from decimal import Decimal

from django.db import models

from avaliacoes.management.models import Colaborador

TAMANHOS = ['PP', 'P', 'M', 'G', 'GG', 'EX', 'EX1', 'EX2', 'EX3', 'EX4', 'EX5']


class Campanha(models.Model):
    nome = models.CharField(max_length=120, help_text='Ex.: Inverno/2026')
    ano = models.PositiveIntegerField()
    ativa = models.BooleanField(default=True)
    # Regras da aba VALORES, editáveis por campanha.
    camisas_quem_ganha = models.PositiveSmallIntegerField(default=2)
    parcelas_max = models.PositiveSmallIntegerField(default=3)
    regras = models.TextField(blank=True, default='')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-ano', '-id']

    def __str__(self):
        return self.nome


class Peca(models.Model):
    CAMISA = 'CAMISA'   # quem ganha leva até `camisas_quem_ganha`
    UNICA = 'UNICA'     # quem ganha escolhe UMA entre as peças deste grupo
    GRUPOS = [(CAMISA, 'Camisa'), (UNICA, 'Agasalho (uma por pessoa que ganha)')]
    PUBLICOS = [('', 'Todos'), ('F', 'Feminino'), ('M', 'Masculino')]

    campanha = models.ForeignKey(Campanha, on_delete=models.CASCADE, related_name='pecas')
    nome = models.CharField(max_length=80)
    publico = models.CharField(max_length=1, choices=PUBLICOS, blank=True, default='')
    grupo = models.CharField(max_length=10, choices=GRUPOS, default=UNICA)
    preco = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0'))
    # Faixas que fogem do preço base: {"EX1": 179, "EX4": 187} (suéter).
    precos_por_tamanho = models.JSONField(default=dict, blank=True)
    tem_ziper = models.BooleanField(default=False, help_text='Soft: fecho até a metade ou todo.')
    ordem = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['ordem', 'id']

    def __str__(self):
        return f'{self.nome}{" (" + self.get_publico_display() + ")" if self.publico else ""}'

    def preco_do_tamanho(self, tamanho: str) -> Decimal:
        valor = (self.precos_por_tamanho or {}).get((tamanho or '').upper())
        return Decimal(str(valor)) if valor not in (None, '') else self.preco


class Pedido(models.Model):
    GANHA = 'GANHA'
    COMPRA = 'COMPRA'
    MODALIDADES = [(GANHA, 'Ganha'), (COMPRA, 'Compra (desconto em folha)')]
    GENEROS = [('F', 'Feminino'), ('M', 'Masculino')]

    campanha = models.ForeignKey(Campanha, on_delete=models.CASCADE, related_name='pedidos')
    colaborador = models.ForeignKey(
        Colaborador, null=True, blank=True, on_delete=models.SET_NULL, related_name='pedidos_uniforme',
    )
    nome = models.CharField(max_length=150)
    cpf = models.CharField(max_length=14, blank=True, default='')
    setor = models.CharField(max_length=150, blank=True, default='')
    cargo = models.CharField(max_length=150, blank=True, default='')
    genero = models.CharField(max_length=1, choices=GENEROS)
    modalidade = models.CharField(max_length=6, choices=MODALIDADES)
    parcelas = models.PositiveSmallIntegerField(default=1)
    observacao = models.TextField(blank=True, default='')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} — {self.get_modalidade_display()}'


class ItemPedido(models.Model):
    ZIPERES = [('', '—'), ('TODO', 'Todo'), ('MEIO', 'Até a metade'), ('UM_DE_CADA', 'Um de cada')]

    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='itens')
    peca = models.ForeignKey(Peca, on_delete=models.PROTECT, related_name='itens')
    quantidade = models.PositiveSmallIntegerField(default=1)
    tamanho = models.CharField(max_length=10)
    ziper = models.CharField(max_length=10, choices=ZIPERES, blank=True, default='')
    entregue = models.BooleanField(default=False)
    entregue_em = models.DateField(null=True, blank=True)
    # "Jak levou", "SOBRA", "DEMITIDO", "FÉRIAS" — o que a planilha escrevia no lugar da data.
    entrega_obs = models.CharField(max_length=120, blank=True, default='')

    class Meta:
        ordering = ['peca__ordem', 'id']

    @property
    def valor(self) -> Decimal:
        return self.peca.preco_do_tamanho(self.tamanho) * self.quantidade
