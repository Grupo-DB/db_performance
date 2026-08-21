"""Regras de negócio desacopladas da ingestão do webhook (fácil de trocar por NLP no futuro)."""
import unicodedata
import logging
import re

from django.conf import settings
from django.utils import timezone

from django.db.models import Q

from .models import ConfiguracaoAtendimento, Fila, Mensagem, WhatsAppNotificacao
from . import graph_api

logger = logging.getLogger(__name__)

# Quantas vezes o menu é mandado antes de jogar o cliente na fila padrão.
TENTATIVAS_MAXIMAS = 3

# Grupo (django.contrib.auth.Group) que enxerga todas as filas e pode assumir
# qualquer conversa, inclusive as que já estão com outro atendente. É o supervisor
# do atendimento: sem isso, um chamado parado com alguém de folga só saía da
# frente pelo admin do Django.
GRUPO_GESTOR = 'GestorWhatsapp'


def eh_gestor(usuario) -> bool:
    if not usuario or not usuario.is_authenticated:
        return False
    return usuario.is_staff or usuario.groups.filter(name=GRUPO_GESTOR).exists()


def marcar_avisos_lidos(conversa, usuario=None) -> int:
    """
    Dá baixa nos avisos pendentes de uma conversa.

    `lido` é pessoal: o badge de cada um conta o que ELE não leu, mesmo que um colega
    da mesma fila já tenha respondido. É por isso que todas as chamadas de dentro do
    atendimento passam `usuario` — a baixa coletiva (sem `usuario`) ficou disponível
    porque é o que faz sentido em manutenção/limpeza, não no fluxo do dia.

    O efeito colateral da regra pessoal: quem nunca abriu uma conversa que já foi
    encerrada continua com o aviso, e a conversa encerrada não aparece na lista de
    abertas. A saída é ver o arquivo da fila (o botão da caixa na Central) ou zerar a
    fila de uma vez em `marcar-fila-lida`.
    """
    qs = WhatsAppNotificacao.objects.filter(conversa=conversa, lido=False)
    if usuario is not None:
        qs = qs.filter(usuario_notificado=usuario)
    return qs.update(lido=True)


def pode_atender(usuario, conversa) -> bool:
    """
    Quem pode escrever, encerrar e abrir tarefa nesta conversa.

    Regra normal é pertencer à fila. O gestor entra em qualquer uma — de nada
    serviria ele assumir um chamado e depois não conseguir responder.
    """
    if eh_gestor(usuario):
        return True
    return bool(conversa.fila_id) and conversa.fila.membros.filter(pk=usuario.pk).exists()


def _filas_ativas(numero=None):
    """
    Filas que ESTE número oferece no menu.

    Fila com `numero` nulo é compartilhada e aparece em todos; fila de outro
    número não aparece. Sem isso os setores do número de TI entrariam no menu do
    número do Comercial, e o cliente escolheria uma fila que ninguém daquele
    setor atende.
    """
    qs = Fila.objects.filter(ativa=True)
    if numero is not None:
        qs = qs.filter(Q(numero=numero) | Q(numero__isnull=True))
    return list(qs.order_by('ordem', 'nome'))


# ── Assinatura do atendimento ────────────────────────────────────────────────
# A Cloud API entrega tudo pelo número da empresa: o cliente vê "Grupo DB" e não
# tem como saber a que setor caiu. A assinatura só chega se for junto do conteúdo.
#
# A assinatura junta PESSOA e SETOR: "Ana Paula · Grupo DB RH". Só o setor era
# impessoal; só a pessoa fazia o cliente cobrar o atendente pelo nome e estranhar
# quando outro respondia. O rótulo do setor segue editável no admin
# (ConfiguracaoAtendimento.assinatura), então trocá-lo não exige deploy.

def assinatura_do_atendimento(numero=None) -> str:
    """Assinatura configurada; vazia desliga a assinatura por completo."""
    return (ConfiguracaoAtendimento.carregar(numero).assinatura or '').strip()


# Nomes compostos são a razão de isto não ser um `split()[0]`: "ANA PAULA DILHE
# LEAL" viraria "Ana". A lista é curta de propósito — errar para menos ("José"
# no lugar de "José Carlos") passa despercebido; errar para mais, não.
_PRIMEIROS_COMPOSTOS = {
    'ana', 'maria', 'jose', 'joao', 'luiz', 'luis', 'antonio', 'carlos',
    'paulo', 'pedro', 'francisco', 'marco', 'marcos', 'jean', 'joana', 'rosa',
}
_CONECTIVOS = {'de', 'da', 'do', 'das', 'dos', 'e'}


def _sem_acento(texto: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )


