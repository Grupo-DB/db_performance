"""
API do Boletim Semanal.

Uma requisição resolve o ano inteiro (`/boletim/`): a tela precisa da semana
escolhida E da evolução das outras para o gráfico, e refazer a conta semana a
semana custaria uma consulta por célula. Como o cálculo já varre o ano de uma vez
(ver services), devolver tudo junto é mais barato do que devolver só a semana.
"""
from datetime import date

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import services
from .models import IndicadorBoletim, ResultadoBoletim
from .serializers import IndicadorBoletimSerializer, ResultadoBoletimSerializer


class IndicadorBoletimViewSet(viewsets.ModelViewSet):
    """Cadastro do mapeamento indicador → ensaio/amostra. Editável também pelo admin."""
    permission_classes = [IsAuthenticated]
    serializer_class = IndicadorBoletimSerializer

    def get_queryset(self):
        qs = IndicadorBoletim.objects.prefetch_related('componentes', 'produtos').select_related('ensaio')
        if self.request.query_params.get('apenas_ativos') in ('1', 'true', 'True'):
            qs = qs.filter(ativo=True)
        return qs


class ResultadoBoletimViewSet(viewsets.ModelViewSet):
    """Correções manuais das células. O `upsert` é o que a tela usa ao editar."""
    permission_classes = [IsAuthenticated]
    serializer_class = ResultadoBoletimSerializer

    def get_queryset(self):
        qs = ResultadoBoletim.objects.select_related('usuario')
        ano = self.request.query_params.get('ano')
        if ano:
            qs = qs.filter(ano=ano)
        return qs

    def perform_create(self, serializer):
        serializer.save(usuario=self.request.user)

    def perform_update(self, serializer):
        serializer.save(usuario=self.request.user)

    @action(detail=False, methods=['post'])
    def upsert(self, request):
        """
        Grava a célula (indicador + ano + semana) sem a tela precisar saber se já
        existia registro. Valor, texto e produção todos vazios APAGAM a correção —
        é assim que se volta ao número calculado.
        """
        dados = request.data
        try:
            indicador = IndicadorBoletim.objects.get(pk=dados.get('indicador'))
        except (IndicadorBoletim.DoesNotExist, TypeError, ValueError):
            return Response({'detail': 'Indicador inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ano = int(dados.get('ano'))
            semana = int(dados.get('semana'))
        except (TypeError, ValueError):
            return Response({'detail': 'Informe ano e semana.'}, status=status.HTTP_400_BAD_REQUEST)
        if not 1 <= semana <= 53:
            return Response({'detail': 'Semana ISO vai de 1 a 53.'}, status=status.HTTP_400_BAD_REQUEST)

        valor = dados.get('valor')
        texto = (dados.get('texto') or '').strip()
        producao = dados.get('producao')
        observacao = (dados.get('observacao') or '').strip()

        def numero(bruto):
            if bruto in (None, ''):
                return None
            try:
                return float(str(bruto).replace(',', '.'))
            except ValueError:
                return None

        valor = numero(valor)
        producao = numero(producao)

        if valor is None and producao is None and not texto and not observacao:
            ResultadoBoletim.objects.filter(indicador=indicador, ano=ano, semana=semana).delete()
            return Response({'removido': True})

        resultado, _ = ResultadoBoletim.objects.update_or_create(
            indicador=indicador, ano=ano, semana=semana,
            defaults={
                'valor': valor, 'texto': texto, 'producao': producao,
                'observacao': observacao, 'usuario': request.user,
            },
        )
        return Response(ResultadoBoletimSerializer(resultado).data)


class BoletimSemanalViewSet(viewsets.ViewSet):
    """Leitura montada: blocos, indicadores, série do ano e destaque da semana."""
    permission_classes = [IsAuthenticated]

    def list(self, request):
        hoje = date.today()
        try:
            ano = int(request.query_params.get('ano') or hoje.isocalendar()[0])
        except ValueError:
            return Response({'detail': 'Ano inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        semana_param = request.query_params.get('semana')
        try:
            semana = int(semana_param) if semana_param else None
        except ValueError:
            semana = None
        if not semana:
            # Semana corrente quando é o ano corrente; senão, a última do ano.
            semana = hoje.isocalendar()[1] if hoje.isocalendar()[0] == ano else services.total_de_semanas(ano)

        indicadores = list(
            IndicadorBoletim.objects.filter(ativo=True)
            .select_related('ensaio')
            .prefetch_related('produtos', 'componentes__produtos', 'componentes__ensaio')
            .order_by('bloco', 'ordem', 'nome')
        )
        manuais = list(ResultadoBoletim.objects.filter(ano=ano))

        series = {}
        for indicador in indicadores:
            if indicador.pai_id:
                continue  # componente entra pelo pai
            serie = services.SerieIndicador(indicador, ano)
            serie.componentes = [
                services.SerieIndicador(c, ano) for c in indicador.componentes.all() if c.ativo
            ]
            serie.carregar(manuais)
            series[indicador.id] = serie

        blocos = []
        for indicador in indicadores:
            if indicador.pai_id:
                continue
            serie = series[indicador.id]
            if not blocos or blocos[-1]['bloco'] != indicador.bloco:
                blocos.append({'bloco': indicador.bloco, 'titulo': indicador.bloco_titulo, 'indicadores': []})
            blocos[-1]['indicadores'].append(self._indicador_payload(serie, semana))

        inicio, fim = services.intervalo_da_semana(ano, min(semana, services.total_de_semanas(ano)))
        return Response({
            'ano': ano,
            'semana': semana,
            'semana_inicio': inicio,
            'semana_fim': fim,
            'total_semanas': services.total_de_semanas(ano),
            'blocos': blocos,
        })

    @action(detail=False, methods=['get'])
    def analises(self, request):
        """
        As análises que formaram o número de uma célula.

        Endpoint separado, e não um campo do boletim, de propósito: a lista nominal
        multiplicada por 25 indicadores × 52 semanas viraria uma resposta de alguns
        MB para uma informação que só interessa quando alguém desconfia de uma
        célula específica.
        """
        try:
            indicador = IndicadorBoletim.objects.get(pk=request.query_params.get('indicador'))
        except (IndicadorBoletim.DoesNotExist, TypeError, ValueError):
            return Response({'detail': 'Indicador inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ano = int(request.query_params.get('ano'))
            semana = int(request.query_params.get('semana'))
        except (TypeError, ValueError):
            return Response({'detail': 'Informe ano e semana.'}, status=status.HTTP_400_BAD_REQUEST)

        # Num ponderado o pai não tem análise própria: o que existe são as dos
        # componentes, então a lista sai agrupada por componente.
        if indicador.agregacao == 'PONDERADO':
            grupos = [
                {'indicador': c.id, 'nome': c.nome, 'analises': services.analises_da_semana(c, ano, semana)}
                for c in indicador.componentes.filter(ativo=True).order_by('ordem', 'nome')
            ]
        else:
            grupos = [{
                'indicador': indicador.id, 'nome': indicador.nome,
                'analises': services.analises_da_semana(indicador, ano, semana),
            }]

        return Response({
            'indicador': indicador.id,
            'nome': indicador.nome,
            'unidade': indicador.unidade,
            'casas_decimais': indicador.casas_decimais,
            # De onde o número foi lido — responde "por que essa análise entrou?"
            'origem': {
                'ensaio': indicador.ensaio.descricao if indicador.ensaio else '',
                'ensaio_nome': indicador.ensaio_nome,
                'campo_especial': indicador.campo_especial,
                'peneira_malha': indicador.peneira_malha,
                'peneira_metrica': indicador.peneira_metrica,
                'material': indicador.material,
                'tipo_amostra': indicador.tipo_amostra,
                'tipo_amostragem': indicador.tipo_amostragem,
                'local_coleta': indicador.local_coleta,
                'finalidade': indicador.finalidade,
                'campo_data': indicador.campo_data,
            },
            'grupos': grupos,
        })

    @staticmethod
    def _indicador_payload(serie, semana):
        indicador = serie.indicador
        return {
            'id': indicador.id,
            'nome': indicador.nome,
            'unidade': indicador.unidade,
            'casas_decimais': indicador.casas_decimais,
            'tipo_limite': indicador.tipo_limite,
            'valor_limite': indicador.valor_limite,
            'agregacao': indicador.agregacao,
            'observacao': indicador.observacao,
            'semana': serie.celula(semana),
            # O ano inteiro, indexado pela semana — é o que alimenta o gráfico e o
            # espelho da planilha sem uma segunda requisição.
            'serie': [serie.celula(s) for s in range(1, serie.semanas + 1)],
            'componentes': [
                {
                    'id': c.indicador.id,
                    'nome': c.indicador.nome,
                    'semana': c.celula(semana),
                    'serie': [c.celula(s) for s in range(1, c.semanas + 1)],
                }
                for c in serie.componentes
            ],
        }
