from django.core.management.base import BaseCommand
from comissoes.models import ParametroComissao

PARAMETROS_DEFAULT = [
    # chave, descricao, taxa
    # ── Construção Civil — Externos CC ──────────────────────────────────────
    ('EXTERNO_CC_CB',       'Taxa base externos CC — grupo CB/Cal Crem',      0.019000),
    ('EXTERNO_CC_PRIMOR',   'Taxa base externos CC — grupo PRIMOR',           0.005000),
    ('EXTERNO_CC_PRIMEX',   'Taxa base externos CC — grupo PRIMEX',           0.007000),
    ('EXTERNO_CC_FINALIZA', 'Taxa base externos CC — grupo FINALIZA',         0.014000),
    # ── Construção Civil — Internos CC ──────────────────────────────────────
    ('INTERNO_CC_CB',       'Taxa base internos CC — grupo CB',               0.002000),
    ('INTERNO_CC_PRIMOR',   'Taxa base internos CC — grupo PRIMOR',           0.002000),
    ('INTERNO_CC_PRIMEX',   'Taxa base internos CC — grupo PRIMEX',           0.002000),
    ('INTERNO_CC_FINALIZA', 'Taxa base internos CC — grupo FINALIZA',         0.002000),
    # ── Potencializadores ───────────────────────────────────────────────────
    ('BONUS_EXTERNO_CC',    'Bônus potencializador externos CC por grupo',    0.001000),
    ('BONUS_INTERNO_CC',    'Bônus potencializador internos CC por grupo',    0.000500),
    # ── Bônus de meta GLOBAL CC (empresa toda, dividido entre os vendedores elegíveis) ──
    ('BONUS_GLOBAL_CC_CB',       'Bônus meta global CC — grupo CB',           0.001000),
    ('BONUS_GLOBAL_CC_PRIMOR',   'Bônus meta global CC — grupo PRIMOR',       0.001000),
    ('BONUS_GLOBAL_CC_PRIMEX',   'Bônus meta global CC — grupo PRIMEX',       0.001000),
    ('BONUS_GLOBAL_CC_FINALIZA', 'Bônus meta global CC — grupo FINALIZA',     0.001000),
    # ── Auxiliar / Especiais CC ─────────────────────────────────────────────
    ('JOCELAINE_BASE',      'Taxa auxiliar Jocelaine sobre base de vendas',   0.000100),
    ('MARCO_ALAN_PCT_PRIMEX','% do total PRIMEX para Marco Alan Lopes',       0.100000),
    # ── Adriano Born (escalonado por % da meta) ──────────────────────────────
    ('ADRIANO_TAXA_0_49',   'Taxa Adriano Born 0-49% da meta',                0.020000),
    ('ADRIANO_TAXA_50_99',  'Taxa Adriano Born 50-99% da meta',               0.030000),
    ('ADRIANO_TAXA_100_119','Taxa Adriano Born 100-119% da meta',             0.040000),
    ('ADRIANO_TAXA_120_MAIS','Taxa Adriano Born ≥120% da meta',               0.050000),
    # ── Agner ───────────────────────────────────────────────────────────────
    ('AGNER_MULTIPLICADOR', 'Multiplicador final comissão Agner (ex: 1.05)',  1.050000),
    ('AGNER_CARBOMAX_TAXA', 'Taxa adicional Agner grupo CARBOMAX',            0.008000),
    # ── Marina Gabrielly ────────────────────────────────────────────────────
    ('MARINA_QUERO_QUERO',  'Taxa Marina sobre vendas QueroQuero',            0.001000),
    ('MARINA_MPA',          'Taxa Marina sobre base MPA (reps MPA)',          0.000300),
    # ── ATM Internos ────────────────────────────────────────────────────────
    ('ATM_INTERNO_REPS',    'Taxa internos ATM sobre reps vinculados (0,25%)',0.002500),
    ('ATM_CAL_SUCRO',       'Taxa Cal Sucro para Mariane ATM (0,125%)',       0.001250),
    ('ATM_KRICAL',          'Taxa KRICAL para Mariane ATM (0,25%)',           0.002500),
    ('ATM_DOLOMITA',        'Taxa dolomita para Alexandra/Mariane ATM (0,5%)',0.005000),
    ('CC_DOLOMITA',         'Taxa adicional dolomita p/ os 12 vendedores externos CC (0,8%)', 0.008000),
    ('ATM_DIRETO',          'Taxa ATM direto para Alexandra/Mariane (0,5%)',  0.005000),
    ('DARCILEI_ATM',        'Taxa Darcilei sobre total ATM sem COFCO (0,04%)',0.000400),
    # ── Marco Antônio Correa ────────────────────────────────────────────────
    ('MARCO_CORREA_SC_TAXA',  'Taxa SC Marco Correa quando acima da meta',    0.005000),
    ('MARCO_CORREA_SC_META',  'Meta vendas SC para taxa variável (600k)',   600000.000000),
    ('MARCO_CORREA_SC_MINIMO','Comissão mínima SC Marco Correa (abaixo meta)',3000.000000),
    ('MARCO_CORREA_RS_TAXA',  'Taxa RS Marco Correa (0,05%)',                 0.000500),
    ('MARCO_CORREA_FIXO',     'Salário fixo mensal Marco Correa',          12500.000000),
    # ── Agronegócio — Felinto ───────────────────────────────────────────────
    ('FELINTO_AGRO_GERAL',  'Taxa Felinto agro não-óxido (0,1%)',             0.001000),
    ('FELINTO_AGRO_OXIDO',  'Taxa Felinto agro-óxido (1%)',                   0.010000),
    # ── Agronegócio — Ildomar / Everton ────────────────────────────────────
    ('AGRO_TAXA_VENDEDOR',  'Taxa por território Ildomar/Everton (0,7%)',     0.007000),
    ('AGRO_TAXA_BASE',      'Taxa base agro residual sobre total (0,1%)',     0.001000),
    ('AGRO_FIXO_REP',       'Salário fixo reps externos agro (Ildomar/Everton)', 8225.000000),
    # ── Agronegócio — Vergilino ─────────────────────────────────────────────
    ('VERGILINO_TAXA',      'Taxa variável Vergilino agro (0,15%)',           0.001500),
    ('VERGILINO_FIXO',      'Salário fixo Vergilino',                         6365.920000),
]


class Command(BaseCommand):
    help = 'Popula os parâmetros de comissão com os valores padrão (não sobrescreve existentes)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Sobrescreve os valores mesmo que já existam',
        )

    def handle(self, *args, **options):
        force = options['force']
        criados = 0
        atualizados = 0
        ignorados = 0

        for chave, descricao, taxa in PARAMETROS_DEFAULT:
            obj, created = ParametroComissao.objects.get_or_create(
                chave=chave,
                defaults={'descricao': descricao, 'taxa': taxa, 'ativo': True}
            )
            if created:
                criados += 1
            elif force:
                obj.descricao = descricao
                obj.taxa = taxa
                obj.save()
                atualizados += 1
            else:
                ignorados += 1

        self.stdout.write(self.style.SUCCESS(
            f'Concluído: {criados} criados, {atualizados} atualizados, {ignorados} ignorados.'
        ))
