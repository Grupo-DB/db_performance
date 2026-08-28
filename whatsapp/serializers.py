from rest_framework import serializers
from django.contrib.auth.models import User

from . import services
from .telefone import telefone_para_envio
from .models import (
    Contato, Disparo, DisparoDestinatario, Fila, Conversa, Mensagem, MensagemAnexo,
    NumeroNegocio, WhatsAppNotificacao,
)


class UserMinSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']


class FilaSerializer(serializers.ModelSerializer):
    membros = UserMinSerializer(many=True, read_only=True)
    membros_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='membros', write_only=True,
        many=True, required=False,
    )
    # Atendimento pessoal (RH) x compartilhado (TI). A tela usa isto para separar
    # "aguardando atendimento" de "em atendimento": onde cada conversa tem dono,
    # a pilha sem dono É o trabalho a fazer, e ela some no meio da lista.
    atendimento_pessoal = serializers.SerializerMethodField()

    class Meta:
        model = Fila
        fields = [
            'id', 'nome', 'descricao', 'ativa', 'ordem', 'palavras_chave',
            'is_padrao', 'membros', 'membros_ids', 'criado_por', 'criado_em',
            'atendimento_pessoal',
        ]
        read_only_fields = ['criado_por', 'criado_em']

    def get_atendimento_pessoal(self, obj) -> bool:
        # Memoizado no contexto da requisição: esta fila vem aninhada em CADA
        # conversa da listagem, e resolver o escopo consulta os números da
        # empresa — sem o cache seriam duas consultas por linha da lista.
        cache = self.context.setdefault('_pessoal_por_numero', {})
        if obj.numero_id not in cache:
            cache[obj.numero_id] = services.atendimento_pessoal_do_numero(obj.numero_id)
        return cache[obj.numero_id]


class MensagemAnexoSerializer(serializers.ModelSerializer):
    class Meta:
        model = MensagemAnexo
        fields = ['id', 'arquivo', 'nome_original', 'tamanho', 'mime_type', 'criado_em']
        read_only_fields = ['nome_original', 'tamanho', 'mime_type', 'criado_em']


class MensagemCitadaSerializer(serializers.ModelSerializer):
    """
    Resumo da mensagem citada — só o que a bolha precisa desenhar acima da
    resposta. Deliberadamente raso: aninhar a mensagem inteira abriria uma
    corrente de citações de citações.
    """
    autor = UserMinSerializer(read_only=True)

    class Meta:
        model = Mensagem
        fields = ['id', 'direcao', 'tipo', 'texto', 'autor']


class MensagemSerializer(serializers.ModelSerializer):
    autor = UserMinSerializer(read_only=True)
    anexos = MensagemAnexoSerializer(many=True, read_only=True)
    anexo = serializers.FileField(write_only=True, required=False)
    # `responde_a` entra como id (o que a tela manda) e sai como `citada`, já
    # resumida: são dois campos sobre o mesmo vínculo porque a tela precisa
    # mostrar o texto citado sem uma segunda requisição.
    responde_a = serializers.PrimaryKeyRelatedField(
        queryset=Mensagem.objects.all(), write_only=True, required=False, allow_null=True,
    )
    citada = MensagemCitadaSerializer(source='responde_a', read_only=True)
    contatos = serializers.SerializerMethodField()

    def get_contatos(self, mensagem):
        """
        Cartões de contato, normalizados para a bolha.

        Sai daqui e não de `payload_bruto` cru porque aquele campo guarda o
        webhook inteiro da Meta — expor o objeto todo para a tela seria vazar
        estrutura interna e trafegar muito mais do que a bolha usa.

        Serve para os dois sentidos: a chave `contacts` é a mesma no que a Meta
        manda e no que nós montamos ao enviar.
        """
        if mensagem.tipo != 'CONTATO':
            return []
        cartoes = (mensagem.payload_bruto or {}).get('contacts') or []
        resultado = []
        for cartao in cartoes:
            telefones = cartao.get('phones') or []
            resultado.append({
                'nome': (cartao.get('name') or {}).get('formatted_name') or '',
                # `wa_id` é o número no formato da Meta; `phone` é como a pessoa
                # digitou. O primeiro é o que serve para conversar.
                'telefone': (telefones[0].get('wa_id') or telefones[0].get('phone') or '')
                            if telefones else '',
                'empresa': (cartao.get('org') or {}).get('company') or '',
            })
        return resultado

    class Meta:
        model = Mensagem
        fields = [
            'id', 'conversa', 'direcao', 'tipo', 'texto', 'autor', 'anexos', 'anexo',
            'responde_a', 'citada', 'contatos',
            'template_nome', 'wa_message_id', 'status_entrega', 'erro_detalhe', 'created_at',
            'enviada_pelo_celular',
        ]
        read_only_fields = [
            'conversa', 'direcao', 'tipo', 'template_nome', 'wa_message_id',
            'status_entrega', 'erro_detalhe', 'created_at', 'autor',
            'enviada_pelo_celular',
        ]