def primeiro_nome(nome: str) -> str:
    """
    "ANA PAULA DILHE LEAL" -> "Ana Paula"; "MATHEUS SOARES MEDEIROS" -> "Matheus".

    O `capitalize()` existe porque boa parte do cadastro de Colaborador está em
    caixa alta, e assinar em CAIXA ALTA parece grito dentro da conversa.
    """
    partes = [p for p in (nome or '').split() if p]
    if not partes:
        return ''
    escolhidas = [partes[0]]
    if (len(partes) >= 3
            and _sem_acento(partes[0]).lower() in _PRIMEIROS_COMPOSTOS
            and _sem_acento(partes[1]).lower() not in _CONECTIVOS):
        escolhidas.append(partes[1])
    return ' '.join(p.capitalize() for p in escolhidas)


def nome_do_atendente(user) -> str:
    """
    O nome da pessoa, nunca o login: os usernames aqui são `anapaula.leal` e
    e-mails, que não servem para o cliente ler.

    A fonte é `Colaborador.nome` porque `User.first_name` está vazio em todos os
    atendentes. Quem não tem colaborador (conta de serviço, cadastro antigo)
    devolve vazio, e a assinatura fica só com o setor.
    """
    if user is None:
        return ''
    # Reverse OneToOne sem registro levanta RelatedObjectDoesNotExist, que o
    # Django faz herdar de AttributeError justamente para o getattr funcionar.
    colaborador = getattr(user, 'colaborador', None)
    if colaborador is not None and (colaborador.nome or '').strip():
        return primeiro_nome(colaborador.nome)
    if (user.first_name or '').strip():
        return primeiro_nome(user.first_name)
    return ''


def _deve_assinar(mensagem) -> bool:
    """
    Toda fala do atendente sai assinada; a do robô, não.

    Antes assinava só a primeira do atendimento e depois de horas paradas, para
    não repetir o rótulo. Passou a assinar sempre a pedido do atendimento: numa
    conversa longa, ou retomada de outro aparelho, o cliente rolava a tela e já
    não sabia com que setor estava falando.
    """
    return mensagem.autor_id is not None  # None é bot: menu de setores, roteamento


def assinar_para_cliente(texto: str, mensagem) -> str:
    """
    Devolve o texto como o cliente deve recebê-lo, com a assinatura do
    atendimento na frente quando for o caso.

    Aplicado só na saída para a Meta, de propósito: gravar o prefixo em
    `Mensagem.texto` duplicaria o rótulo na central, que já mostra o autor
    embaixo da bolha, e sujaria o resumo que vira tarefa no Kanban.
    """
    if not _deve_assinar(mensagem):
        return texto
    # O setor vem do número por onde a conversa entrou: com dois setores,
    # "Grupo DB TI" numa resposta do RH estaria errada.
    setor = assinatura_do_atendimento(mensagem.conversa.numero)
    pessoa = nome_do_atendente(mensagem.autor)
    nome = ' · '.join(parte for parte in (pessoa, setor) if parte)
    if not nome:
        return texto
    # Sem texto é legenda de mídia: aí a assinatura vai sozinha, sem os dois-pontos.
    return f'*{nome}:*\n{texto}' if (texto or '').strip() else f'*{nome}*'


def saudar_se_configurado(conversa) -> None:
    """
    Responde a saudação do número, quando há uma configurada.

    Chamada só no primeiro contato de um atendimento em número sem menu — é o
    equivalente, ali, ao menu de setores que o número com menu manda.

    Silenciosa por padrão: `texto_saudacao` nasce em branco, então nenhum número
    passa a falar sozinho só porque este código existe. Quem quiser saudação
    preenche o campo no admin, sem deploy.
    """
    texto = (ConfiguracaoAtendimento.carregar(conversa.numero).texto_saudacao or '').strip()
    if texto:
        responder_automatico(conversa, texto)


def montar_texto_menu(filas=None, numero=None) -> str:
    filas = filas if filas is not None else _filas_ativas(numero)
    linhas = [ConfiguracaoAtendimento.carregar(numero).texto_menu]
    for i, fila in enumerate(filas, start=1):
        linhas.append(f"{i} - {fila.nome}")
    return "\n".join(linhas)


def montar_texto_roteamento(fila, numero=None) -> str:
    """
    Confirmação de "você caiu no setor X", com o nome do setor no lugar de {setor}.

    Substituição literal em vez de `str.format`: o texto é digitado por gente no
    admin, e uma chave solta ou um `{Setor}` com maiúscula derrubariam o envio com
    KeyError — no meio de uma task do Celery, onde ninguém vê o erro. Sem o
    marcador o texto simplesmente sai como foi escrito.
    """
    modelo = ConfiguracaoAtendimento.carregar(numero).texto_roteamento
    return modelo.replace('{setor}', fila.nome)


