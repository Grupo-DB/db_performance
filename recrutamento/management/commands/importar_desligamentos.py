"""
Importa as respostas antigas dos dois Google Forms de desligamento (CSV exportado pelo Forms):

    manage.py importar_desligamentos --gestor "Formulário de Justificativa ... - Gestor.csv" \\
        --funcionario "Formulário de Entrevista ... - Funcionário.csv" [--dry-run] [--classificar]

- Liga cada resposta ao cadastro de colaboradores pelo nome (desligamento.casar_colaborador);
  sem casamento, o desligamento fica com o nome digitado.
- Justificativa do gestor e entrevista do funcionário do MESMO colaborador, com datas a até
  60 dias uma da outra, viram um desligamento só (datas mais distantes ficam separadas e são
  listadas no fim, para o RH conferir — houve um 2023 que parece ser 2025).
- Setor e cargo: os do cadastro quando casou (padronizados); o digitado no Forms vai para a
  observação, para nada se perder.
- Idempotente: cada linha tem `id_legado` = formulário + carimbo de data/hora do Forms.
- --classificar: roda a IA nas respostas abertas (alguns segundos por formulário).
"""
import csv
import re
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from avaliacoes.management.models import Colaborador
from recrutamento import desligamento as dsl
from recrutamento.models import Desligamento, FormularioDesligamento

# Colunas fixas de cada CSV (antes das perguntas, que vêm na ordem de dsl.PERGUNTAS).
COLUNAS = {
    'GESTOR': {'carimbo': 0, 'nome': 1, 'cargo': 2, 'setor': 3, 'gestor': 4, 'data': 5, 'tipo': 6, 'perguntas': 7},
    'FUNCIONARIO': {'carimbo': 0, 'nome': 1, 'cargo': 2, 'setor': 3, 'tempo': 4, 'data': 5, 'tipo': 6,
                    'perguntas': 7},
}
TIPOS = {
    'iniciativa da empresa': 'INVOLUNTARIO', 'involuntario': 'INVOLUNTARIO',
    'pedido do colaborador': 'VOLUNTARIO', 'voluntario': 'VOLUNTARIO',
    'acordo mutuo': 'ACORDO',
}
JANELA_DIAS = 60


def _carimbo(texto: str):
    """Data do carimbo do Forms, "2025/05/16 2:12:39 PM GMT-3". Sem strptime("%p"): AM/PM
    depende do locale, e com o sistema em português a leitura falharia calada."""
    m = re.match(r'\s*(\d{4})/(\d{1,2})/(\d{1,2})', texto or '')
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


