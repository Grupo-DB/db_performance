"""
Importa o histórico da planilha da UNIDB para o módulo.

    python manage.py importar_unidb --arquivo /caminho/Quadro_de_avaliacao_UNIDB.xlsx --dry-run
    python manage.py importar_unidb --arquivo /caminho/Quadro_de_avaliacao_UNIDB.xlsx
    python manage.py importar_unidb --arquivo ... --somente alunos,cursos

Abas lidas (cabeçalho na linha 8 da planilha, dados a partir da 9):

    CAD_FUNC              → Aluno
    CAD_CURSOS            → Curso + Turma
    CAD_MATRICULAS        → Matricula
    REG_TREINAMENTOS_NOVO → AvaliacaoTreinamento

É REPETÍVEL: aluno casa por matrícula, curso por nome, turma pelo código da planilha e
matrícula pelo par (turma, aluno). Rodar duas vezes atualiza, não duplica.
"""
import re
import unicodedata
from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from unidb.models import Aluno, AvaliacaoTreinamento, Curso, Matricula, Turma

# Linha do cabeçalho nas abas de cadastro (0-based, como o pandas conta).
LINHA_CABECALHO = 7


def texto(valor):
    """Célula → str limpa; NaN/None viram ''."""
    if valor is None:
        return ''
    s = str(valor).strip()
    if s.lower() in ('nan', 'nat', 'none'):
        return ''
    return s


def maiusculo_sem_acento(valor):
    """'Não' → 'NAO'. As escolhas do modelo são gravadas sem acento."""
    s = texto(valor).upper()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def numero(valor):
    """Célula → float, ou None. Aceita '9,5' (a planilha tem os dois formatos)."""
    s = texto(valor).replace('%', '')
    if not s:
        return None
    if ',' in s and '.' not in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def inteiro(valor):
    n = numero(valor)
    return int(n) if n is not None else None


