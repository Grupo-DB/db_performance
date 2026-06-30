from rest_framework import serializers
from .models import (Comissao, Meta, Regiao, Representante, ParametroComissao,
                     VinculoRepresentante, MapeamentoMunicipio,
                     RegraComissao, RegraComissaoGrupo, RegraComissaoFaixa)


class RegiaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Regiao
        fields = ['id', 'nome']


class RepresentanteSerializer(serializers.ModelSerializer):
    regiao = serializers.PrimaryKeyRelatedField(queryset=Regiao.objects.all(), write_only=True, allow_null=True, required=False)
    regiao_detalhes = RegiaoSerializer(source='regiao', read_only=True)

    class Meta:
        model = Representante
        fields = [
            'id',
            'nome',
            'empresa',
            'vendededor_externo',
            'vendedor_interno',
            'regiao',
            'segmento',
            'email',
            'telefone',
            'cpf',
            'cnpj',
            'regiao_detalhes'
        ]


class MetaSerializer(serializers.ModelSerializer):
    representante = serializers.PrimaryKeyRelatedField(queryset=Representante.objects.all(), write_only=True, allow_null=True, required=False)
    representante_detalhes = RepresentanteSerializer(source='representante', read_only=True)
    regiao = serializers.PrimaryKeyRelatedField(queryset=Regiao.objects.all(), write_only=True, allow_null=True, required=False)
    regiao_detalhes = RegiaoSerializer(source='regiao', read_only=True)

    class Meta:
        model = Meta
        fields = [
            'id',
            'regiao',
            'representante',
            'segmento',
            'grupo',
            'valor',
            'periodo',
            'data_meta',
            'representante_detalhes',
            'regiao_detalhes'
        ]


class ComissaoSerializer(serializers.ModelSerializer):
    representante = serializers.PrimaryKeyRelatedField(queryset=Representante.objects.all(), write_only=True)
    representante_detalhes = RepresentanteSerializer(source='representante', read_only=True)

    class Meta:
        model = Comissao
        fields = [
            'id',
            'representante',
            'valor',
            'periodo',
            'data_pagamento',
            'representante_detalhes'
        ]


class ParametroComissaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParametroComissao
        fields = ['id', 'chave', 'descricao', 'taxa', 'ativo', 'vigencia_inicio', 'vigencia_fim']


class VinculoRepresentanteSerializer(serializers.ModelSerializer):
    representante_externo = serializers.PrimaryKeyRelatedField(queryset=Representante.objects.all())
    representante_externo_detalhes = RepresentanteSerializer(source='representante_externo', read_only=True)
    representante_interno = serializers.PrimaryKeyRelatedField(queryset=Representante.objects.all(), allow_null=True, required=False)
    representante_interno_detalhes = RepresentanteSerializer(source='representante_interno', read_only=True)

    class Meta:
        model = VinculoRepresentante
        fields = [
            'id',
            'representante_externo',
            'representante_externo_detalhes',
            'representante_interno',
            'representante_interno_detalhes',
            'segmento',
            'apenas_filial_atm',
            'ativo',
        ]


class MapeamentoMunicipioSerializer(serializers.ModelSerializer):
    representante = serializers.PrimaryKeyRelatedField(queryset=Representante.objects.all())
    representante_detalhes = RepresentanteSerializer(source='representante', read_only=True)

    class Meta:
        model = MapeamentoMunicipio
        fields = ['id', 'cidade_estado', 'representante', 'representante_detalhes', 'segmento']


class RegraComissaoGrupoSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegraComissaoGrupo
        fields = ['id', 'grupo', 'taxa', 'taxa_potencializador']


class RegraComissaoFaixaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegraComissaoFaixa
        fields = ['id', 'pct_minimo', 'pct_maximo', 'taxa']


class RegraComissaoSerializer(serializers.ModelSerializer):
    representante = serializers.PrimaryKeyRelatedField(queryset=Representante.objects.all())
    representante_detalhes = RepresentanteSerializer(source='representante', read_only=True)
    grupos = RegraComissaoGrupoSerializer(many=True, read_only=True)
    faixas = RegraComissaoFaixaSerializer(many=True, read_only=True)

    class Meta:
        model = RegraComissao
        fields = [
            'id', 'representante', 'representante_detalhes',
            'descricao', 'tipo', 'base_calculo', 'segmento_produto',
            'taxa', 'valor_fixo', 'multiplicador', 'ordem', 'ativo',
            'filtro_filial_contem', 'filtro_cliente_contem',
            'filtro_grupo_comercial_contem', 'filtro_cidade_sufixo',
            'grupos', 'faixas',
        ]