def _registrar_saida_automatica(conversa, texto: str, envio, contexto: str, **campos) -> None:
    """
    Grava uma fala do robô no histórico e tenta entregá-la.

    O registro vem antes do envio de propósito: uma entrega que falha precisa
    deixar rastro na central, senão vira silêncio — o cliente não recebe nada e
    ninguém entende por quê.

    `envio` é a chamada ao Graph, passada como função porque o payload muda
    conforme o caminho (texto livre ou template). `autor` fica nulo em todos os
    casos — é o que distingue a fala do robô da de um atendente, sem precisar de
    campo novo no modelo.

    `ultima_mensagem_cliente_em` NÃO é tocado: só uma resposta do cliente reabre
    a janela de 24h, e nada que saia daqui conta como tal.
    """
    agora = timezone.now()
    mensagem = Mensagem.objects.create(
        conversa=conversa, direcao='SAIDA', tipo='TEXTO', texto=texto,
        autor=None, status_entrega='PENDENTE', **campos,
    )
    try:
        resposta = envio()
        mensagem.wa_message_id = resposta.get('messages', [{}])[0].get('id')
        mensagem.status_entrega = 'ENVIADA'
    except Exception as exc:
        logger.exception('%s (conversa_id=%s)', contexto, conversa.id)
        mensagem.status_entrega = 'FALHOU'
        mensagem.erro_detalhe = graph_api.detalhe_do_erro(exc)
    mensagem.save(update_fields=['wa_message_id', 'status_entrega', 'erro_detalhe'])

    conversa.ultima_mensagem_em = agora
    conversa.save(update_fields=['ultima_mensagem_em'])


def responder_automatico(conversa, texto: str) -> None:
    """
    Manda o texto pelo Graph e grava no histórico da conversa.

    Antes o bot chamava `graph_api.enviar_mensagem_texto` direto: o cliente
    recebia o menu, mas nada disso virava `Mensagem`. O atendente abria a central
    e via só as respostas do cliente ("1", "2"), sem a pergunta correspondente.
    """
    _registrar_saida_automatica(
        conversa, texto,
        lambda: graph_api.enviar_mensagem_texto(
            conversa.contato_telefone, texto, numero=conversa.numero),
        'Falha ao enviar resposta automática',
    )


def _enviar_menu(conversa, filas) -> None:
    """Manda o menu e contabiliza o envio — `tentativas_menu` é o que impede o loop."""
    conversa.tentativas_menu += 1
    conversa.save(update_fields=['tentativas_menu'])
    responder_automatico(conversa, montar_texto_menu(filas, conversa.numero))


def _notificar_membros(conversa, fila, tipo, texto_preview):
    if not fila:
        return
    notificacoes = [
        WhatsAppNotificacao(conversa=conversa, usuario_notificado=membro, tipo=tipo, mensagem=texto_preview)
        for membro in fila.membros.all()
    ]
    if notificacoes:
        WhatsAppNotificacao.objects.bulk_create(notificacoes)


def _resolver_por_opcao_ou_palavra_chave(texto: str, filas):
    texto_norm = (texto or '').strip()
    if texto_norm.isdigit():
        indice = int(texto_norm) - 1
        if 0 <= indice < len(filas):
            return filas[indice]
        return None
    texto_lower = texto_norm.lower()
    for fila in filas:
        termos = [t.strip().lower() for t in fila.palavras_chave.split(',') if t.strip()]
        if any(termo in texto_lower for termo in termos):
            return fila
    return None


