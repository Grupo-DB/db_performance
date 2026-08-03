"""
Importa a planilha "Gestão DB | RH V.2.0" (.xlsm) para o módulo Recrutamento.

    python manage.py importar_rh_xlsm /caminho/Gestao_DB-RH_-_V.2.0.xlsm

O comando é idempotente: usa ``id_legado`` (ID_CADCV / ID_VAGA / ID_REC) como
chave, então rodar de novo atualiza em vez de duplicar. Use ``--dry-run`` para
ver o relatório sem gravar nada.

A planilha acumulou 5 anos de digitação manual, então o importador normaliza:
grafias do responsável pelo contato (FABIOLA/FABÍOLA), cidades com e sem "/RS",
ano de nascimento gravado ora como número ora como texto, e datas que o Excel
guardou como ``time`` (00:00:00) em vez de ``date``.
"""

import re
import unicodedata
from datetime import date, datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from recrutamento.models import AreaInteresse, Candidato, Processo, Vaga

# Colunas de área na aba Cad_Currículos -> nome canônico da AreaInteresse.
AREAS = [
    'CONTABIL', 'FINANCEIRO', 'COMERCIAL', 'RECURSOS HUMANOS', 'DEPARTAMENTO PESSOAL',
    'MOTORISTA INTERNO', 'MOTORISTA EXTERNO', 'OPERADOR DE MAQUINAS', 'COZINHEIRA',
    'LIMPEZA', 'TECNICO EM SEGURANCA', 'PORTARIA', 'TI', 'MANUTENCAO PREDIAL',
    'MECANICO INDUSTRIAL', 'MECANICO AUTOMOTIVO', 'ELETRICISTA', 'RECEPCAO',
    'EXPEDICAO / LOGISTICA', 'ALMOXARIFADO', 'LABORATORIO', 'FABRICA_GERAIS', 'MARKETING',
]

PARECER_MAP = {
    'INDICADO(A)': Processo.PARECER_INDICADO,
    'INDICADO(A) COM RESTRICOES': Processo.PARECER_INDICADO_RESTRICOES,
    'CONTRAINDICADO(A)': Processo.PARECER_CONTRAINDICADO,
}

ESCOLARIDADES = {c[0] for c in Candidato.ESCOLARIDADE_CHOICES}
ESTADOS_CIVIS = {c[0] for c in Candidato.ESTADO_CIVIL_CHOICES}
NIVEIS = {c[0] for c in Candidato.NIVEL_CHOICES}
TURNOS = {c[0] for c in Candidato.TURNO_CHOICES}


def sem_acento(texto):
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn'
    )


def txt(valor, limite=None):
    """Normaliza célula para texto limpo ('' quando vazia)."""
    if valor is None:
        return ''
    if isinstance(valor, (datetime, date, time)):
        return ''
    s = str(valor).replace('_x000D_', '').strip()
    if s.lower() in ('none', 'nan', '-', '(vazio)'):
        return ''
    s = re.sub(r'[ \t]+', ' ', s)
    return s[:limite] if limite else s


def data(valor):
    """Converte célula em ``date``. O Excel salvou várias como time/serial."""
    if valor is None or isinstance(valor, time):
        return None
    if isinstance(valor, datetime):
        # 1900-01-01 é o "zero" do Excel: aparece onde a fórmula não achou data.
        return None if valor.year <= 1900 else valor.date()
    if isinstance(valor, date):
        return None if valor.year <= 1900 else valor
    s = txt(valor)
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d/%m/%y'):
        try:
            d = datetime.strptime(s, fmt).date()
            return None if d.year <= 1900 else d
        except ValueError:
            continue
    return None


def booleano(valor):
    """SIM/NÃO/X -> True/False; vazio -> None."""
    s = sem_acento(txt(valor)).upper()
    if s in ('SIM', 'S', 'X', 'TRUE', '1'):
        return True
    if s in ('NAO', 'N', 'FALSE', '0'):
        return False
    return None


def inteiro(valor):
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return int(valor)
    achados = re.findall(r'\d+', str(valor))
    return int(achados[0]) if achados else None


def ano_nascimento(valor):
    """ANO_NASC vem ora como 1971, ora como '14/02/1988'. Devolve (ano, data)."""
    d = data(valor)
    if d:
        return d.year, d
    n = inteiro(valor)
    if n and 1920 <= n <= date.today().year:
        return n, None
    return None, None


def normaliza_pessoa(valor):
    """Une grafias do mesmo nome: 'FABÍOLA SILVEIRA' e 'FABIOLA SILVEIRA'."""
    s = txt(valor).upper()
    if not s:
        return ''
    return re.sub(r'\s+', ' ', sem_acento(s)).strip()


