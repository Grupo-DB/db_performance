from rest_framework import serializers

from .models import Pergunta, Pesquisa, Resposta, RespostaItem


class PerguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pergunta
        fields = [
            'id', 'secao', 'ordem', 'enunciado', 'tipo', 'obrigatoria',
            'escala_min', 'escala_max', 'rotulo_min', 'rotulo_max', 'opcoes',
        ]


class PesquisaSerializer(serializers.ModelSerializer):
    """
    A pesquisa com as perguntas aninhadas — o editor manda tudo de uma vez.

    Escrever as perguntas junto evita o vaivém de criar a pesquisa, pegar o id e
    mandar pergunta por pergunta; o editor é uma tela só e salva uma vez.
    """

    perguntas = PerguntaSerializer(many=True, required=False)
    total_respostas = serializers.SerializerMethodField()
    link_publico = serializers.SerializerMethodField()

    class Meta:
        model = Pesquisa
        fields = [
            'id', 'titulo', 'codigo_formulario', 'versao', 'descricao',
            'mensagem_abertura', 'mensagem_encerramento', 'status', 'token',
            'data_inicio', 'data_fim', 'coleta_setor', 'setor_obrigatorio',
            'criada_em', 'alterada_em', 'perguntas', 'total_respostas', 'link_publico',
        ]
        read_only_fields = ['token', 'criada_em', 'alterada_em']

    def get_total_respostas(self, obj) -> int:
        return obj.respostas.count()

    def get_link_publico(self, obj) -> str:
        return f'/p/pesquisa/{obj.token}'

    def create(self, validated_data):
        perguntas = validated_data.pop('perguntas', [])
        pesquisa = Pesquisa.objects.create(**validated_data)
        self._gravar_perguntas(pesquisa, perguntas)
        return pesquisa

    def update(self, instance, validated_data):
        perguntas = validated_data.pop('perguntas', None)
        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)
        instance.save()
        # `None` = o cliente não mandou o campo e as perguntas ficam como estão.
        # Lista vazia = o editor apagou todas, e isso tem de valer.
        if perguntas is not None:
            self._gravar_perguntas(instance, perguntas, substituir=True)
        return instance

    def _gravar_perguntas(self, pesquisa, perguntas, substituir=False):
        if substituir:
            # Recriar em vez de casar por id: o editor reordena, insere no meio e
            # remove; casar item a item daria mais código do que vale. As respostas
            # já enviadas seguram as perguntas antigas pela FK — por isso o editor
            # é bloqueado depois da primeira resposta (ver PesquisaViewSet).
            pesquisa.perguntas.all().delete()
        for ordem, dados in enumerate(perguntas):
            dados.pop('id', None)
            dados['ordem'] = dados.get('ordem') or ordem + 1
            Pergunta.objects.create(pesquisa=pesquisa, **dados)


class PesquisaPublicaSerializer(serializers.ModelSerializer):
    """O que o formulário público precisa — sem nada de gestão."""

    perguntas = PerguntaSerializer(many=True, read_only=True)

    class Meta:
        model = Pesquisa
        fields = [
            'titulo', 'codigo_formulario', 'versao', 'descricao',
            'mensagem_abertura', 'mensagem_encerramento',
            'coleta_setor', 'setor_obrigatorio', 'perguntas',
        ]


class RespostaItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RespostaItem
        fields = ['pergunta', 'valor_numero', 'valor_texto', 'valor_opcoes']


class RespostaSerializer(serializers.ModelSerializer):
    itens = RespostaItemSerializer(many=True)

    class Meta:
        model = Resposta
        fields = ['id', 'setor', 'enviada_em', 'impressao', 'itens']
        read_only_fields = ['id', 'enviada_em']
