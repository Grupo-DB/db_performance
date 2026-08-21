from django.db import models
from django.contrib.auth.models import User


class NumeroNegocio(models.Model):
    """
    Um número de WhatsApp da empresa.

    Existe porque o `phone_number_id` era único e vinha do `.env`: toda saída
    usava o mesmo número, então mensagem que chegasse num segundo número seria
    respondida pelo primeiro — o cliente escreve para um e recebe resposta de
    outro.

    `access_token` e `waba_id` ficam em branco no caso normal: o número na MESMA
    WABA usa o token do `.env`. Só quando o número nasce em outra WABA é que
    precisa de token próprio — o token guarda um retrato dos ativos do usuário de
    sistema no momento em que foi gerado, e uma WABA que não estava naquele
    retrato devolve `code 100 / subcode 33`.
    """

    phone_number_id = models.CharField(
        max_length=50, unique=True,
        help_text='Phone Number ID da Meta (não é o telefone). Fica no WhatsApp Manager.',
    )
    nome = models.CharField(max_length=60, help_text='Como aparece na tela. Ex.: TI, Comercial')
    telefone = models.CharField(max_length=30, blank=True, help_text='Só para exibição.')
    waba_id = models.CharField(
        max_length=50, blank=True,
        help_text='Em branco = a WABA do .env. Preencha só se o número está em outra conta.',
    )
    access_token = models.TextField(
        blank=True,
        help_text='Em branco = o token do .env. Obrigatório quando a WABA é outra.',
    )
    ativo = models.BooleanField(default=True)
    is_padrao = models.BooleanField(
        default=False,
        help_text='Destino de mensagem que chegar num número não cadastrado, para o '
                  'webhook não descartar o atendimento.',
    )
    menu_automatico = models.BooleanField(
        default=True,
        help_text='Desligue em número que também é atendido no app WhatsApp Business '
                  '(coexistência): o robô mandaria o menu de setores por cima de quem '
                  'já está respondendo à mão, e o cliente receberia as duas coisas. '
                  'Desligado, a conversa entra direto na fila e a Central funciona como '
                  'caixa de entrada compartilhada.',
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Número de negócio'
        verbose_name_plural = 'Números de negócio'
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} ({self.telefone or self.phone_number_id})'

    def fila_padrao(self):
        """
        Onde cai a conversa quando este número não pergunta o setor.

        Prefere a fila marcada como padrão entre as deste número; sem ela, a
        primeira na ordem. Nulo só se ninguém cadastrou fila para o número — e aí
        a conversa fica sem fila, visível apenas para gestor, o que é melhor que
        perder a mensagem.
        """
        filas = self.filas.filter(ativa=True).order_by('-is_padrao', 'ordem', 'nome')
        return filas.first()

    @classmethod
    def resolver(cls, phone_number_id: str):
        """
        O número que recebeu a mensagem, ou o padrão quando ele não está cadastrado.

        Nunca levanta exceção: número novo configurado na Meta e esquecido aqui
        não pode fazer o webhook perder a mensagem do cliente.
        """
        if phone_number_id:
            achado = cls.objects.filter(phone_number_id=phone_number_id, ativo=True).first()
            if achado:
                return achado
        return cls.objects.filter(is_padrao=True, ativo=True).first()


class Fila(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    descricao = models.CharField(max_length=255, blank=True)
    ativa = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0, help_text='Posição no menu numérico enviado ao cliente')
    palavras_chave = models.CharField(
        max_length=255, blank=True,
        help_text='Termos separados por vírgula usados no roteamento automático (ex: compra,comprar,fornecedor)'
    )
    is_padrao = models.BooleanField(default=False, help_text='Fila de fallback quando não é possível identificar o setor')
    membros = models.ManyToManyField(User, related_name='filas_whatsapp', blank=True)
    numero = models.ForeignKey(
        NumeroNegocio, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='filas',
        help_text='Número que oferece esta fila no menu. Em branco = todos os números '
                  '(fila compartilhada).',
    )
    criado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='filas_whatsapp_criadas')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fila'
        verbose_name_plural = 'Filas'
        ordering = ['ordem', 'nome']

    def __str__(self):
        return self.nome


