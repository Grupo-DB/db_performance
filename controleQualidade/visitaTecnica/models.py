from django.db import models


def upload_image_visita(instance, filename):
    return f"visita_tecnica_{instance.visita.id}/{filename}"


class VisitaTecnica(models.Model):
    """
    Relatório de visita técnica para atendimento externo — ensaio de resistência
    de aderência à tração em revestimento (substrato/superficial), NBR 13528-2.

    Reproduz o formulário que o laboratório mantinha em Excel
    ('calculo de aderencia geral.xlsx', aba 'NBR 13.528-2').

    Os campos que identificam ou filtram a visita são colunas de verdade; as
    seções do formulário (que são grupos de marcações e texto livre, e mudam a
    cada revisão do formulário) ficam em JSON, como já é feito nos ensaios de
    argamassa em `Analise`. Isso evita uma migration por ajuste de formulário.
    """

    id = models.AutoField(primary_key=True)
    codigo = models.CharField(max_length=50, unique=True)  # ex.: '2026.42'

    # ── 1 - Identificação ────────────────────────────────────────────────────
    cliente = models.CharField(max_length=255)
    nome_obra = models.CharField(max_length=255, null=True, blank=True)
    endereco_obra = models.CharField(max_length=500, null=True, blank=True)
    local_avaliado = models.CharField(max_length=255, null=True, blank=True)
    teste = models.CharField(max_length=255, null=True, blank=True)

    # ── Capa do relatório (página 1) ─────────────────────────────────────────
    data_visita = models.DateField(null=True, blank=True)
    acompanhantes_obra = models.CharField(max_length=500, null=True, blank=True)
    acompanhantes_db = models.CharField(max_length=500, null=True, blank=True)
    vendedor = models.CharField(max_length=255, null=True, blank=True)
    material_ensaiado = models.CharField(max_length=255, null=True, blank=True)
    data_aplicacao = models.DateField(null=True, blank=True)
    data_ensaio = models.DateField(null=True, blank=True)
    ambiente = models.CharField(max_length=50, null=True, blank=True)  # Interno / Externo

    # ── Seções do formulário ─────────────────────────────────────────────────
    # cabecalho: norma de referência, material ensaiado e local (as marcações do topo)
    cabecalho = models.JSONField(default=dict, blank=True)
    # sistema: 2 - Informações sobre o Sistema
    sistema = models.JSONField(default=dict, blank=True)
    # metodo: 3 - Informações sobre o Método de Ensaio
    metodo = models.JSONField(default=dict, blank=True)
    # condicoes: 3 - Informações sobre o Ensaio (horários, clima, executante)
    condicoes = models.JSONField(default=dict, blank=True)

    # ── 4 - Resultados ───────────────────────────────────────────────────────
    # Os ENSAIOS da visita. A obra faz várias baterias no mesmo dia — o relatório
    # 2025.160 (Construtora Schama) saiu com três, "ensaio E" e "ensaio G" ao
    # substrato e "ensaio F" superficial —, cada uma com seus 12 corpos de prova e
    # sua prancha de fotos. Antes cabia uma bateria por visita, e o técnico abria
    # uma visita por ensaio: o cliente recebia três relatórios do mesmo dia.
    #
    # Cada item: {rotulo, tipo, corpos, limite_ra, tipo_ruptura, resultados}.
    ensaios = models.JSONField(default=list, blank=True)
    # Lista dos corpos de prova (12 no formulário). Cada item traz diâmetro, área,
    # carga e a resistência já calculada, mais as 7 formas de ruptura em %.
    #
    # Repete o PRIMEIRO ensaio. Mantido porque o app mobile, o admin e as visitas
    # já gravadas leem daqui — visita de um ensaio só continua idêntica.
    corpos_prova = models.JSONField(default=list, blank=True)
    # media, desvio_padrao, maximo, minimo. Calculados no frontend
    # (core/utils/aderencia-externa.ts) e gravados aqui para o relatório reimprimir
    # exatamente o que foi emitido — a fórmula tem UMA implementação, no frontend.
    resultados = models.JSONField(default=dict, blank=True)
    tipo_ruptura = models.CharField(max_length=10, null=True, blank=True)

    # ── 5 - Considerações ────────────────────────────────────────────────────
    consideracoes = models.TextField(null=True, blank=True)
    observacoes = models.TextField(null=True, blank=True)

    laboratorio = models.CharField(max_length=255, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Visita Técnica'
        verbose_name_plural = 'Visitas Técnicas'
        ordering = ['-data_visita', '-id']

    def __str__(self):
        return f'{self.codigo} — {self.cliente}'


class VisitaTecnicaImagem(models.Model):
    """
    Foto do ensaio. `cp` diz a qual corpo de prova a foto pertence (1..12), o que
    permite montar a grade 'CP-1..CP-12' do relatório na ordem certa; fica nulo
    para fotos gerais da obra.

    FileField (e não ImageField) pelo mesmo motivo de `AmostraImagem`: o app
    mobile envia o arquivo direto da câmera e o Pillow não é dependência garantida
    no servidor.
    """

    id = models.AutoField(primary_key=True)
    visita = models.ForeignKey(VisitaTecnica, on_delete=models.CASCADE, related_name='imagens')
    image = models.FileField(upload_to=upload_image_visita, blank=False, null=False)
    cp = models.PositiveSmallIntegerField(null=True, blank=True)
    # A qual ensaio da visita a foto pertence (1 = o primeiro). Cada ensaio imprime
    # a própria prancha "Figura N — Ensaio X". Nulo é foto anterior ao suporte a
    # vários ensaios: pertence ao primeiro, que era o único que existia.
    ensaio = models.PositiveSmallIntegerField(null=True, blank=True)
    descricao = models.CharField(max_length=255, null=True, blank=True)
    data_upload = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Imagem da Visita Técnica'
        verbose_name_plural = 'Imagens da Visita Técnica'
        # Por ensaio e, dentro dele, na ordem da grade CP-1..CP-12. Foto sem CP vai
        # para o fim do seu ensaio.
        ordering = ['ensaio', 'cp', 'id']
