"""
Cadastra na Meta os templates que o atendimento precisa.

Template é objeto da Meta, não do nosso banco: ele é criado na conta (WABA), passa
por revisão dela e só então pode ser enviado. Este comando existe para o cadastro
ficar versionado — o mesmo texto pode ser recriado em outra conta sem alguém ter de
lembrar o que foi digitado no WhatsApp Manager.

Uso (no servidor, onde o token é válido):

    python manage.py criar_templates_whatsapp              # só mostra o que faria
    python manage.py criar_templates_whatsapp --confirmar  # cria de verdade
    python manage.py criar_templates_whatsapp --confirmar --apenas retomada_atendimento

Precisa de:
  - WHATSAPP_BUSINESS_ACCOUNT_ID no .env (o id da conta no WhatsApp Manager);
  - token com a permissão `whatsapp_business_management` — a de envio
    (`whatsapp_business_messaging`) NÃO cria template.
"""
from django.core.management.base import BaseCommand, CommandError

from whatsapp import graph_api


# Regras da Meta que derrubam o cadastro e são fáceis de esbarrar sem saber:
#   - variável no começo ou no fim do corpo é reprovada;
#   - duas variáveis colodas ({{1}} {{2}}) também;
#   - a numeração tem de ser sequencial a partir de {{1}}.
# Os textos abaixo já respeitam isso.
TEMPLATES = [
    {
        'nome': 'retomada_atendimento',
        # O do banner "Janela de 24h encerrada": o atendente escolhe na Central e
        # manda para o cliente voltar a escrever, reabrindo a janela.
        'corpo': (
            'Olá! Aqui é o atendimento do Grupo DB. '
            'Estamos retomando a sua solicitação sobre {{1}}. '
            'Se ainda precisar de ajuda, responda esta mensagem que seguimos de onde paramos.'
        ),
        'exemplos': ['orçamento de calcário'],
        'categoria': 'UTILITY',
    },
    {
        'nome': 'andamento_tarefa',
        # Este é consumido por código, não por gente: services.avisar_andamento_tarefa
        # manda exatamente 2 parâmetros, nesta ordem (título e situação). Mudar a
        # quantidade de variáveis aqui quebra o envio automático.
        'corpo': (
            'Atualização da sua solicitação no Grupo DB. '
            'Assunto: {{1}}. '
            'Situação atual: {{2}}. '
            'Responda esta mensagem se quiser falar com um atendente.'
        ),
        'exemplos': ['Troca do medidor', 'Em andamento'],
        'categoria': 'UTILITY',
    },
    # ── Do RH ────────────────────────────────────────────────────────────────
    # Os dois vêm de três textos que o RH propôs em 25/08/2026. O terceiro
    # ("Oi, tudo bem?") não está aqui porque saudação pura é reprovada por
    # conteúdo genérico: a Meta exige que o template diga PARA QUÊ está sendo
    # mandado. É a mesma regra que faz o `{{2}}` do `abertura_rh` ser obrigatório
    # e não enfeite.
    #
    # Destinatário aqui é FUNCIONÁRIO, não cliente. Mensagem não esperada gera
    # bloqueio e denúncia, e isso derruba a qualidade do número — atrasando e
    # encarecendo todo envio, inclusive o atendimento normal.
    {
        'nome': 'abertura_rh',
        # O que o RH pediu como "template de abertura": a Cloud API não mostra
        # quem escreve (o cliente vê só "Grupo DB"), então o nome do atendente
        # tem de vir dentro do texto. O {{1}} é esse "me chamo Karyna"; o {{2}} é
        # o motivo, que é o que faz a revisão da Meta passar.
        'corpo': (
            'Olá! Aqui é {{1}}, do RH do Grupo Dagoberto Barcellos. '
            'Preciso falar com você sobre {{2}}. '
            'Pode responder esta mensagem quando puder?'
        ),
        'exemplos': ['Karyna', 'seu atestado médico'],
        'categoria': 'UTILITY',
    },
    {
        'nome': 'comparecer_rh',
        # Pedido do RH em 02/09/2026, no texto que eles escreveram. É irmão do
        # `abertura_rh`: mesma abertura com o nome de quem fala, e a chamada muda
        # de "responda esta mensagem" para "venha até o RH".
        #
        # ⚠️ RISCO DE REPROVAÇÃO, e é o mesmo do "Oi, tudo bem?" que ficou de
        # fora: "preciso falar contigo" NÃO diz sobre o quê. A Meta reprova
        # template sem propósito declarado, e foi exatamente por isso que o
        # `abertura_rh` ganhou o {{2}} do motivo. Este vai como o RH pediu, sem
        # o motivo, porque a graça dele é ser curto e não exigir que o atendente
        # digite o assunto. Se a revisão reprovar, o caminho é trocar o corpo por:
        #
        #     'Oi! Aqui é {{1}}, do RH do Grupo Dagoberto Barcellos. '
        #     'Preciso falar com você sobre {{2}}. Consegue passar aqui no RH?'
        #     exemplos: ['Karyna', 'seu atestado médico']
        #
        # e recriar — template reprovado não se reenvia igual.
        #
        # ⚠️ "é a" pressupõe nome feminino. Serve para Karyna e Ana, que são quem
        # usa hoje; se algum homem do RH for mandar, o texto sai errado e o
        # conserto é trocar por "aqui é {{1}}" — o que exige NOVO template, porque
        # corpo aprovado não se edita sem passar por revisão de novo.
        'corpo': (
            'Oi, é a {{1}}, preciso falar contigo, '
            'consegue passar aqui no RH?'
        ),
        'exemplos': ['Karyna'],
        'categoria': 'UTILITY',
    },
    {
        'nome': 'aniversario_bolinho',
        # Sem variável de propósito: é o cadastro mais simples que existe, e sem
        # exemplo não há o que a Meta reprove no preenchimento.
        #
        # MARKETING não é escolha nossa: nasceu UTILITY e a Meta reclassificou em
        # 26/08/2026 ("incluiu conteúdo da categoria marketing"). Para ela, UTILITY
        # é mensagem ligada a uma transação ou a um pedido do próprio destinatário,
        # e presente de aniversário é oferta espontânea. Já vai cadastrado como
        # MARKETING para não repetir a dança da reclassificação.
        #
        # ⚠️ Não é o emoji. Tirar o 🎂 não devolve a categoria — a regra é sobre
        # propósito, não sobre forma. E reescrever para "parecer" utilidade arrisca
        # reprovação ou marca de política, o que é pior que a tarifa de marketing.
        'corpo': (
            'Olá! Aqui é o RH do Grupo Dagoberto Barcellos. '
            'Temos um bolinho reservado para você pela passagem do seu aniversário 🎂 '
            'Quando puder, passe no RH para retirar. Parabéns!'
        ),
        'exemplos': [],
        'categoria': 'MARKETING',
    },
]