class Conversa(models.Model):
    STATUS_CHOICES = [
        ('ABERTA', 'Aberta'),
        ('ENCERRADA', 'Encerrada'),
    ]
    ESTADO_MENU_CHOICES = [
        ('AGUARDANDO_SETOR', 'Aguardando escolha de setor'),
        ('EM_ATENDIMENTO', 'Em atendimento'),
    ]

    contato_telefone = models.CharField(max_length=30, db_index=True)
    contato_nome = models.CharField(max_length=150, blank=True)
    numero_negocio_id = models.CharField(max_length=50, blank=True, help_text='phone_number_id do Meta que recebeu a mensagem')
    numero = models.ForeignKey(
        NumeroNegocio, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conversas',
        help_text='Número da empresa por onde esta conversa entrou. Substitui o '
                  '`numero_negocio_id` de texto, que fica só como histórico.',
    )
    fila = models.ForeignKey(Fila, on_delete=models.SET_NULL, null=True, blank=True, related_name='conversas')
    responsavel = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conversas_whatsapp_responsavel'
    )  # opcional — qualquer membro da fila pode assumir/liberar
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ABERTA')
    estado_menu = models.CharField(max_length=20, choices=ESTADO_MENU_CHOICES, default='AGUARDANDO_SETOR')
    tentativas_menu = models.PositiveSmallIntegerField(default=0)
    ultima_mensagem_em = models.DateTimeField(null=True, blank=True, db_index=True)
    ultima_mensagem_cliente_em = models.DateTimeField(null=True, blank=True, help_text='Base do cálculo da janela de 24h do WhatsApp')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Conversa'
        verbose_name_plural = 'Conversas'
        ordering = ['-ultima_mensagem_em']
        indexes = [
            models.Index(fields=['fila', 'status']),
            models.Index(fields=['responsavel', 'status']),
        ]

    def __str__(self):
        return f"{self.contato_nome or self.contato_telefone} ({self.get_status_display()})"

    @property
    def dentro_da_janela_24h(self):
        if not self.ultima_mensagem_cliente_em:
            return False
        from django.utils import timezone
        return (timezone.now() - self.ultima_mensagem_cliente_em).total_seconds() < 24 * 3600


class Mensagem(models.Model):
    DIRECAO_CHOICES = [
        ('ENTRADA', 'Entrada'),
        ('SAIDA', 'Saída'),
    ]
    TIPO_CHOICES = [
        ('TEXTO', 'Texto'),
        ('IMAGEM', 'Imagem'),
        ('DOCUMENTO', 'Documento'),
        ('AUDIO', 'Áudio'),
        ('VIDEO', 'Vídeo'),
        # Cartão de contato (o "contacts" da Cloud API). Os dados ficam em
        # `payload_bruto`, não em arquivo: é JSON, não mídia.
        ('CONTATO', 'Contato'),
    ]
    STATUS_ENTREGA_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('ENVIADA', 'Enviada'),
        ('ENTREGUE', 'Entregue'),
        ('LIDA', 'Lida'),
        ('FALHOU', 'Falhou'),
    ]

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='mensagens')
    direcao = models.CharField(max_length=10, choices=DIRECAO_CHOICES)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='TEXTO')
    texto = models.TextField(blank=True)
    autor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='mensagens_whatsapp_enviadas')
    responde_a = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='respostas',
        help_text='Mensagem citada. Na saída vira o "reply" do WhatsApp; na entrada é o que '
                  'o cliente citou (vem em context.id do webhook).',
    )
    wa_message_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    status_entrega = models.CharField(max_length=10, choices=STATUS_ENTREGA_CHOICES, default='PENDENTE')
    erro_detalhe = models.TextField(blank=True)
    template_nome = models.CharField(
        max_length=120, blank=True,
        help_text='Preenchido quando a saída foi por template aprovado (fora da janela de 24h).',
    )
    enviada_pelo_celular = models.BooleanField(
        default=False,
        help_text='Saída digitada no app WhatsApp Business (coexistência), espelhada para cá '
                  'pelo webhook. Distingue do robô: as duas são saída sem autor, e sem este '
                  'campo a tela marcaria como "automático" o que uma pessoa escreveu.',
    )
    payload_bruto = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Mensagem'
        verbose_name_plural = 'Mensagens'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversa', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.direcao}] {self.conversa} - {self.created_at:%d/%m/%Y %H:%M}"


class MensagemAnexo(models.Model):
    mensagem = models.ForeignKey(Mensagem, on_delete=models.CASCADE, related_name='anexos')
    arquivo = models.FileField(upload_to='whatsapp/anexos/%Y/%m/')
    nome_original = models.CharField(max_length=255, blank=True)
    tamanho = models.PositiveIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    wa_media_id = models.CharField(max_length=100, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.arquivo and not self.nome_original:
            # Só o nome do arquivo. Guardar `arquivo.name` inteiro fazia a Central
            # exibir "whatsapp/anexos/2026/08/15654489…" como nome do anexo.
            self.nome_original = self.arquivo.name.rsplit('/', 1)[-1]
        if self.arquivo and not self.tamanho:
            self.tamanho = self.arquivo.size
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome_original or f"Anexo {self.pk}"


class Contato(models.Model):
    """
    Agenda própria do atendimento.

    Existe porque a Cloud API **não** tem catálogo de contatos: não há endpoint
    para ler a agenda do WhatsApp, e a Meta só informa o nome do perfil de quem
    escreve (que já fica em `Conversa.contato_nome`). Este modelo guarda o que a
    conversa não dá: quem nunca escreveu, o nome interno que a empresa usa para a
    pessoa, e a observação do atendimento.

    A listagem da tela junta as duas fontes pelo telefone — quem está aqui, quem
    só apareceu em conversa, e quem está nos dois lugares. O telefone é a chave,
    no mesmo formato que a Meta usa em `wa_id` (dígitos, com DDI, sem sinais).
    """

    telefone = models.CharField(
        max_length=30, unique=True, db_index=True,
        help_text='Só dígitos, com DDI. Ex.: 5555996294108',
    )
    nome = models.CharField(max_length=150)
    empresa = models.CharField(max_length=150, blank=True)
    observacoes = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)
    criado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='contatos_whatsapp_criados',
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Contato'
        verbose_name_plural = 'Contatos'
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} ({self.telefone})'


