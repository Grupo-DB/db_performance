from django.db import models


class TipoEnsaio(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    class meta:
        verbose_name = 'Tipo de Ensaio'
        verbose_name_plural = 'Tipos de Ensaio'


class Variavel(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=255, null=False, blank=False)
    tecnica = models.CharField(max_length=255, null=True, blank=True)
    valor = models.FloatField(null=True, blank=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    class meta:
        verbose_name = 'Variável'
        verbose_name_plural = 'Variáveis'

class Ensaio(models.Model):
    id = models.AutoField(primary_key=True)
    descricao = models.CharField(max_length=500, null=False, blank=False)
    valor = models.FloatField(null=True, blank=True)
    tipo_ensaio = models.ForeignKey(TipoEnsaio, null=True, blank=True, on_delete=models.RESTRICT, related_name='ensaio')
    unidade = models.CharField(max_length=255, null=True, blank=True)
    tempo_previsto = models.CharField(max_length=255, null=True, blank=True)
    variavel = models.ManyToManyField(Variavel,related_name='ensaio')
    tecnica = models.CharField(max_length=255, null=True, blank=True)
    funcao = models.CharField(max_length=500, null=True, blank=True)
    norma = models.CharField(max_length=500, null=True, blank=True)
    garantia = models.CharField(max_length=500, null=True, blank=True)
    estado = models.CharField(max_length=255, null=True, blank=True)
    tempo_trabalho = models.CharField(max_length=255, null=True, blank=True)
    class meta:
        verbose_name = 'Ensaio'
        verbose_name_plural = 'Ensaios'



class PlanoPeneira(models.Model):
    """Plano de peneiramento: quais malhas o laboratório usa em cada ensaio.

    Os planos eram uma constante fixa no frontend
    (`controleQualidade/shared/planos-peneiras.ts`), então criar um plano novo
    exigia alterar código e publicar o front. Aqui viram cadastro.

    Mora no app `ensaio` — e não no `plano`, que seria o vizinho óbvio — porque
    o `plano` é um dos apps sem nenhum arquivo de migration na VM (as migrations
    estão no .gitignore do backend): um `makemigrations plano` geraria um
    `0001_initial` tentando recriar a tabela de PlanoAnalise, que já existe. O
    `ensaio` tem a cadeia íntegra (…0013), então esta entra como incremento.

    `peneiras` é a lista de malhas na MESMA grafia gravada em `Analise.peneiras`
    / `peneiras_umidas` ('# 30 - ABNT/ASTM 30 - 0,600 mm'). É por essa string que
    o valor da malha é encontrado, então o cadastro só oferece as opções do
    catálogo do front — texto livre aqui quebraria o casamento em silêncio.
    """

    SECAS = 'peneiras_secas'
    UMIDAS = 'peneiras_umidas'
    TIPOS = [
        (SECAS, 'Peneiras Secas'),
        (UMIDAS, 'Peneiras Úmidas'),
    ]

    id = models.AutoField(primary_key=True)
    descricao = models.CharField(max_length=200, null=False, blank=False)
    tipo = models.CharField(max_length=20, choices=TIPOS, default=SECAS)
    peneiras = models.JSONField(default=list, blank=True)
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Plano de Peneiras'
        verbose_name_plural = 'Planos de Peneiras'
        ordering = ['tipo', 'ordem', 'descricao']
        # O mesmo nome pode existir nas secas e nas úmidas ("Argamassa e Areias"
        # é plano dos dois lados), mas não duas vezes no mesmo peneiramento.
        unique_together = ('descricao', 'tipo')

    def __str__(self):
        return f'{self.descricao} ({self.get_tipo_display()})'


class CadastroSimples(models.Model):
    """Base dos cadastros de lista da amostra: só um nome, ligado ou desligado.

    Finalidade e Fornecedor eram arrays fixos dentro de `amostra.ts`, no
    frontend: acrescentar um fornecedor exigia alterar código e publicar. Aqui
    viram cadastro, com a tela de Amostras podendo criar pelo modal.

    Moram no app `ensaio` — e não no `amostra`, que seria o vizinho óbvio —
    porque o `amostra` é um dos apps sem nenhum arquivo de migration na VM (as
    migrations estão no .gitignore do backend): um `makemigrations amostra`
    geraria um `0001_initial` tentando recriar as tabelas que já existem. O
    `ensaio` tem a cadeia íntegra, então estas entram como incremento. O app
    virou, na prática, o lugar dos cadastros do laboratório.
    """

    nome = models.CharField(max_length=150, unique=True)
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True
        ordering = ['ordem', 'nome']

    def __str__(self):
        return self.nome


class Finalidade(CadastroSimples):
    """Para que a amostra entrou no laboratório (Controle de Qualidade, SAC...).

    O nome é gravado como TEXTO em `Amostra.finalidade`, e a tela de análise
    compara com 'SAC' para pedir o número do SAC. Renomear uma finalidade aqui
    não renomeia o que já foi gravado nas amostras antigas.
    """

    class Meta(CadastroSimples.Meta):
        abstract = False
        verbose_name = 'Finalidade'
        verbose_name_plural = 'Finalidades'


class Fornecedor(CadastroSimples):
    """Quem forneceu o material da amostra. Também gravado como texto na amostra."""

    class Meta(CadastroSimples.Meta):
        abstract = False
        verbose_name = 'Fornecedor'
        verbose_name_plural = 'Fornecedores'