class Command(BaseCommand):
    help = 'Importa as respostas antigas dos Google Forms de desligamento (gestor e funcionário).'

    def add_arguments(self, parser):
        parser.add_argument('--gestor', help='CSV da Justificativa de Desligamento (Gestor)')
        parser.add_argument('--funcionario', help='CSV da Entrevista de Desligamento (Funcionário)')
        parser.add_argument('--dry-run', action='store_true', help='Mostra o que faria, sem gravar.')
        parser.add_argument('--classificar', action='store_true', help='Classifica as respostas abertas pela IA.')

    def handle(self, *args, **op):
        if not op['gestor'] and not op['funcionario']:
            raise CommandError('Informe --gestor e/ou --funcionario.')
        self.colaboradores = list(Colaborador.objects.select_related('setor', 'cargo'))
        self.resumo = {'criados': 0, 'existentes': 0, 'pareados': 0, 'sem_cadastro': [], 'datas_distantes': []}
        with transaction.atomic():
            # Gestor primeiro: o tipo do desligamento é o que a empresa registrou.
            for formulario, caminho in (('GESTOR', op['gestor']), ('FUNCIONARIO', op['funcionario'])):
                if caminho:
                    for linha in self._ler(caminho, formulario):
                        self._importar(formulario, linha)
            if op['dry_run']:
                transaction.set_rollback(True)
        r = self.resumo
        self.stdout.write(f"Formulários criados: {r['criados']} | já existiam: {r['existentes']} | "
                          f"gestor+funcionário juntos: {r['pareados']}")
        if r['sem_cadastro']:
            self.stdout.write('Sem colaborador no cadastro (ficam com o nome digitado): ' + ', '.join(r['sem_cadastro']))
        for d in r['datas_distantes']:
            self.stdout.write(f'Conferir: {d}')
        if op['dry_run']:
            self.stdout.write(self.style.WARNING('--dry-run: nada foi gravado.'))
        elif op['classificar']:
            self._classificar()

    def _ler(self, caminho, formulario):
        with open(caminho, encoding='utf-8-sig', newline='') as f:
            linhas = list(csv.reader(f))
        esperadas = COLUNAS[formulario]['perguntas'] + len(dsl.PERGUNTAS[formulario])
        if len(linhas[0]) != esperadas:
            raise CommandError(f'{caminho}: {len(linhas[0])} colunas, esperado {esperadas} — o formulário mudou?')
        return linhas[1:]

    def _importar(self, formulario, linha):
        col = COLUNAS[formulario]
        id_legado = f'{formulario}|{linha[col["carimbo"]].strip()}'
        if FormularioDesligamento.objects.filter(id_legado=id_legado).exists():
            self.resumo['existentes'] += 1
            return
        nome = ' '.join(linha[col['nome']].split())
        data = date.fromisoformat(linha[col['data']].strip())
        colaborador, _ = dsl.casar_colaborador(nome, self.colaboradores)
        if not colaborador:
            self.resumo['sem_cadastro'].append(nome)

        desligamento = None
        if colaborador:
            candidatos = Desligamento.objects.filter(colaborador=colaborador)
            perto = [d for d in candidatos if abs((d.data_desligamento - data).days) <= JANELA_DIAS]
            if perto:
                desligamento = perto[0]
                self.resumo['pareados'] += 1
            elif candidatos:
                self.resumo['datas_distantes'].append(
                    f'{nome}: {formulario.lower()} diz {data:%d/%m/%Y}, outro formulário diz '
                    f'{candidatos[0].data_desligamento:%d/%m/%Y} — ficaram como desligamentos separados.')

        tipo = TIPOS.get(dsl.normalizar(linha[col['tipo']]), '')
        digitado = f'Google Forms ({formulario.lower()}): cargo "{linha[col["cargo"]].strip()}", ' \
                   f'setor "{linha[col["setor"]].strip()}".'
        if not desligamento:
            desligamento = Desligamento.objects.create(
                colaborador=colaborador,
                nome=colaborador.nome if colaborador else nome.upper(),
                cargo=(colaborador.cargo.nome if colaborador and colaborador.cargo_id else linha[col['cargo']].strip())[:120],
                setor=(colaborador.setor.nome if colaborador and colaborador.setor_id else linha[col['setor']].strip())[:120],
                data_admissao=colaborador.data_admissao.date() if colaborador and colaborador.data_admissao else None,
                data_desligamento=data,
                tipo=tipo,
                observacao=digitado,
            )
        else:
            desligamento.observacao = (desligamento.observacao + '\n' + digitado).strip()
            if formulario == 'GESTOR' or not desligamento.tipo:
                desligamento.tipo = tipo or desligamento.tipo
        if formulario == 'GESTOR':
            gestor_nome = ' '.join(linha[col['gestor']].split())
            gestor, _ = dsl.casar_colaborador(gestor_nome, self.colaboradores)
            desligamento.gestor = gestor
            desligamento.gestor_nome = gestor.nome if gestor else gestor_nome
        else:
            desligamento.tempo_casa_texto = linha[col['tempo']].strip()[:80]
        desligamento.save()

        respostas = {}
        for i, pergunta in enumerate(dsl.PERGUNTAS[formulario]):
            valor = linha[col['perguntas'] + i].strip()
            if pergunta['tipo'] == 'multipla':
                respostas[pergunta['chave']] = dsl.separar_multipla(valor, pergunta['opcoes'])
            elif not dsl.resposta_vazia(valor):
                respostas[pergunta['chave']] = valor
        FormularioDesligamento.objects.create(
            desligamento=desligamento, formulario=formulario, tipo_informado=tipo, respostas=respostas,
            data_preenchimento=_carimbo(linha[col['carimbo']]) or data, origem='GOOGLE_FORMS', id_legado=id_legado,
        )
        self.resumo['criados'] += 1

    def _classificar(self):
        from recrutamento.views import aplicar_classificacao
        pendentes = list(FormularioDesligamento.objects.filter(classificado_em__isnull=True, classificacao_revisada=False))
        self.stdout.write(f'Classificando {len(pendentes)} formulário(s) pela IA…')
        ok = 0
        for i, f in enumerate(pendentes, 1):
            ok += aplicar_classificacao(f)
            if i % 10 == 0:
                self.stdout.write(f'  {i}/{len(pendentes)}')
        # Segunda passada nas que falharam: o Foundry às vezes devolve 408 (tempo esgotado).
        falharam = [f for f in pendentes if f.erro_classificacao]
        if falharam:
            self.stdout.write(f'Tentando de novo {len(falharam)} que falharam…')
            ok += sum(aplicar_classificacao(f) for f in falharam)
        self.stdout.write(f'Classificados: {ok} | com erro: {len(pendentes) - ok}')
