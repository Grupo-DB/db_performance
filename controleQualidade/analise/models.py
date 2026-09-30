from django.db import models
from controleQualidade.amostra.models import Amostra
from controleQualidade.ensaio.models import Ensaio

class Analise(models.Model):
    id = models.AutoField(primary_key=True)
    data = models.DateTimeField(auto_created=True, auto_now=True, null=False, blank=False)
    amostra = models.ForeignKey(Amostra, null=True, blank=True, on_delete=models.RESTRICT, related_name='analise')
    estado = models.CharField(max_length=255, null=False, blank=False)
    finalizada = models.BooleanField(default=False, blank=True)
    finalizada_at = models.DateField(null=True, blank=True)  
    laudo = models.BooleanField(default=False, blank=True)  
    aprovada = models.BooleanField(default=False, blank=True)  
    aprovada_at = models.DateField(null=True)
    metodo_modelagem = models.CharField(max_length=255, null=True, blank=True)
    metodo_muro = models.CharField(max_length=255, null=True, blank=True)
    observacoes_muro = models.TextField(null=True, blank=True)
    material_organico = models.TextField(null=True, blank=True)
    parecer = models.JSONField(null=True, blank=True)
    substrato = models.JSONField(null=True, blank=True)
    superficial = models.JSONField(null=True, blank=True)
    retracao = models.JSONField(null=True, blank=True)
    elasticidade = models.JSONField(null=True, blank=True)
    flexao = models.JSONField(null=True, blank=True)
    compressao = models.JSONField(null=True, blank=True)
    peneiras = models.JSONField(null=True, blank=True)
    peneiras_umidas = models.JSONField(null=True, blank=True)
    laboratorio_atual = models.CharField(max_length=255, null=True, blank=True)
    # Fonte única da data de moldagem dos corpos de prova.
    #
    # Antes ela existia em três lugares que se desencontravam: `flexao.moldagem`,
    # `compressao.moldagem` e, implicitamente, o L0/M0 da variação (que é a
    # LEITURA inicial, dias depois da moldagem). O laudo lia um deles e saía com
    # data diferente da que o laboratório aplicou na tela.
    #
    # Nula em análise antiga, e é por isso que o front mantém a dedução por
    # `L0 - 3` como segunda opção.
    data_moldagem = models.DateField(null=True, blank=True)
    # Data de cura = moldagem + 28 dias, só para Argamassa, Finaliza e Areia (que não têm
    # data de descarte — decisão do laboratório, 30/09/2026). Gravada pelo `save()` a
    # partir da moldagem: não é editada à mão, então nunca fica diferente dela.
    data_cura = models.DateField(null=True, blank=True)
    variacao_dimensional = models.JSONField(null=True, blank=True)
    variacao_massa = models.JSONField(null=True, blank=True)
    tracao_normal = models.JSONField(null=True, blank=True)
    tracao_submersa = models.JSONField(null=True, blank=True)
    tracao_estufa = models.JSONField(null=True, blank=True)
    tracao_tempo_aberto = models.JSONField(null=True, blank=True)
    modulo_elasticidade = models.JSONField(null=True, blank=True)
    deslizamento = models.JSONField(null=True, blank=True)
    massa_especifica = models.JSONField(null=True, blank=True)
    retencao_agua = models.JSONField(null=True, blank=True)
    classificacao = models.CharField(max_length=255, null=True, blank=True)
    capilaridade = models.JSONField(null=True, blank=True)
    cal_completo = models.JSONField(null=True, blank=True)
    usada_laudo = models.BooleanField(default=False, blank=True)
    excluded_ensaios = models.JSONField(null=True, blank=True, default=list)
    excluded_calculos = models.JSONField(null=True, blank=True, default=list)

    class Meta:
        verbose_name = 'Análise'
        verbose_name_plural = 'Análises'

    def save(self, *args, **kwargs):
        self.data_cura = calcular_data_cura(self)
        # Quem salva só alguns campos (update_fields) também leva a data de cura junto.
        campos = kwargs.get('update_fields')
        if campos is not None and 'data_cura' not in campos:
            kwargs['update_fields'] = list(campos) + ['data_cura']
        super().save(*args, **kwargs)


# Materiais sem data de descarte: a data que vale para eles é a de cura.
MATERIAIS_SEM_DESCARTE = {'argamassa', 'finaliza', 'areia'}
DIAS_CURA = 28


def _normalizar(texto):
    import unicodedata
    texto = unicodedata.normalize('NFD', str(texto or ''))
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn').lower().strip()


def _data(valor):
    """DateField, 'AAAA-MM-DD' ou ISO com hora (o que vem dos JSONs de ensaio)."""
    import datetime as dt
    if not valor:
        return None
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    try:
        return dt.date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def calcular_data_cura(analise):
    """Moldagem + 28 dias para os materiais sem descarte; None para os demais.

    A moldagem sai de `data_moldagem` e, em análise anterior a ele, da moldagem da
    flexão ou da compressão — a mesma ordem do front (shared/cura.ts). O L0 − 3 fica de
    fora: a regra dos 3 dias já falhou em análise real."""
    import datetime as dt
    material = getattr(analise.amostra, 'material', None) if analise.amostra_id else None
    if _normalizar(material) not in MATERIAIS_SEM_DESCARTE:
        return None
    moldagem = (_data(analise.data_moldagem)
                or _data(((analise.flexao or {}).get('moldagem') or {}).get('data'))
                or _data(((analise.compressao or {}).get('moldagem') or {}).get('data')))
    return moldagem + dt.timedelta(days=DIAS_CURA) if moldagem else None

class AnaliseEnsaio(models.Model):
    id = models.AutoField(primary_key=True)
    analise = models.ForeignKey(Analise, null=True, blank=True, on_delete=models.RESTRICT, related_name='ensaios')
    ensaios = models.ForeignKey(Ensaio, null=True, blank=True, on_delete=models.RESTRICT, related_name='analise_ensaios')
    ensaios_utilizados = models.JSONField(null=True, blank=True) 
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    digitador = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Análise de Ensaio'
        verbose_name_plural = 'Análises de Ensaio'

class AnaliseCalculo(models.Model):
    id = models.AutoField(primary_key=True)
    analise = models.ForeignKey(Analise, null=True, blank=True, on_delete=models.RESTRICT, related_name='calculos')
    calculos = models.CharField(max_length=255, null=False, blank=False)
    resultados = models.FloatField(null=True, blank=True)
    ensaios_utilizados = models.JSONField(null=True, blank=True)
    responsavel = models.CharField(max_length=255, null=True, blank=True)
    digitador = models.CharField(max_length=255, null=True, blank=True)
    laboratorio = models.CharField(max_length=255, null=True, blank=True)
    class Meta:
        verbose_name = 'Análise de Cálculo'
        verbose_name_plural = 'Análises de Cálculo' 