class ConversaListSerializer(serializers.ModelSerializer):
    # Por qual número da empresa a conversa entrou — com mais de um número, a
    # tela precisa dizer qual, senão o atendente responde achando que é o dele.
    numero_nome = serializers.CharField(source='numero.nome', read_only=True, default='')
    fila = FilaSerializer(read_only=True)
    responsavel = UserMinSerializer(read_only=True)
    ultima_mensagem_texto = serializers.SerializerMethodField()
    # A janela vem já na listagem porque é ela que decide se a tela mostra o
    # campo de resposta livre ou o botão de template — sem isso o atendente só
    # descobre que a janela fechou depois de digitar e tomar 409.
    dentro_da_janela_24h = serializers.BooleanField(read_only=True)

    class Meta:
        model = Conversa
        fields = [
            'id', 'contato_telefone', 'contato_nome', 'fila', 'responsavel',
            'status', 'estado_menu', 'ultima_mensagem_em', 'ultima_mensagem_texto',
            'ultima_mensagem_cliente_em', 'dentro_da_janela_24h', 'created_at',
                    'numero_nome',
        ]

    def get_ultima_mensagem_texto(self, obj):
        ultima = obj.mensagens.order_by('-created_at').first()
        return ultima.texto if ultima else ''


class ConversaDetailSerializer(serializers.ModelSerializer):
    # Por qual número da empresa a conversa entrou — com mais de um número, a
    # tela precisa dizer qual, senão o atendente responde achando que é o dele.
    numero_nome = serializers.CharField(source='numero.nome', read_only=True, default='')
    fila = FilaSerializer(read_only=True)
    responsavel = UserMinSerializer(read_only=True)
    mensagens = MensagemSerializer(many=True, read_only=True)
    dentro_da_janela_24h = serializers.BooleanField(read_only=True)
    tarefas_kanban = serializers.SerializerMethodField()

    class Meta:
        model = Conversa
        fields = [
            'id', 'contato_telefone', 'contato_nome', 'fila', 'responsavel',
            'status', 'estado_menu', 'ultima_mensagem_em', 'ultima_mensagem_cliente_em',
            'dentro_da_janela_24h', 'mensagens', 'tarefas_kanban', 'created_at',
                    'numero_nome',
        ]

    def get_tarefas_kanban(self, obj):
        """Tarefas abertas a partir desta conversa, para a tela não criar duplicadas."""
        return [
            {
                'id': t.id,
                'titulo': t.titulo,
                'quadro_nome': t.coluna.quadro.nome,
                'coluna_titulo': t.coluna.titulo,
                'concluida': t.concluido_em is not None,
            }
            for t in obj.tarefas_kanban.select_related('coluna', 'coluna__quadro').order_by('-criado_em')
        ]


class WhatsAppNotificacaoSerializer(serializers.ModelSerializer):
    # Fila da conversa: é o que permite à Central mostrar um badge por fila em vez
    # de um total solto. Vem como id (a tela já tem os nomes das filas) e é nulo em
    # conversa que ainda não escolheu setor.
    fila = serializers.IntegerField(source='conversa.fila_id', read_only=True, allow_null=True)
    # Situação da conversa: aviso de conversa ENCERRADA não vira badge de fila, porque
    # ela não está na lista de abertas — não há como abri-la para dar baixa.
    conversa_status = serializers.CharField(source='conversa.status', read_only=True)
    # Quem é o cliente. A `mensagem` do aviso NOVA_MENSAGEM é o texto que ele mandou,
    # sem dizer de quem é — no sino, fora da Central, "bom dia, e o pedido?" não
    # identifica ninguém. Sai do `select_related('conversa')` que já existe.
    contato_nome = serializers.CharField(source='conversa.contato_nome', read_only=True)
    contato_telefone = serializers.CharField(source='conversa.contato_telefone', read_only=True)

    class Meta:
        model = WhatsAppNotificacao
        fields = ['id', 'conversa', 'fila', 'conversa_status', 'tipo', 'mensagem', 'lido',
                  'created_at', 'contato_nome', 'contato_telefone']


