"""
Confere, conserta e blinda a numeração das amostras ("cal 00.0440").

Existe porque o número era escolhido pelo navegador e nada no banco impedia
repetição — ver controleQualidade/amostra/numeracao.py para a história completa.
A partir de 08/2026 quem numera é o servidor (`AmostraViewSet.perform_create`),
mas isso só fecha a porta para o que vem DEPOIS: as duplicatas já gravadas
continuam lá e o índice único ainda precisa ser criado no MySQL de produção.

    python manage.py numeros_amostra                  # só lista o que está repetido
    python manage.py numeros_amostra --corrigir       # renumera as repetidas
    python manage.py numeros_amostra --criar-indice   # cria o UNIQUE no banco

Ordem obrigatória: `--corrigir` primeiro, `--criar-indice` depois — o índice não
nasce com duplicata na tabela.

⚠️ `--corrigir` não sabe de duplicata/reanálise: renumerar uma amostra que tem
derivadas ('calcario 00.0526' com uma '...0526.1') deixa a família com números de
troncos diferentes. O vínculo em si sobrevive, porque é a FK `amostra_origem` que
o guarda — mas o número deixa de contar a história. Confira as derivadas antes
(`Amostra.objects.filter(amostra_origem__isnull=False)`).

⚠️ `--corrigir` TROCA o número de amostras já cadastradas. Fica com o número
original a amostra **EM USO** — a que tem OS (ordem ou expressa) ou análise
vinculada, porque é a que já apareceu em laudo e etiqueta; no empate, a mais
antiga. As outras recebem o próximo sequencial livre. Ainda assim o papel pode
divergir do sistema, então o comando imprime o de-para e nada acontece sem a flag.

⚠️ O índice é criado por SQL, e não por migration, porque a VM não tem os arquivos
de migration do app `amostra` (`**/migrations/` está no .gitignore; ver
[[deploy_backend_armadilhas]]). `makemigrations` lá geraria um `0001_initial`
tentando recriar tabela. O `unique=True` do model e este comando dizem a mesma
coisa por caminhos diferentes.
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from controleQualidade.amostra.models import Amostra
from controleQualidade.amostra.numeracao import (
    formatar_numero,
    normalizar_prefixo,
    numeros_duplicados,
    prefixo_de,
    sequenciais_usados,
)

NOME_INDICE = 'amostra_amostra_numero_uniq'


class Command(BaseCommand):
    help = 'Lista/corrige números de amostra repetidos e cria o índice único.'

    def add_arguments(self, parser):
        parser.add_argument('--corrigir', action='store_true',
                            help='Renumera as repetidas (mantém a que tem OS/análise).')
        parser.add_argument('--criar-indice', action='store_true',
                            help='Cria o índice único de Amostra.numero no banco.')

    def handle(self, *args, **opcoes):
        duplicados = numeros_duplicados()
        self.mostrar(duplicados)

        if opcoes['corrigir'] and duplicados:
            duplicados = self.corrigir(duplicados)

        if opcoes['criar_indice']:
            if duplicados:
                self.stdout.write(self.style.ERROR(
                    'Índice NÃO criado: ainda há número repetido. Rode --corrigir primeiro.'))
                return
            self.criar_indice()

    # ------------------------------------------------------------------ listar
    def mostrar(self, duplicados):
        if not duplicados:
            self.stdout.write(self.style.SUCCESS('Nenhum número de amostra repetido.'))
            return

        total = sum(len(ids) for ids in duplicados.values())
        self.stdout.write(self.style.WARNING(
            f'{len(duplicados)} número(s) repetido(s), {total} amostra(s) envolvida(s):'))
        for numero, ids in sorted(duplicados.items()):
            amostras = (Amostra.objects
                        .filter(id__in=ids)
                        .values_list('id', 'numero', 'material', 'data_entrada', 'local_coleta')
                        .order_by('id'))
            self.stdout.write(f'  {numero}')
            for pk, numero_gravado, material, data_entrada, local in amostras:
                self.stdout.write(
                    f'    id {pk:>6}  {numero_gravado!r}  {material}  entrada {data_entrada}  {local or "-"}')

    # ----------------------------------------------------------------- corrigir
    def em_uso(self, ids):
        """Ids que já têm OS ou análise — são os que NÃO devem ser renumerados.

        O número dessas já circulou (etiqueta, laudo, boletim). Renumerar a órfã
        do par é o conserto mais barato para o laboratório.
        """
        # Import local: analise importa amostra, e o comando só roda sob demanda.
        from controleQualidade.analise.models import Analise

        com_analise = set(Analise.objects.filter(amostra_id__in=ids)
                          .values_list('amostra_id', flat=True))
        com_os = set(Amostra.objects
                     .filter(id__in=ids)
                     .exclude(ordem__isnull=True, expressa__isnull=True)
                     .values_list('id', flat=True))
        return com_analise | com_os

    def corrigir(self, duplicados):
        """Renumera as repetidas e devolve o que sobrou (deveria ser vazio)."""
        usados_por_prefixo = {}
        trocas = []

        for numero, ids in sorted(duplicados.items()):
            usadas = self.em_uso(ids)
            # Em uso primeiro; entre iguais, a mais antiga.
            ordenados = sorted(ids, key=lambda pk: (0 if pk in usadas else 1, pk))
            manter, renumerar = ordenados[0], ordenados[1:]
            motivo = 'tem OS/análise' if manter in usadas else 'é a mais antiga'
            self.stdout.write(f'{numero}: id {manter} fica com o número original ({motivo}).')

            for pk in renumerar:
                amostra = Amostra.objects.get(pk=pk)
                prefixo = prefixo_de(amostra.numero) or normalizar_prefixo(amostra.material)
                if not prefixo:
                    self.stdout.write(self.style.ERROR(
                        f'  id {pk}: sem prefixo nem material — corrija à mão.'))
                    continue

                usados = usados_por_prefixo.setdefault(prefixo, sequenciais_usados(prefixo))
                sequencial = (max(usados) if usados else 0) + 1
                usados.add(sequencial)
                trocas.append((pk, amostra.numero, formatar_numero(prefixo, sequencial)))

        if not trocas:
            return numeros_duplicados()

        with transaction.atomic():
            for pk, antigo, novo in trocas:
                # update() e não save(): não passa pelo serializer nem dispara sinal,
                # e é o único campo que muda.
                Amostra.objects.filter(pk=pk).update(numero=novo)
                self.stdout.write(f'  id {pk}: {antigo!r} → {novo!r}')

        self.stdout.write(self.style.SUCCESS(f'{len(trocas)} amostra(s) renumerada(s).'))
        self.stdout.write(self.style.WARNING(
            'Avise o laboratório: laudo ou etiqueta já impressos com os números antigos '
            'ficaram divergentes.'))
        return numeros_duplicados()

    # ------------------------------------------------------------------ índice
    def criar_indice(self):
        tabela = Amostra._meta.db_table
        with connection.cursor() as cursor:
            existentes = connection.introspection.get_constraints(cursor, tabela)
            for nome, definicao in existentes.items():
                if definicao.get('columns') == ['numero'] and definicao.get('unique'):
                    self.stdout.write(self.style.SUCCESS(
                        f'Índice único já existe em {tabela}.numero ({nome}).'))
                    return

            # CREATE UNIQUE INDEX serve tanto ao MySQL de produção quanto ao SQLite local
            # (o ALTER TABLE ... ADD UNIQUE do MySQL não existe no SQLite).
            cursor.execute(f'CREATE UNIQUE INDEX {NOME_INDICE} ON {tabela} (numero)')

        self.stdout.write(self.style.SUCCESS(
            f'Índice único {NOME_INDICE} criado em {tabela}.numero.'))
