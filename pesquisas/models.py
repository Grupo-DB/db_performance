import secrets

from django.contrib.auth.models import User
from django.db import models


def gerar_token() -> str:
    """Token do link público. 32 caracteres hex — não é adivinhável e não expõe o id."""
    return secrets.token_hex(16)


class Pesquisa(models.Model):
    """
    Um formulário de pesquisa com link público próprio.

    O primeiro caso é o F-099 (satisfação de colaboradores), mas nada aqui é
    específico dele: o RH monta as perguntas na tela e publica.
    """

    RASCUNHO = 'rascunho'
    PUBLICADA = 'publicada'
    ENCERRADA = 'encerrada'
    STATUS = [
        (RASCUNHO, 'Rascunho'),
        (PUBLICADA, 'Publicada'),
        (ENCERRADA, 'Encerrada'),
    ]

    titulo = models.CharField(max_length=200)
    # Código do formulário do SGQ (F-099) e a versão dele: o laboratório e o RH
    # identificam os documentos por esse código, não pelo título.
    codigo_formulario = models.CharField(max_length=30, blank=True, default='')
    versao = models.CharField(max_length=20, blank=True, default='')

    descricao = models.TextField(blank=True, default='')
    # Texto que abre o formulário público (o "Prezado colaborador..." do F-099).
    mensagem_abertura = models.TextField(blank=True, default='')
    # Texto da tela de "obrigado", depois de enviar.
    mensagem_encerramento = models.TextField(blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS, default=RASCUNHO)
    # Token do link público; trocar o token invalida o link antigo.
    token = models.CharField(max_length=40, unique=True, default=gerar_token, db_index=True)

    # Janela opcional. Fora dela o link responde "fora do período".
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)

    # O F-099 pede o setor sem pedir o nome: é o recorte que o RH usa para ler o
    # resultado sem quebrar o anonimato.
    coleta_setor = models.BooleanField(default=True)
    setor_obrigatorio = models.BooleanField(default=False)

    criada_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pesquisas_criadas',
    )
    criada_em = models.DateTimeField(auto_now_add=True)
    # `auto_now` de propósito: serve para saber quando o formulário mudou pela
    # última vez, não quando a pesquisa foi criada (essa é a `criada_em`).
    alterada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criada_em']
        verbose_name = 'Pesquisa'
        verbose_name_plural = 'Pesquisas'

    def __str__(self) -> str:
        return f'{self.codigo_formulario} — {self.titulo}' if self.codigo_formulario else self.titulo


class Pergunta(models.Model):
    """
    Uma pergunta do formulário.

    `secao` é só um título que agrupa na tela (o F-099 não usa, mas pesquisas
    maiores ficam ilegíveis sem isso). A escala guarda mínimo, máximo e os
    rótulos das pontas — no F-099, 1 = "Discordo totalmente" e 5 = "Concordo
    totalmente".
    """

    ESCALA = 'escala'
    TEXTO_LONGO = 'texto_longo'
    TEXTO_CURTO = 'texto_curto'
    ESCOLHA_UNICA = 'escolha_unica'
    ESCOLHA_MULTIPLA = 'escolha_multipla'
    SIM_NAO = 'sim_nao'
    NUMERO = 'numero'
    TIPOS = [
        (ESCALA, 'Escala'),
        (TEXTO_LONGO, 'Texto longo'),
        (TEXTO_CURTO, 'Texto curto'),
        (ESCOLHA_UNICA, 'Escolha única'),
        (ESCOLHA_MULTIPLA, 'Escolha múltipla'),
        (SIM_NAO, 'Sim / Não'),
        (NUMERO, 'Número'),
    ]

    # Os tipos cujo resultado é um número e admitem média/distribuição.
    TIPOS_NUMERICOS = (ESCALA, NUMERO)

    pesquisa = models.ForeignKey(Pesquisa, on_delete=models.CASCADE, related_name='perguntas')
    secao = models.CharField(max_length=120, blank=True, default='')
    ordem = models.PositiveIntegerField(default=0)

    enunciado = models.TextField()
    tipo = models.CharField(max_length=20, choices=TIPOS, default=ESCALA)
    obrigatoria = models.BooleanField(default=False)

    escala_min = models.PositiveSmallIntegerField(default=1)
    escala_max = models.PositiveSmallIntegerField(default=5)
    rotulo_min = models.CharField(max_length=60, blank=True, default='')
    rotulo_max = models.CharField(max_length=60, blank=True, default='')

    # Lista de strings para os tipos de escolha. JSONField porque a quantidade
    # varia por pergunta e nunca é consultada por opção.
    opcoes = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['ordem', 'id']
        verbose_name = 'Pergunta'
        verbose_name_plural = 'Perguntas'

    def __str__(self) -> str:
        return f'{self.ordem}. {self.enunciado[:60]}'


class Resposta(models.Model):
    """
    Uma submissão inteira do formulário público.

    NÃO guarda quem respondeu — a pesquisa promete anonimato. `impressao` é um
    identificador do APARELHO, gerado no navegador, que só serve para a tela
    saber que ali já respondeu; não liga a resposta a uma pessoa e é
    contornável de propósito (outro navegador responde de novo).
    """

    pesquisa = models.ForeignKey(Pesquisa, on_delete=models.CASCADE, related_name='respostas')
    setor = models.CharField(max_length=120, blank=True, default='')
    enviada_em = models.DateTimeField(auto_now_add=True)
    impressao = models.CharField(max_length=64, blank=True, default='', db_index=True)

    class Meta:
        ordering = ['-enviada_em']
        verbose_name = 'Resposta'
        verbose_name_plural = 'Respostas'

    def __str__(self) -> str:
        return f'Resposta #{self.pk} — {self.pesquisa.titulo}'


class RespostaItem(models.Model):
    """
    O que foi respondido em UMA pergunta.

    Três colunas em vez de uma só: o número precisa ser número para a média e a
    distribuição saírem do banco, e a escolha múltipla é lista.
    """

    resposta = models.ForeignKey(Resposta, on_delete=models.CASCADE, related_name='itens')
    pergunta = models.ForeignKey(Pergunta, on_delete=models.CASCADE, related_name='itens')

    valor_numero = models.FloatField(null=True, blank=True)
    valor_texto = models.TextField(blank=True, default='')
    valor_opcoes = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = 'Item de resposta'
        verbose_name_plural = 'Itens de resposta'
        # Uma linha por pergunta em cada submissão.
        constraints = [
            models.UniqueConstraint(fields=['resposta', 'pergunta'], name='unico_item_por_pergunta'),
        ]

    def __str__(self) -> str:
        return f'{self.pergunta_id} = {self.valor_numero or self.valor_texto[:30]}'
