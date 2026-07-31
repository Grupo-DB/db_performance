from rest_framework import serializers
from .models import Analise, AnaliseCalculo, AnaliseEnsaio
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.amostra.serializers import AmostraSerializer
from controleQualidade.amostra.models import Amostra


class AnaliseEnsaioSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnaliseEnsaio
        fields = '__all__'

class AnaliseCalculoSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnaliseCalculo
        fields = '__all__'


class AnaliseSerializer(serializers.ModelSerializer):
    amostra = serializers.PrimaryKeyRelatedField(queryset=Amostra.objects.all(), write_only=True)
    amostra_detalhes = AmostraSerializer(source='amostra', read_only=True)
    ensaios = AnaliseEnsaioSerializer(many=True, required=False, write_only=True)
    calculos = AnaliseCalculoSerializer(many=True, required=False, write_only=True)
    ensaios_detalhes = AnaliseEnsaioSerializer(source='ensaios', many=True, read_only=True)
    calculos_detalhes = AnaliseCalculoSerializer(source='calculos', many=True, read_only=True)
    ultimo_ensaio = serializers.SerializerMethodField(read_only=True)
    ultimo_calculo = serializers.SerializerMethodField(read_only=True) 
    class Meta:
        model = Analise
        fields = '__all__'

    # ------------------------------------------------------------------ caches
    # Estes dois métodos rodam por análise; na listagem (abertas/fechadas) isso
    # eram ~19 queries por análise, ~6.200 para as 320 fechadas, e um TTFB de ~5 s.
    # As caches abaixo vivem na instância do serializer, que o DRF cria uma vez por
    # request (com many=True o child é reaproveitado para todos os objetos) — não há
    # risco de dado velho entre requests.

    @property
    def _mapa_ensaios(self):
        """
        Todos os Ensaio por id, com as variáveis já carregadas.
        `get_ultimo_calculo` fazia `Ensaio.objects.get(id=...)` + `variavel.all()`
        dentro de dois loops aninhados — 300 das 771 queries de uma lista de 40
        análises. São ~70 ensaios cadastrados no total, então trazer todos de uma vez
        é mais barato que buscar um a um, e cabe em 2 queries.
        """
        if not hasattr(self, '_ensaios_por_id'):
            self._ensaios_por_id = {
                e.id: e for e in Ensaio.objects.prefetch_related('variavel').all()
            }
        return self._ensaios_por_id

    def _variaveis_do_ensaio(self, ensaio_id):
        """
        `(chaves_var, variaveis_utilizadas)` de um ensaio, calculado uma única vez.
        A forma não depende da análise nem do cálculo, então repetir por linha era
        trabalho puro. Devolve None quando o ensaio não existe.
        """
        if not hasattr(self, '_variaveis_por_ensaio'):
            self._variaveis_por_ensaio = {}
        if ensaio_id not in self._variaveis_por_ensaio:
            ensaio = self._mapa_ensaios.get(ensaio_id)
            if ensaio is None:
                self._variaveis_por_ensaio[ensaio_id] = None
            else:
                chaves = {}
                utilizadas = []
                for i, variavel in enumerate(ensaio.variavel.all()):
                    key = f'var{i+1:02d}' if i < 9 else f'var{i+1}'  # var01, var02, etc.
                    var_data = {
                        'valor': variavel.id,
                        'descricao': getattr(variavel, 'descricao', str(variavel))
                    }
                    chaves[key] = var_data
                    utilizadas.append({
                        'nome': getattr(variavel, 'descricao', str(variavel)),
                        'valor': variavel.id,
                        'tecnica': key
                    })
                self._variaveis_por_ensaio[ensaio_id] = (chaves, utilizadas)
        return self._variaveis_por_ensaio[ensaio_id]

    def get_ultimo_ensaio(self, obj):
        # `order_by('-id').first()` ignora o prefetch_related e refaz a query. Ordenar
        # em Python a lista já carregada é o mesmo resultado sem ida ao banco.
        ensaios = list(obj.ensaios.all())
        if not ensaios:
            return None
        ultimo = max(ensaios, key=lambda e: e.id)
        return AnaliseEnsaioSerializer(ultimo).data

    # def get_ultimo_calculo(self, obj):
    #     ultimo = obj.calculos.order_by('-id')
    #     if ultimo:
    #         return AnaliseCalculoSerializer(ultimo).data
    #     return None
    
    def get_ultimo_calculo(self, obj):
        # Mesma troca do get_ultimo_ensaio: a lista vem do prefetch e a ordenação é em
        # Python. `order_by('-id')` + `.exists()` custavam duas queries por análise.
        calculos = sorted(obj.calculos.all(), key=lambda c: c.id, reverse=True)
        if calculos:
            calculos_lista = []
            calculos_tipos_vistos = set()  # Para controlar quais tipos já foram adicionados

            for calculo in calculos:
                # Se já temos este tipo de cálculo, pula
                if calculo.calculos in calculos_tipos_vistos:
                    continue
                
                calculos_tipos_vistos.add(calculo.calculos)
                data = AnaliseCalculoSerializer(calculo).data
                
                # Busca as variáveis através dos ensaios utilizados (igual ao ultimo_ensaio)
                if calculo.ensaios_utilizados:
                    ensaios_com_variaveis = []
                    
                    for ensaio_data in calculo.ensaios_utilizados:
                        # Se ensaio_data é um dicionário, pega o id
                        if isinstance(ensaio_data, dict):
                            ensaio_id = ensaio_data.get('id') or ensaio_data.get('value')
                            # Copia todos os dados do ensaio original
                            ensaio_completo = ensaio_data.copy()
                        else:
                            ensaio_id = ensaio_data
                            ensaio_completo = {'id': ensaio_id}
                            
                        # Verifica se o ensaio_id é válido (não é temporário)
                        if ensaio_id and not str(ensaio_id).startswith('temp_'):
                            try:
                                ensaio_id = int(ensaio_id)  # Converte para int
                                variaveis = self._variaveis_do_ensaio(ensaio_id)
                                if variaveis is None:
                                    raise Ensaio.DoesNotExist

                                # Cada variável também vira campo individual (var01, var02...),
                                # como o ultimo_ensaio faz
                                chaves, variaveis_utilizadas = variaveis
                                ensaio_completo.update(chaves)
                                ensaio_completo['variaveis_utilizadas'] = variaveis_utilizadas
                                ensaios_com_variaveis.append(ensaio_completo)

                            except (Ensaio.DoesNotExist, ValueError, TypeError):
                                # Se o ensaio não existe ou ID inválido, adiciona sem variáveis
                                if isinstance(ensaio_data, dict):
                                    ensaios_com_variaveis.append(ensaio_data)
                        else:
                            # ID temporário ou inválido, adiciona sem variáveis
                            if isinstance(ensaio_data, dict):
                                ensaios_com_variaveis.append(ensaio_data)
                    
                    # Atualiza os ensaios_utilizados
                    data['ensaios_utilizados'] = ensaios_com_variaveis
                
                calculos_lista.append(data)
            
            return calculos_lista
        return []

    def update(self, instance, validated_data):
        ensaios_data = validated_data.pop('ensaios', [])
        calculos_data = validated_data.pop('calculos', [])
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if ensaios_data:
            instance.ensaios.all().delete()
            for ensaio in ensaios_data:
                AnaliseEnsaio.objects.create(
                    analise=instance,
                    ensaios_utilizados=ensaio.get('ensaios_utilizados', []),
                    responsavel=ensaio.get('responsavel'),
                    digitador=ensaio.get('digitador'),
                    ensaios=ensaio.get('ensaios'),
                )

        if calculos_data:
            instance.calculos.all().delete()
            for calc in calculos_data:
                AnaliseCalculo.objects.create(
                    analise=instance,
                    calculos=calc.get('calculos'),
                    resultados=calc.get('resultados'),
                    ensaios_utilizados=calc.get('ensaios_utilizados', []),
                    responsavel=calc.get('responsavel'),
                    digitador=calc.get('digitador'),
                    laboratorio=calc.get('laboratorio'),
                )

        return instance

