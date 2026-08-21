from rest_framework import serializers
from django.contrib.auth.models import User

from .models import (
    Contato, Fila, Conversa, Mensagem, MensagemAnexo, NumeroNegocio,
    WhatsAppNotificacao,
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

    class Meta:
        model = Fila
        fields = [
            'id', 'nome', 'descricao', 'ativa', 'ordem', 'palavras_chave',
            'is_padrao', 'membros', 'membros_ids', 'criado_por', 'criado_em',
        ]
        read_only_fields = ['criado_por', 'criado_em']


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
        Guarda só dígitos.

        A tela deixa digitar "(55) 99629-4108", mas a Meta identifica o cliente
        por `wa_id`, que é dígito puro com DDI. Normalizar na entrada evita o
        mesmo contato cadastrado duas vezes com máscaras diferentes — o `unique`
        do campo não pegaria isso.
        """
        digitos = ''.join(c for c in (valor or '') if c.isdigit())
        if len(digitos) < 10:
            raise serializers.ValidationError('Telefone incompleto. Use DDI + DDD + número.')
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