def data_de(valor):
    """
    Timestamp/datetime/str → `date`, ou None.

    A ordem importa: `pandas.Timestamp` e `datetime` SÃO instâncias de `date`, então
    testar `isinstance(valor, date)` primeiro devolveria o datetime cru — e comparar
    datetime com date estoura (`can't compare datetime.datetime to datetime.date`).
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):          # cobre pandas.Timestamp
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = texto(valor)
    if not s:
        return None
    for formato in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(s[:10], formato).date()
        except ValueError:
            continue
    return None


def sim_nao(valor):
    """'SIM'/'NAO'/'NÃO' → bool. Vazio conta como False."""
    return maiusculo_sem_acento(valor).startswith('S')


def chave_treinamento(nome):
    """
    Normaliza o nome do treinamento para casar a ficha de avaliação com a turma.

    A aba REG_TREINAMENTOS_NOVO é preenchida à mão pelo participante, então o nome vem
    abreviado ("NR-12"), com grafia própria ("NR-6" x "NR-06") e com erro de digitação
    ("ESPAÇO CONFINAOD"). Aqui: sem acento, maiúsculo, NR com dois dígitos e só letras,
    números e espaço — o resto vira espaço.

    Não tenta corrigir erro de digitação: nome que não casa fica sem turma, com o texto
    preservado, em vez de ser pendurado na turma errada.
    """
    s = maiusculo_sem_acento(nome)
    s = re.sub(r'\bNR[\s\-]*0*(\d+)', lambda m: f'NR-{int(m.group(1)):02d}', s)
    s = re.sub(r'[^A-Z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def escolha(valor, validas):
    """
    Casa a resposta da planilha com as escolhas do modelo, sem acento e em maiúsculas.
    Resposta fora da lista volta None em vez de estourar — a planilha tem célula solta
    ("BOM " com espaço, e o que o usuário digitou à mão).
    """
    v = maiusculo_sem_acento(valor)
    return v if v in validas else None


class Command(BaseCommand):
    help = 'Importa alunos, cursos/turmas, matrículas e avaliações da planilha da UNIDB.'

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', required=True, help='Caminho do .xlsx')
        parser.add_argument('--dry-run', action='store_true', help='Só conta, não grava.')
        parser.add_argument('--somente', default='alunos,cursos,matriculas,avaliacoes',
                            help='Partes a importar, separadas por vírgula.')

    def handle(self, *args, **opcoes):
        try:
            import pandas as pd
        except ImportError as erro:  # pragma: no cover
            raise CommandError(f'pandas é necessário para ler a planilha: {erro}')

        caminho = opcoes['arquivo']
        simular = opcoes['dry_run']
        partes = {p.strip() for p in opcoes['somente'].split(',') if p.strip()}

        try:
            planilha = pd.ExcelFile(caminho)
        except FileNotFoundError:
            raise CommandError(f'Planilha não encontrada: {caminho}')

        # Tudo numa transação: importação pela metade deixaria matrícula apontando para
        # turma que não existe. Com --dry-run desfaz no fim.
        with transaction.atomic():
            resumo = {}
            if 'alunos' in partes:
                resumo['alunos'] = self._alunos(planilha)
            if 'cursos' in partes:
                resumo['cursos'] = self._cursos(planilha)
            if 'matriculas' in partes:
                resumo['matriculas'] = self._matriculas(planilha)
            if 'avaliacoes' in partes:
                resumo['avaliacoes'] = self._avaliacoes(planilha)

            self.stdout.write('')
            for parte, contas in resumo.items():
                detalhe = '  '.join(f'{chave}={valor}' for chave, valor in contas.items())
                self.stdout.write(f'{parte:12} {detalhe}')

            if simular:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING('\n--dry-run: nada foi gravado.'))
            else:
                self.stdout.write(self.style.SUCCESS('\nImportação concluída.'))

    # ── CAD_FUNC ──────────────────────────────────────────────────────────────
    def _alunos(self, planilha):
        df = planilha.parse('CAD_FUNC', header=None)
        criados = atualizados = ignorados = 0
        for _, linha in df.iloc[LINHA_CABECALHO + 1:].iterrows():
            matricula = texto(linha[1])
            nome = texto(linha[2])
            # Sem matrícula ou sem nome não é aluno: são as linhas de rodapé/fórmula.
            if not matricula or not nome:
                ignorados += 1
                continue
            campos = {
                'nome': nome,
                'cargo': texto(linha[3]) or None,
                'setor': texto(linha[4]) or None,
                'data_admissao': data_de(linha[5]),
                'data_matricula_unidb': data_de(linha[6]),
                'grupo_alvo': texto(linha[7]) or None,
                'origem': 'EXTERNO' if maiusculo_sem_acento(linha[8]).startswith('EXT') else 'INTERNO',
            }
            _, criado = Aluno.objects.update_or_create(matricula=matricula, defaults=campos)
            criados += 1 if criado else 0
            atualizados += 0 if criado else 1
        return {'criados': criados, 'atualizados': atualizados, 'linhas_ignoradas': ignorados}

    # ── CAD_CURSOS ────────────────────────────────────────────────────────────
    def _cursos(self, planilha):
        df = planilha.parse('CAD_CURSOS', header=None)
        cursos_criados = turmas_criadas = turmas_atualizadas = ignorados = 0
        for _, linha in df.iloc[LINHA_CABECALHO + 1:].iterrows():
            codigo = texto(linha[1])
            nome_curso = texto(linha[3])
            if not codigo or not nome_curso:
                ignorados += 1
                continue

            # O Curso guarda o que não muda de turma para turma. `update_or_create`
            # deixaria a última turma importada mandar no cadastro; aqui a primeira
            # ocorrência define e as seguintes só completam o que estiver vazio.
            curso, criado = Curso.objects.get_or_create(
                nome=nome_curso,
                defaults={
                    'area': texto(linha[2]) or None,
                    'tipo_treinamento': maiusculo_sem_acento(linha[7]) or None,
                    'tem_avaliacao': sim_nao(linha[9]),
                    'pre_requisito': texto(linha[10]) or None,
                    'publico_alvo': texto(linha[11]) or None,
                    'aberto_publico_interno': sim_nao(linha[12]),
                    'aberto_publico_externo': sim_nao(linha[13]),
                    'pontuacao': numero(linha[17]),
                    'periodicidade_meses': inteiro(linha[18]),
                    'alavanca_ni': numero(linha[19]),
                    'nota_minima': numero(linha[20]),
                    'peso_assiduidade': numero(linha[21]),
                    'peso_avaliacao_comportamental': numero(linha[22]),
                    'peso_avaliacao_tecnica': numero(linha[23]),
                    'validade_dias': inteiro(linha[24]),
                    'status': maiusculo_sem_acento(linha[27]) or 'ATIVO',
                },
            )
            cursos_criados += 1 if criado else 0

            campos_turma = {
                'curso': curso,
                'codigo_modulo': texto(linha[4]) or None,
                'modulo': texto(linha[5]) or None,
                'instrutor': texto(linha[6]) or None,
                'horas_aula': numero(linha[8]),
                'vagas': inteiro(linha[14]),
                'data_inicial': data_de(linha[15]),
                'data_final': data_de(linha[16]),
                'data_vencimento': data_de(linha[25]),
                'observacao': texto(linha[26]) or None,
                'status': maiusculo_sem_acento(linha[27]) or 'ATIVO',
                'carga': numero(linha[28]) if df.shape[1] > 28 else None,
            }
            _, criado = Turma.objects.update_or_create(codigo=codigo, defaults=campos_turma)
            turmas_criadas += 1 if criado else 0
            turmas_atualizadas += 0 if criado else 1
        return {'cursos_novos': cursos_criados, 'turmas_novas': turmas_criadas,
                'turmas_atualizadas': turmas_atualizadas, 'linhas_ignoradas': ignorados}

    # ── CAD_MATRICULAS ────────────────────────────────────────────────────────
    def _matriculas(self, planilha):
        df = planilha.parse('CAD_MATRICULAS', header=None)
        turmas = {t.codigo: t for t in Turma.objects.all() if t.codigo}
        alunos = {a.matricula: a for a in Aluno.objects.all()}

        criadas = existentes = sem_turma = alunos_criados = ignorados = 0
        novas = []
        for _, linha in df.iloc[LINHA_CABECALHO + 1:].iterrows():
            codigo_curso = texto(linha[2])
            codigo_aluno = texto(linha[6])
            nome_aluno = texto(linha[7])
            if not codigo_curso or not codigo_aluno:
                ignorados += 1
                continue

            turma = turmas.get(codigo_curso)
            if not turma:
                # Matrícula de turma que não está na CAD_CURSOS: não há onde pendurar.
                sem_turma += 1
                continue

            aluno = alunos.get(codigo_aluno)
            if not aluno:
                # Aluno que aparece só na matrícula (desligado antes do cadastro atual).
                # Criar preserva o histórico; descartar perderia a participação.
                aluno = Aluno.objects.create(
                    matricula=codigo_aluno,
                    nome=nome_aluno or f'Aluno {codigo_aluno}',
                    ativo=False,
                    observacoes='Criado pela importação da planilha (só aparecia em matrículas).',
                )
                alunos[codigo_aluno] = aluno
                alunos_criados += 1

            if Matricula.objects.filter(turma=turma, aluno=aluno).exists():
                existentes += 1
                continue
            novas.append(Matricula(
                turma=turma, aluno=aluno,
                data_matricula=data_de(linha[1]) or turma.data_inicial,
                # A planilha só guarda quem participou, então o histórico entra como
                # concluído — é o que o RH considera para validade e vencimento.
                situacao='CONCLUIDO',
                presente=True,
            ))
            criadas += 1

        # `ignore_conflicts` protege o par (turma, aluno) repetido na própria planilha,
        # que o filtro acima não pega porque as novas ainda não estão no banco.
        Matricula.objects.bulk_create(novas, batch_size=500, ignore_conflicts=True)
        return {'criadas': criadas, 'ja_existiam': existentes, 'sem_turma': sem_turma,
                'alunos_criados': alunos_criados, 'linhas_ignoradas': ignorados}

    # ── REG_TREINAMENTOS_NOVO ─────────────────────────────────────────────────
    def _avaliacoes(self, planilha):
        df = planilha.parse('REG_TREINAMENTOS_NOVO', header=None)
        qualidade = {v for v, _ in AvaliacaoTreinamento.ESCALA_QUALIDADE}
        sim = {v for v, _ in AvaliacaoTreinamento.ESCALA_SIM}
        tempo = {v for v, _ in AvaliacaoTreinamento.ESCALA_TEMPO}

        # Índice para casar a resposta com a turma: a aba só traz nome e data.
        turmas = list(Turma.objects.select_related('curso'))
        por_nome_data = {}
        por_nome = {}
        for t in turmas:
            chave_nome = chave_treinamento(t.curso.nome)
            por_nome.setdefault(chave_nome, []).append(t)
            if t.data_final:
                por_nome_data[(chave_nome, t.data_final)] = t
            if t.data_inicial:
                por_nome_data.setdefault((chave_nome, t.data_inicial), t)

        criadas = com_turma = sem_turma = ignorados = 0
        novas = []
        for _, linha in df.iloc[LINHA_CABECALHO + 1:].iterrows():
            nome = texto(linha[2])
            conclusao = data_de(linha[1])
            geral = escolha(linha[4], qualidade)
            # Linha sem treinamento e sem nenhuma resposta é sobra de fórmula da aba.
            if not nome and not geral:
                ignorados += 1
                continue

            chave = chave_treinamento(nome)
            turma = por_nome_data.get((chave, conclusao))
            if not turma:
                candidatas = list(por_nome.get(chave) or [])
                if not candidatas and chave:
                    # O participante escreve o apelido do treinamento ("NR-12" para
                    # "NR-12 SEGURANÇA EM MÁQUINAS E EQUIPAMENTOS"): vale quando um nome
                    # está contido no outro. Exige 4+ caracteres para "NR" ou uma letra
                    # solta não casar com meia base.
                    if len(chave) >= 4:
                        for chave_curso, turmas_curso in por_nome.items():
                            if chave in chave_curso or chave_curso in chave:
                                candidatas.extend(turmas_curso)
                # Sem data exata, fica a turma mais próxima ANTES da conclusão: a ficha
                # é respondida no fim do treinamento.
                if conclusao:
                    anteriores = [t for t in candidatas if t.data_inicial and t.data_inicial <= conclusao]
                    turma = max(anteriores, key=lambda t: t.data_inicial) if anteriores else None
                if not turma and len(candidatas) == 1:
                    turma = candidatas[0]

            novas.append(AvaliacaoTreinamento(
                turma=turma,
                nome_treinamento=nome or None,
                instrutor=texto(linha[3]) or None,
                data_conclusao=conclusao,
                avaliacao_geral=geral,
                conteudo_atendeu=escolha(linha[5], sim),
                didatica_instrutor=escolha(linha[6], qualidade),
                material_apoio=escolha(linha[7], sim),
                tempo_duracao=escolha(linha[8], tempo),
                pontos_positivos=texto(linha[9]) or None,
                pontos_melhoria=texto(linha[10]) or None,
                importada_da_planilha=True,
            ))
            criadas += 1
            com_turma += 1 if turma else 0
            sem_turma += 0 if turma else 1

        # Sem chave natural (a ficha é anônima e pode repetir resposta idêntica): para
        # não duplicar numa segunda rodada, a aba é reimportada do zero. Apaga SÓ o que
        # veio da planilha — resposta digitada na tela pelo RH não é da importação.
        AvaliacaoTreinamento.objects.filter(importada_da_planilha=True).delete()
        AvaliacaoTreinamento.objects.bulk_create(novas, batch_size=500)
        return {'criadas': criadas, 'casadas_com_turma': com_turma,
                'sem_turma': sem_turma, 'linhas_ignoradas': ignorados}