class ContatoSerializer(serializers.ModelSerializer):
    """A agenda em si — o que foi cadastrado à mão."""

    criado_por = UserMinSerializer(read_only=True)

    class Meta:
        model = Contato
        fields = ['id', 'telefone', 'nome', 'empresa', 'observacoes', 'ativo',
                  'criado_por', 'criado_em']
        read_only_fields = ['criado_por', 'criado_em']

    def validate_telefone(self, valor):
        """
        Guarda só dígitos, com DDI.

        A tela deixa digitar "(51) 99239-3150", mas a Meta identifica o cliente
        por `wa_id`, que é dígito puro com DDI. Normalizar na entrada evita o
        mesmo contato cadastrado duas vezes com máscaras diferentes — o `unique`
        do campo não pegaria isso.

        O `< 10` de antes deixava passar celular sem código do país, e era daí
        que vinha o 131026: `51992393150` é lido pela Meta como Peru (DDI 51),
        não como DDD 51. `telefone_para_envio` põe o `55` quando o número tem
        forma brasileira; o que sobra abaixo de 12 dígitos é ambíguo de verdade
        e precisa ser digitado por extenso.
        """
        digitos = telefone_para_envio(valor)
        if len(digitos) < 12:
            raise serializers.ValidationError(
                'Telefone incompleto: informe DDI + DDD + número (ex.: 5551999998888).'
            )
        return digitos


class ContatoDaAgendaSerializer(serializers.Serializer):
    """
    Uma linha da tela de contatos: junta a agenda com quem já conversou.

    Não é ModelSerializer porque a linha não é um registro — ela sai do encontro
    de `Contato` com `Conversa` pelo telefone, e as duas metades podem faltar.
    """

    telefone = serializers.CharField()
    nome = serializers.CharField()
    empresa = serializers.CharField(allow_blank=True)
    observacoes = serializers.CharField(allow_blank=True)
    # De onde a linha veio: só agenda, só conversa, ou as duas.
    fonte = serializers.ChoiceField(choices=['AGENDA', 'CONVERSA', 'AMBOS'])
    contato_id = serializers.IntegerField(allow_null=True)
    total_conversas = serializers.IntegerField()
    ultima_conversa_id = serializers.IntegerField(allow_null=True)
    ultima_mensagem_em = serializers.DateTimeField(allow_null=True)
    ultima_conversa_status = serializers.CharField(allow_null=True)
    # Se dá para mandar texto livre agora, ou se só sai template.
    janela_aberta = serializers.BooleanField()


class NumeroNegocioSerializer(serializers.ModelSerializer):
    """
    O que a tela precisa saber do número. Sem `access_token` — segredo não sai
    daqui nem para usuário autenticado.
    """

    class Meta:
        model = NumeroNegocio
        fields = ['id', 'nome', 'telefone', 'phone_number_id', 'ativo', 'is_padrao']


class DisparoDestinatarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = DisparoDestinatario
        fields = ['id', 'contato', 'telefone', 'nome', 'status', 'erro', 'enviado_em']
        read_only_fields = fields


class DisparoSerializer(serializers.ModelSerializer):
    """
    Lista e detalhe do disparo, com o placar sempre junto.

    Os contadores vêm no mesmo payload de propósito: a tela acompanha o envio
    por polling, e buscar progresso num segundo endpoint dobraria as requisições
    de uma tela que já fica atualizando sozinha.
    """

    criado_por_nome = serializers.CharField(source='criado_por.username', read_only=True, default='')
    numero_nome = serializers.CharField(source='numero.nome', read_only=True)
    total = serializers.IntegerField(read_only=True)
    enviados = serializers.IntegerField(read_only=True)
    falhas = serializers.IntegerField(read_only=True)
    pendentes = serializers.IntegerField(read_only=True)
    # Só os contatos escolhidos na tela; a lista gravada volta em `destinatarios`.
    contatos_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, allow_empty=True,
    )
    # Quem só existe em conversa não tem id de agenda. Em vez de deixar essa
    # gente de fora — que era a maioria: 35 telefones contra 1 cadastrado — a
    # tela manda o telefone cru e o cadastro nasce aqui.
    telefones = serializers.ListField(
        child=serializers.CharField(max_length=30), write_only=True,
        required=False, allow_empty=True,
    )

    class Meta:
        model = Disparo
        fields = [
            'id', 'nome', 'numero', 'numero_nome', 'template_nome', 'idioma',
            'componentes', 'previa', 'status', 'detalhe_status',
            'criado_por', 'criado_por_nome', 'criado_em', 'iniciado_em', 'concluido_em',
            'total', 'enviados', 'falhas', 'pendentes', 'contatos_ids', 'telefones',
        ]
        read_only_fields = [
            'status', 'detalhe_status', 'criado_por', 'criado_em',
            'iniciado_em', 'concluido_em',
        ]


class DisparoDetalheSerializer(DisparoSerializer):
    destinatarios = DisparoDestinatarioSerializer(many=True, read_only=True)

    class Meta(DisparoSerializer.Meta):
        fields = DisparoSerializer.Meta.fields + ['destinatarios']
