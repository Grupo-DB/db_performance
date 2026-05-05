from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import Local, Royalty, Fatura
from .serializers import LocalSerializer, RoyaltySerializer, FaturaSerializer
import pandas as pd
import json

class LocalViewSet(viewsets.ModelViewSet):
    queryset = Local.objects.all()
    serializer_class = LocalSerializer

    @action(detail=False, methods=['get'], url_path='apuracao')
    def apuracao(self, request):
        # Filtros opcionais via query params (?nome=fcmI) ou body JSON ({"nome":"fcmI"})
        filtro_nome = request.query_params.get('nome') or request.data.get('nome')
        filtro_periodo = request.query_params.get('periodo') or request.data.get('periodo')

        qs_local = Local.objects.all()
        if filtro_nome:
            qs_local = qs_local.filter(nome=filtro_nome)
        if filtro_periodo:
            qs_local = qs_local.filter(periodo__icontains=filtro_periodo)

        df_local = pd.DataFrame(qs_local.values())
        df_faturas = pd.DataFrame(Fatura.objects.all().values())

        # Agregar faturas por período
        df_fat_agrupado = df_faturas.groupby('periodo').agg(
            total_servico=('total_servico', 'sum'),
            total_produto=('total_produto', 'sum')
        ).reset_index()

        # Merge entre Local e Faturas pelo campo 'periodo'
        df = df_local.merge(df_fat_agrupado, on='periodo', how='left')

        # Calcular colunas derivadas
        df['consumo_total'] = df['consumo'].sum()
        df['custo_mensal'] = (df['consumo'] / df['consumo_total']) * (df['total_servico'] + df['total_produto'])
        df['percentual'] = df['consumo'] / df['consumo_total'] * 100
        df['consumo_ton_prod'] = df['consumo'] / df['producao'] * 100
        df['custo_ton_prod'] = df['custo_mensal'] / df['producao']

        # Somar total da coluna custo_ton_prod
        #total_custo_ton_prod = df['custo_ton_prod'].sum()

        data = json.loads(df.to_json(orient='records'))

        return Response({
            #'total_custo_ton_prod': total_custo_ton_prod,
            'resultados': data,
        })

class RoyaltyViewSet(viewsets.ModelViewSet):
    queryset = Royalty.objects.all()
    serializer_class = RoyaltySerializer

class FaturaViewSet(viewsets.ModelViewSet):
    queryset = Fatura.objects.all()
    serializer_class = FaturaSerializer

