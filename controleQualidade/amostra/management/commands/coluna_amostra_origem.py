"""Cria a coluna `amostra_origem_id` de Amostra direto no banco.

Existe porque a VM de produção NÃO tem os arquivos de migration do app `amostra`
(ver a memória deploy_backend_armadilhas): lá `migrate amostra` não aplica a
0029_amostra_amostra_origem, e copiar só ela dá NodeNotFoundError. Foi o mesmo
impasse do índice único do `numero`, resolvido do mesmo jeito — por comando.

    python manage.py coluna_amostra_origem            # diz o que falta
    python manage.py coluna_amostra_origem --criar    # cria a coluna e a FK

É idempotente: rodar de novo com a coluna já criada não faz nada e não falha.

Depois de criado na mão, registre a migration como aplicada para o grafo não
tentar criá-la outra vez:

    python manage.py migrate amostra 0029 --fake
"""
from django.core.management.base import BaseCommand
from django.db import connection

COLUNA = 'amostra_origem_id'
NOME_FK = 'amostra_amostra_origem_fk'


class Command(BaseCommand):
    help = 'Cria a coluna amostra_origem_id (duplicata/reanálise) sem depender de migration.'

    def add_arguments(self, parser):
        parser.add_argument('--criar', action='store_true',
                            help='Aplica o ALTER TABLE. Sem isto, apenas informa o estado.')

    def handle(self, *args, **opcoes):
        from controleQualidade.amostra.models import Amostra

        tabela = Amostra._meta.db_table
        with connection.cursor() as cursor:
            colunas = [c.name for c in connection.introspection.get_table_description(cursor, tabela)]

            if COLUNA in colunas:
                self.stdout.write(self.style.SUCCESS(f'{tabela}.{COLUNA} já existe — nada a fazer.'))
                return

            if not opcoes['criar']:
                self.stdout.write(self.style.WARNING(
                    f'{tabela}.{COLUNA} NÃO existe. Rode com --criar para criá-la.'))
                return

            # Nulo e sem default: amostra que já existe não é duplicata de ninguém.
            cursor.execute(f'ALTER TABLE {tabela} ADD COLUMN {COLUNA} integer NULL')
            self.stdout.write(self.style.SUCCESS(f'Coluna {COLUNA} criada.'))

            # A FK é o que garante que apagar a original deixe a derivada órfã em vez
            # de apontar para um id que sumiu. O SQLite local não aceita ADD CONSTRAINT
            # por ALTER — lá a coluna sozinha basta para os testes.
            if connection.vendor != 'mysql':
                self.stdout.write(f'Banco {connection.vendor}: FK não criada (só MySQL).')
                return

            cursor.execute(
                f'ALTER TABLE {tabela} ADD CONSTRAINT {NOME_FK} '
                f'FOREIGN KEY ({COLUNA}) REFERENCES {tabela} (id) ON DELETE SET NULL'
            )
            cursor.execute(f'CREATE INDEX {NOME_FK}_idx ON {tabela} ({COLUNA})')
            self.stdout.write(self.style.SUCCESS(f'FK {NOME_FK} e índice criados.'))