def normaliza_cidade(valor):
    """'CAÇAPAVA DO SUL/RS' e 'CAÇAPAVA DO SUL' viram a mesma cidade."""
    s = txt(valor, 120).upper()
    if not s:
        return ''
    s = re.sub(r'\s*[/-]\s*[A-Z]{2}\s*$', '', s)  # remove UF no fim
    return re.sub(r'\s+', ' ', s).strip()


def escolha(valor, validos):
    """Devolve o valor apenas se casar com uma das choices; senão ''."""
    s = txt(valor).upper()
    if s in validos:
        return s
    sem = sem_acento(s)
    for v in validos:
        if sem_acento(v) == sem:
            return v
    return ''


class Command(BaseCommand):
    help = 'Importa a planilha de RH (.xlsm) para o módulo Recrutamento e Seleção.'

    def add_arguments(self, parser):
        parser.add_argument('arquivo', help='Caminho do .xlsm')
        parser.add_argument('--dry-run', action='store_true', help='Não grava nada; só relata.')

    def handle(self, *args, **opts):
        try:
            import openpyxl
        except ImportError:
            raise CommandError('openpyxl não instalado: pip install openpyxl')

        caminho = opts['arquivo']
        self.stdout.write(f'Lendo {caminho} ...')
        try:
            wb = openpyxl.load_workbook(caminho, data_only=True, read_only=True)
        except Exception as exc:
            raise CommandError(f'Não consegui abrir a planilha: {exc}')

        try:
            with transaction.atomic():
                areas = self._areas()
                cvs = self._candidatos(wb, areas)
                vagas = self._vagas(wb)
                self._processos(wb, cvs, vagas)
                if opts['dry_run']:
                    self.stdout.write(self.style.WARNING('\n--dry-run: rollback, nada foi gravado.'))
                    transaction.set_rollback(True)
        finally:
            wb.close()

        self.stdout.write(self.style.SUCCESS('\nImportação concluída.'))

    # -- leitura -------------------------------------------------------------

    def _linhas(self, wb, aba, linha_cabecalho):
        ws = wb[aba]
        cabecalho = None
        for i, linha in enumerate(ws.iter_rows(values_only=True), start=1):
            if i < linha_cabecalho:
                continue
            if i == linha_cabecalho:
                cabecalho = [txt(c) for c in linha]
                continue
            registro = {h: v for h, v in zip(cabecalho, linha) if h}
            if any(v is not None and txt(v) != '' for v in registro.values()):
                yield registro

    # -- áreas ---------------------------------------------------------------

    def _areas(self):
        mapa = {}
        for ordem, nome in enumerate(AREAS):
            area, _ = AreaInteresse.objects.get_or_create(nome=nome, defaults={'ordem': ordem})
            mapa[nome] = area
        self.stdout.write(f'  áreas de interesse: {len(mapa)}')
        return mapa

    # -- candidatos ----------------------------------------------------------

    def _cidades_canonicas(self, wb):
        """
        Escolhe uma grafia oficial por cidade.

        'ALMIRANTE TAMANDARÉ' e 'ALMIRANTE TAMANDARE' são a mesma cidade; agrupa
        pela versão sem acento e adota a grafia mais frequente do acervo.
        """
        from collections import Counter

        contagem = {}
        for reg in self._linhas(wb, 'Cad_Currículos', 6):
            cidade = normaliza_cidade(reg.get('CIDADE'))
            if cidade:
                contagem.setdefault(sem_acento(cidade), Counter())[cidade] += 1
        return {chave: grafias.most_common(1)[0][0] for chave, grafias in contagem.items()}

    def _candidatos(self, wb, areas):
        criados = atualizados = 0
        por_legado = {}
        cidades = self._cidades_canonicas(wb)
        for reg in self._linhas(wb, 'Cad_Currículos', 6):
            nome = txt(reg.get('NOME_CANDIDATO'), 255)
            legado = inteiro(reg.get('ID_CADCV'))
            if not nome or not legado:
                continue

            ano, nasc = ano_nascimento(reg.get('ANO_NASC'))
            cidade = normaliza_cidade(reg.get('CIDADE'))
            campos = {
                'nome': nome,
                'data_recebimento': data(reg.get('DATA_REC')),
                'ano_nascimento': ano,
                'data_nascimento': nasc,
                'sexo': escolha(reg.get('SEXO'), {'MASCULINO', 'FEMININO'}),
                'estado_civil': escolha(reg.get('ESTADO_CIVIL'), ESTADOS_CIVIS),
                'endereco': txt(reg.get('ENDERECO_RESIDENCIAL'), 255),
                'cidade': cidades.get(sem_acento(cidade), cidade),
                'telefone_principal': txt(reg.get('TELEFONE_PRINCIPAL'), 30),
                'telefone_contato': txt(reg.get('TELEFONE_CONTATO'), 30),
                'tem_ctps': booleano(reg.get('CTPS_S_N')),
                'ctps_numero': txt(reg.get('CTPS_NUM'), 40),
                'identidade': txt(reg.get('IDENTIDADE_NUM'), 40),
                'cpf': txt(reg.get('CPF_NUM'), 20),
                'titulo_eleitor': txt(reg.get('TITULO_ELEIT_NUM'), 40),
                'certificado_reservista': txt(reg.get('CART_RESERV'), 40),
                'cnh_categoria': txt(reg.get('CART_MOT_CAT'), 5),
                'cnh_numero': txt(reg.get('CART_MOT_NUM'), 40),
                'pis': txt(reg.get('PIS_NUM'), 40),
                'numero_dependentes': inteiro(reg.get('Nº DEPENDENTES')),
                'nome_conjuge': txt(reg.get('NOME_CONJUGE'), 255),
                'nascimento_conjuge': data(reg.get('DATA_NASC_CONJUGE')),
                'profissao_conjuge': txt(reg.get('PROFISSAO_CONJUGE'), 120),
                'nome_pai': txt(reg.get('NOME_PAI'), 255),
                'nascimento_pai': data(reg.get('DATA_NASC_PAI')),
                'profissao_pai': txt(reg.get('PROFISSAO_PAI'), 120),
                'nome_mae': txt(reg.get('NOME_MAE'), 255),
                'nascimento_mae': data(reg.get('DATA_NASC_MAE')),
                'profissao_mae': txt(reg.get('PROFISSAO_MAE'), 120),
                'ultima_empresa': txt(reg.get('ULT_EMPRESA'), 180),
                'ultima_empresa_periodo': txt(reg.get('PERIODO_ULT_EMPRESA'), 80),
                'ultima_empresa_funcao': txt(reg.get('FUNCAO_ULT_EMPRESA'), 180),
                'penultima_empresa': txt(reg.get('PENULT_EMPRESA'), 180),
                'penultima_empresa_periodo': txt(reg.get('PERIODO_PENULT_EMPRESA'), 80),
                'penultima_empresa_funcao': txt(reg.get('FUNCAO_PENULT_EMPRESA'), 180),
                'escolaridade': escolha(reg.get('ESCOLARIDADE'), ESCOLARIDADES),
                'instituicao_ensino': txt(reg.get('INST_ENSINO'), 180),
                'data_conclusao': txt(reg.get('DATA_CONCLUSAO'), 40),
                'estuda_atualmente': booleano(reg.get('ESTUDA_HOJE')),
                'local_estudo': txt(reg.get('LOCAL_ESTUDO'), 180),
                'turno_estudo': escolha(reg.get('TURNO_ESTUDO'), TURNOS),
                'curso_1': txt(reg.get('OUTROS_CURSOS_1'), 180),
                'curso_1_local': txt(reg.get('LOCAL_OUTROS_CURSOS_1'), 180),
                'curso_1_ano': txt(reg.get('ANO_CONCLUSAO_OUT_CURSOS_1'), 20),
                'curso_2': txt(reg.get('OUTROS_CURSOS_2'), 180),
                'curso_2_local': txt(reg.get('LOCAL_OUTROS_CURSOS_2'), 180),
                'curso_2_ano': txt(reg.get('ANO_CONCLUSAO_OUT_CURSOS_2'), 20),
                'nivel_office': escolha(reg.get('OFFICE'), NIVEIS),
                'nivel_internet': escolha(reg.get('INTERNET'), NIVEIS),
                'outros_conhecimentos': txt(reg.get('OUTROS_1')),
                'complemento_escolaridade': txt(reg.get('COMP_ESCOLARIDADE'), 255),
                'funcao_desejada': txt(reg.get('FUNCAO_DESEJADA'), 255),
                'pcd': booleano(reg.get('PCD')),
                'conhece_funcionario': txt(reg.get('CONHECE_FUNC'), 255),
                'ja_trabalhou_db': booleano(reg.get('JA_TRABALHOU_DB')),
                'referencia_1': txt(reg.get('REFERENCIA_1'), 180),
                'referencia_1_telefone': txt(reg.get('TEL_REF_1'), 30),
                'referencia_2': txt(reg.get('REFERENCIA_2'), 180),
                'referencia_2_telefone': txt(reg.get('TEL_REF_2'), 30),
                'pasta_arquivo': txt(reg.get('PASTA_ARQUIVO'), 180),
                'observacoes': txt(reg.get('OBSERVACOES')),
            }
            candidato, novo = Candidato.objects.update_or_create(id_legado=legado, defaults=campos)
            criados += novo
            atualizados += not novo

            marcadas = [areas[a] for a in AREAS if txt(reg.get(a))]
            candidato.areas_interesse.set(marcadas)
            por_legado[legado] = candidato

        self.stdout.write(f'  candidatos: {criados} criados, {atualizados} atualizados')
        return por_legado

    # -- vagas ---------------------------------------------------------------

    def _vagas(self, wb):
        criadas = atualizadas = 0
        por_legado = {}
        validos = {c[0] for c in Vaga.STATUS_CHOICES}
        for reg in self._linhas(wb, 'Cad_Vagas', 6):
            descricao = txt(reg.get('DESCRICAO_VAGA'), 255)
            legado = inteiro(reg.get('ID_VAGA'))
            # A aba tem ~1.000 linhas pré-formatadas em branco; ignora as sem conteúdo.
            # A data de abertura falta em 96 vagas antigas, mas elas têm processos
            # vinculados -- por isso entram assim mesmo, sinalizadas na tela.
            if not descricao or not legado:
                continue
            abertura = data(reg.get('DATA_ABERTURA'))

            status = escolha(reg.get('STATUS'), validos) or Vaga.STATUS_NAO_INFORMADO
            vaga, nova = Vaga.objects.update_or_create(
                id_legado=legado,
                defaults={
                    'descricao': descricao,
                    'requisitante': txt(reg.get('REQUISITANTE'), 180).upper(),
                    'tipo': escolha(reg.get('INT_EXT'), {'INTERNA', 'EXTERNA'}) or Vaga.TIPO_EXTERNA,
                    'data_abertura': abertura,
                    'prazo_encerramento': data(reg.get('PRAZO_ENCERRAR')),
                    'status': status,
                    'data_retorno_requisitante': data(reg.get('DATA_RET_REQUISIT')),
                },
            )
            criadas += nova
            atualizadas += not nova
            por_legado[legado] = vaga

        self.stdout.write(f'  vagas: {criadas} criadas, {atualizadas} atualizadas')
        return por_legado

    # -- processos -----------------------------------------------------------

    def _processos(self, wb, cvs, vagas):
        criados = atualizados = 0
        sem_candidato = sem_vaga = 0
        for reg in self._linhas(wb, 'Recrutamento', 6):
            legado = inteiro(reg.get('ID_REC'))
            candidato = cvs.get(inteiro(reg.get('ID_CADCV')))
            if not legado:
                continue
            if not candidato:
                # Sem currículo correspondente não há como criar o vínculo.
                sem_candidato += 1
                continue

            vaga = vagas.get(inteiro(reg.get('ID_VAGA')))
            if not vaga:
                sem_vaga += 1

            parecer_bruto = sem_acento(txt(reg.get('PARECER'))).upper()
            processo, novo = Processo.objects.update_or_create(
                id_legado=legado,
                defaults={
                    'candidato': candidato,
                    'vaga': vaga,
                    'data_contato': data(reg.get('DATA_CONTATO')),
                    'responsavel_contato': normaliza_pessoa(reg.get('RESP_CONTATO'))[:120],
                    'tentativas_contato': inteiro(reg.get('TENTATIVAS_CONTATO')),
                    'contato_com_sucesso': self._contato(reg.get('CONTATO_C_S_SUCESSO')),
                    'data_entrevista': data(reg.get('DATA_ENTREVISTA')),
                    'compareceu': booleano(reg.get('COMPARECEU_S_N')),
                    'data_parecer': data(reg.get('DATA_PARECER')),
                    'parecer': PARECER_MAP.get(parecer_bruto, ''),
                    'data_retorno_requisitante': data(reg.get('DATA_RET_REQUISTANTE')),
                    'observacao_requisitante': txt(reg.get('OBSERVAÇÃO_1')),
                    'data_retorno_candidato': data(reg.get('DATA_RETORNO_CANDIDATO')),
                    'observacao_candidato': txt(reg.get('OBSERVAÇÃO_2')),
                    'contratado': booleano(reg.get('CONTRATADO')),
                    'data_contratacao': data(reg.get('DATA_CONTRATACAO')),
                    'ex_funcionario': booleano(reg.get('EX_FUNC')) or False,
                },
            )
            criados += novo
            atualizados += not novo

        self.stdout.write(f'  processos: {criados} criados, {atualizados} atualizados')
        if sem_candidato:
            self.stdout.write(self.style.WARNING(
                f'  {sem_candidato} linhas de Recrutamento ignoradas (ID_CADCV sem currículo)'
            ))
        if sem_vaga:
            self.stdout.write(self.style.WARNING(
                f'  {sem_vaga} processos importados sem vaga (ID_VAGA vazio ou inexistente)'
            ))

    @staticmethod
    def _contato(valor):
        """COM SUCESSO / SEM SUCESSO -- a coluna também tem lixo (datas)."""
        s = sem_acento(txt(valor)).upper()
        if 'COM SUCESSO' in s:
            return True
        if 'SEM SUCESSO' in s:
            return False
        return None
