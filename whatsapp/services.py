"""Regras de negócio desacopladas da ingestão do webhook (fácil de trocar por NLP no futuro)."""
import logging
from datetime import timedelta

from django.utils import timezone

from .models import ConfiguracaoAtendimento, Fila, Mensagem, WhatsAppNotificacao
from . import graph_api

logger = logging.getLogger(__name__)

# Quantas vezes o menu é mandado antes de jogar o cliente na fila padrão.
TENTATIVAS_MAXIMAS = 3

# Depois desse tempo sem o atendente falar, a próxima mensagem volta a ser
# assinada. Sem isso, uma conversa retomada no dia seguinte continuaria sem nome
# só porque o último a falar foi a mesma pessoa.
INTERVALO_REASSINATURA = timedelta(hours=4)


def _filas_ativas():
    return list(Fila.objects.filter(ativa=True).order_by('ordem', 'nome'))


# ── Assinatura do atendente ──────────────────────────────────────────────────
# A Cloud API entrega tudo pelo número da empresa: o cliente vê "Grupo DB" e não
# tem como saber com quem está falando. O nome só chega se for junto do conteúdo.

def nome_do_atendente(usuario) -> str:
    """Primeiro nome do atendente; cai no username quando o cadastro está vazio."""
    if usuario is None:
        return ''
    return (usuario.first_name or '').strip() or usuario.username


def _deve_assinar(mensagem) -> bool:
    """
    Assina só quando o nome acrescenta informação: na primeira fala do atendente,
    quando outra pessoa assume, ou quando a conversa ficou parada.

    Repetir o nome em toda linha polui o histórico do cliente — numa sequência de
    cinco mensagens seguidas ele lê o mesmo "*Jian:*" cinco vezes.
    """
    if mensagem.autor_id is None:
        return False  # bot: menu de setores, confirmação de roteamento

    anterior = (
        Mensagem.objects
        .filter(
            conversa_id=mensagem.conversa_id,
            direcao='SAIDA',
            autor__isnull=False,
            created_at__lt=mensagem.created_at,
        )
        # Uma mensagem que não saiu não apresentou ninguém: contá-la faria a
        # próxima tentativa ir sem nome.
        .exclude(status_entrega='FALHOU')
        .exclude(pk=mensagem.pk)
        .order_by('-created_at')
        .first()
    )
    if anterior is None or anterior.autor_id != mensagem.autor_id:
        return True
    return (mensagem.created_at - anterior.created_at) > INTERVALO_REASSINATURA


def assinar_para_cliente(texto: str, mensagem) -> str:
    """
    Devolve o texto como o cliente deve recebê-lo, com o nome do atendente na
    frente quando for o caso.

    Aplicado só na saída para a Meta, de propósito: gravar o prefixo em
    `Mensagem.texto` duplicaria o nome na central, que já mostra o autor embaixo
    da bolha, e sujaria o resumo que vira tarefa no Kanban.
    """
    if not _deve_assinar(mensagem):
        return texto
    nome = nome_do_atendente(mensagem.autor)
    if not nome:
        return texto
    # Sem texto é legenda de mídia: aí o nome vai sozinho, sem os dois-pontos.
    return f'*{nome}:*\n{texto}' if (texto or '').strip() else f'*{nome}*'


def montar_texto_menu(filas=None) -> str:
    filas = filas if filas is not None else _filas_ativas()
    linhas = [ConfiguracaoAtendimento.carregar().texto_menu]
    for i, fila in enumerate(filas, start=1):
        linhas.append(f"{i} - {fila.nome}")
    return "\n".join(linhas)


def montar_texto_roteamento(fila) -> str:
    """
    Confirmação de "você caiu no setor X", com o nome do setor no lugar de {setor}.

    Substituição literal em vez de `str.format`: o texto é digitado por gente no
    admin, e uma chave solta ou um `{Setor}` com maiúscula derrubariam o envio com
    KeyError — no meio de uma task do Celery, onde ninguém vê o erro. Sem o
    marcador o texto simplesmente sai como foi escrito.
    """
    modelo = ConfiguracaoAtendimento.carregar().texto_roteamento
    return modelo.replace('{setor}', fila.nome)


def responder_automatico(conversa, texto: str) -> None:
    """
    Manda o texto pelo Graph e grava no histórico da conversa.

    Antes o bot chamava `graph_api.enviar_mensagem_texto` direto: o cliente
    recebia o menu, mas nada disso virava `Mensagem`. O atendente abria a central
    e via só as respostas do cliente ("1", "2"), sem a pergunta correspondente.

    `autor` fica nulo de propósito — é o que distingue a fala do bot da fala de
    um atendente, sem precisar de campo novo no modelo.
    """
    agora = timezone.now()
    mensagem = Mensagem.objects.create(
        conversa=conversa,
        direcao='SAIDA',
        tipo='TEXTO',
        texto=texto,
        autor=None,
        status_entrega='PENDENTE',
    )
    try:
        resposta = graph_api.enviar_mensagem_texto(conversa.contato_telefone, texto)
        mensagem.wa_message_id = resposta.get('messages', [{}])[0].get('id')
        mensagem.status_entrega = 'ENVIADA'
    except Exception as exc:
        # Sem o registro da falha, um menu que não saiu vira silêncio: o cliente
        # não responde e ninguém na central entende por quê.
        logger.exception('Falha ao enviar resposta automática (conversa_id=%s)', conversa.id)
        mensagem.status_entrega = 'FALHOU'
        mensagem.erro_detalhe = str(exc)
    mensagem.save(update_fields=['wa_message_id', 'status_entrega', 'erro_detalhe'])

    conversa.ultima_mensagem_em = agora
    conversa.save(update_fields=['ultima_mensagem_em'])


def _enviar_menu(conversa, filas) -> None:
    """Manda o menu e contabiliza o envio — `tentativas_menu` é o que impede o loop."""
    conversa.tentativas_menu += 1
    conversa.save(update_fields=['tentativas_menu'])
    responder_automatico(conversa, montar_texto_menu(filas))


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
    filas = _filas_ativas()

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

    responder_automatico(conversa, montar_texto_roteamento(fila_encontrada))
    _notificar_membros(
        conversa, fila_encontrada, 'CONVERSA_ATRIBUIDA',
        f"Nova conversa de {conversa.contato_nome or conversa.contato_telefone}"
    )