class ConfiguracaoAtendimento(models.Model):
    """
    Textos que o robô manda sozinho, editáveis sem deploy.

    Existe porque eram literais dentro de `services.py`: trocar uma vírgula da
    saudação exigia subir código e reiniciar o worker do Celery.

    Era singleton. Com mais de um número passou a ser um registro por número,
    mais o **geral** (`numero` nulo), que atende todo número sem configuração
    própria. `carregar(numero)` é o jeito previsto de obtê-lo.
    """

    texto_menu = models.TextField(
        default='Olá! Para qual setor você deseja falar? Responda com o número:',
        help_text='Primeira linha do menu. Os setores são listados numerados logo abaixo, '
                  'a partir das Filas ativas.',
    )
    texto_roteamento = models.TextField(
        default='Você foi direcionado ao setor {setor}. Em breve alguém vai te atender.',
        help_text='Confirmação enviada quando o cliente escolhe o setor. '
                  'Use {setor} onde o nome do setor deve aparecer.',
    )
    assinatura = models.CharField(
        max_length=60, blank=True, default='Setor de TI Grupo DB',
        help_text='Nome que o cliente vê no começo de TODA resposta do atendente. É fixo de '
                  'propósito: o cliente fala com a empresa, não com uma pessoa. '
                  'Deixe em branco para não assinar nada.',
    )
    numero = models.ForeignKey(
        NumeroNegocio, on_delete=models.CASCADE, null=True, blank=True,
        related_name='configuracoes',
        help_text='Em branco = configuração geral, usada por todo número que não tiver a '
                  'sua. Preencha para dar menu, roteamento e assinatura próprios a um '
                  'número (é o que separa um setor do outro).',
    )
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='configuracoes_whatsapp_editadas',
    )

    class Meta:
        verbose_name = 'Configuração do atendimento'
        verbose_name_plural = 'Configurações do atendimento'
        constraints = [
            # Uma configuração por número. `condition` é obrigatória: sem ela o
            # unique não vale para a geral (NULL não colide com NULL) e ainda
            # daria erro de duplicidade em bancos que tratam NULL como valor.
            models.UniqueConstraint(
                fields=['numero'], condition=models.Q(numero__isnull=False),
                name='whatsapp_config_uma_por_numero',
            ),
        ]

    def __str__(self):
        if self.numero_id:
            return f'Textos automáticos — {self.numero.nome}'
        return 'Textos automáticos — geral'

    def save(self, *args, **kwargs):
        # A GERAL continua travada no pk=1: é a que `carregar()` usa como último
        # recurso, e duas gerais deixariam o robô escolhendo textos por sorteio
        # (o `unique` do banco não pega, porque MySQL aceita vários NULL).
        # A do número NÃO pode ser travada — fixar o pk aqui faria o cadastro do
        # segundo setor sobrescrever os textos do primeiro, calado.
        if self.numero_id is None:
            self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # A geral não se apaga: sem ela o atendimento fica sem texto nenhum até
        # alguém recriar. A de um número, sim — apagar é como se volta a usar a
        # geral naquele número.
        if self.numero_id is None:
            raise ValueError('A configuração geral do atendimento não pode ser excluída.')
        super().delete(*args, **kwargs)

    @classmethod
    def carregar(cls, numero=None):
        """
        A configuração do número, caindo para a geral quando ele não tem uma.

        Deixou de ser singleton quando entrou o segundo número: cada setor precisa
        do seu menu e da sua assinatura. Sem configuração própria, o número usa a
        geral — então nada muda para quem nunca cadastrar uma.
        """
        if numero is not None:
            do_numero = cls.objects.filter(numero=numero).first()
            if do_numero:
                return do_numero
        geral = cls.objects.filter(numero__isnull=True).order_by('pk').first()
        if geral:
            return geral
        return cls.objects.create()


class WhatsAppNotificacao(models.Model):
    TIPO_CHOICES = [
        ('NOVA_MENSAGEM', 'Nova Mensagem'),
        ('CONVERSA_ATRIBUIDA', 'Conversa Atribuída'),
        ('CONVERSA_TRANSFERIDA', 'Conversa Transferida'),
    ]

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='notificacoes')
    usuario_notificado = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notificacoes_whatsapp')
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    mensagem = models.CharField(max_length=255)
    lido = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Notificação de WhatsApp'
        verbose_name_plural = 'Notificações de WhatsApp'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['usuario_notificado', '-created_at']),
            models.Index(fields=['usuario_notificado', 'lido']),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.conversa}"