class Command(BaseCommand):
    help = 'Cria na Meta os templates de retomada de atendimento e de andamento de tarefa.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar', action='store_true',
            help='Sem esta opção o comando só imprime o que enviaria (nada é criado).',
        )
        parser.add_argument(
            '--apenas', action='append', default=[], metavar='NOME',
            help='Cria só o template indicado. Pode repetir a opção.',
        )

    def handle(self, *args, **opcoes):
        escolhidos = opcoes['apenas']
        alvos = [t for t in TEMPLATES if not escolhidos or t['nome'] in escolhidos]
        if not alvos:
            raise CommandError(
                f"Nenhum template com esse nome. Disponíveis: "
                f"{', '.join(t['nome'] for t in TEMPLATES)}"
            )

        # Listar antes evita o erro de nome duplicado e mostra o status do que já
        # existe — um template reprovado precisa ser editado na Meta, não recriado.
        try:
            existentes = {t.get('name'): t.get('status') for t in graph_api.listar_templates()}
        except Exception as exc:
            raise CommandError(f'Falha ao listar os templates da conta: {exc}')

        for template in alvos:
            nome = template['nome']
            if nome in existentes:
                self.stdout.write(self.style.WARNING(
                    f'· {nome}: já existe na conta (status {existentes[nome]}) — nada feito.'
                ))
                continue

            self.stdout.write(f'· {nome} [{template["categoria"]}]')
            self.stdout.write(f'  {template["corpo"]}')
            self.stdout.write(f'  exemplos: {template["exemplos"]}')

            if not opcoes['confirmar']:
                self.stdout.write(self.style.NOTICE('  (simulação — use --confirmar para criar)'))
                continue

            try:
                resposta = graph_api.criar_template(
                    nome=nome,
                    corpo=template['corpo'],
                    exemplos=template['exemplos'],
                    categoria=template['categoria'],
                )
            except Exception as exc:
                self.stderr.write(self.style.ERROR(
                    f'  falhou: {graph_api.detalhe_do_erro(exc)}'
                ))
                continue

            self.stdout.write(self.style.SUCCESS(
                f'  criado (id {resposta.get("id")}, status {resposta.get("status")}) — '
                f'aguardando revisão da Meta.'
            ))

        if opcoes['confirmar']:
            self.stdout.write(
                '\nDepois de a Meta aprovar: o "andamento_tarefa" precisa ir para o .env '
                'em WHATSAPP_TEMPLATE_ANDAMENTO_TAREFA (e reiniciar o Celery). '
                'O "retomada_atendimento" já aparece sozinho na Central.'
            )