def resolver_fila_por_texto(texto: str, conversa) -> None:
    """Avança a máquina de estados de roteamento de uma Conversa a partir do texto recebido do cliente."""
    filas = _filas_ativas(conversa.numero)

    if conversa.fila_id and conversa.estado_menu == 'EM_ATENDIMENTO':
        return  # já roteada, nada a fazer aqui

    # `tentativas_menu` é o único sinal de "o menu já foi mostrado nesta rodada":
    # zera na criação e na reabertura da conversa. Antes isto olhava o total de
    # mensagens de ENTRADA, que conta o histórico inteiro do telefone — numa
    # conversa reaberta já passava de 1, então o menu era pulado e a primeira
    # frase do cliente ia direto para o casamento por palavra-chave. Um "bom dia"
    # que por acaso contivesse uma palavra-chave roteava o cliente para um setor
    # que ele nunca escolheu.
    if conversa.tentativas_menu == 0:
        _enviar_menu(conversa, filas)
        return

    fila_encontrada = _resolver_por_opcao_ou_palavra_chave(texto, filas)

    if fila_encontrada is None:
        if conversa.tentativas_menu >= TENTATIVAS_MAXIMAS:
            fila_encontrada = Fila.objects.filter(is_padrao=True, ativa=True).first()
        else:
            _enviar_menu(conversa, filas)
            return

    if fila_encontrada is None:
        # Só cai aqui se esgotou as tentativas e não existe fila padrão ativa.
        # Marcar EM_ATENDIMENTO sem fila deixava a conversa num estado morto:
        # o webhook não notifica ninguém (exige fila) e o roteamento não roda de
        # novo, então o cliente ficava no vácuo sem nada aparecer na central.
        logger.warning(
            'Conversa %s esgotou as tentativas de menu e não há fila padrão ativa configurada.',
            conversa.id,
        )
        return

    conversa.fila = fila_encontrada
    conversa.estado_menu = 'EM_ATENDIMENTO'
    conversa.save(update_fields=['fila', 'estado_menu', 'tentativas_menu'])

    responder_automatico(conversa, montar_texto_roteamento(fila_encontrada, conversa.numero))
    _notificar_membros(
        conversa, fila_encontrada, 'CONVERSA_ATRIBUIDA',
        f"Nova conversa de {conversa.contato_nome or conversa.contato_telefone}"
    )


# ── Aviso de andamento de tarefa do Kanban ───────────────────────────────────
# Disparado pelo signal de `kanban.KanbanTask`, não por um atendente — por isso a
# mensagem sai sem assinatura, como as demais falas do robô.

# A Meta recusa parâmetro de template com quebra de linha, tab ou espaços
# seguidos. Título de tarefa é texto digitado por gente, então passa por aqui
# antes de virar {{1}} — senão o template inteiro é rejeitado no envio.
_ESPACOS_SEGUIDOS = re.compile(r'\s+')
LIMITE_PARAMETRO_TEMPLATE = 200


def _parametro_template(texto: str) -> str:
    return _ESPACOS_SEGUIDOS.sub(' ', (texto or '').strip())[:LIMITE_PARAMETRO_TEMPLATE]


def avisar_andamento_tarefa(conversa, titulo_tarefa: str, andamento: str) -> None:
    """
    Conta ao cliente que a tarefa aberta a partir do atendimento dele mudou de estado.

    O caminho depende da janela de 24h: dentro dela vale texto livre; fora, só
    template aprovado. Uma tarefa costuma andar dias depois do atendimento, então
    o segundo caso é a regra e não a exceção — é por isso que a falta de template
    configurado é tratada aqui como situação prevista, e não como erro.
    """
    if conversa.dentro_da_janela_24h:
        responder_automatico(
            conversa,
            f'Atualização da sua solicitação:\n*{titulo_tarefa}*\nSituação: {andamento}',
        )
        return

    # O texto guardado é só o rastro para o histórico: o corpo real do template
    # mora na Meta e pode ser alterado lá sem passar por aqui.
    previa = f'[andamento] {titulo_tarefa} — {andamento}'
    nome_template = getattr(settings, 'WHATSAPP_TEMPLATE_ANDAMENTO_TAREFA', None)

    if not nome_template:
        # Gravado como falha, e não apenas logado: quem ligou o aviso na tarefa
        # precisa ver na própria conversa que o cliente não foi avisado, e por quê.
        logger.warning(
            'Tarefa mudou de andamento fora da janela de 24h e '
            'WHATSAPP_TEMPLATE_ANDAMENTO_TAREFA não está configurado (conversa_id=%s)',
            conversa.id,
        )
        Mensagem.objects.create(
            conversa=conversa, direcao='SAIDA', tipo='TEXTO', texto=previa, autor=None,
            status_entrega='FALHOU',
            erro_detalhe=(
                'Fora da janela de 24h e nenhum template configurado em '
                'WHATSAPP_TEMPLATE_ANDAMENTO_TAREFA — o cliente não foi avisado.'
            ),
        )
        return

    idioma = getattr(settings, 'WHATSAPP_TEMPLATE_IDIOMA', 'pt_BR')
    componentes = [{
        'type': 'body',
        'parameters': [
            {'type': 'text', 'text': _parametro_template(titulo_tarefa)},
            {'type': 'text', 'text': _parametro_template(andamento)},
        ],
    }]
    _registrar_saida_automatica(
        conversa, previa,
        lambda: graph_api.enviar_template(
            conversa.contato_telefone, nome_template, idioma, componentes,
        ),
        'Falha ao enviar template de andamento de tarefa',
        template_nome=nome_template,
        payload_bruto={'template': nome_template, 'idioma': idioma, 'componentes': componentes},
    )
