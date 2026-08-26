import logging
import mimetypes
import time
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Q
from django.utils import timezone

from . import audio, graph_api, services
from .models import (Conversa, Disparo, DisparoDestinatario, Mensagem, MensagemAnexo,
                     NumeroNegocio, WhatsAppNotificacao)

logger = logging.getLogger(__name__)

_TIPO_MEDIA_CAMPO = {
    'image': 'IMAGEM',
    'document': 'DOCUMENTO',
    'audio': 'AUDIO',
    'video': 'VIDEO',
}

# Tipos que NÃO são mídia para baixar, mas têm bolha própria na tela.
_TIPO_ESTRUTURADO = {
    'contacts': 'CONTATO',
}

# Como descrever, no texto da bolha, o que chegou e não é texto. Sem isto a
# mensagem entrava com tipo TEXTO e corpo vazio — figurinha, localização e
# cartão de contato viravam BOLHA EM BRANCO, sem indício de que algo chegou.
_RESUMO_POR_TIPO = {
    'sticker': '[figurinha]',
    'location': '[localização]',
    'contacts': '[contato]',
    'reaction': '[reação]',
    'button': '[resposta de botão]',
    'interactive': '[resposta de menu]',
    'order': '[pedido]',
    'system': '[aviso do sistema]',
    'unsupported': '[mensagem não suportada]',
}


@shared_task
def processar_webhook_whatsapp(payload: dict):
    try:
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                campo = change.get('field') or ''

                # Coexistência: número que também é atendido no app WhatsApp
                # Business. TODA mensagem que a pessoa manda pelo celular vem por
                # aqui, e só por aqui — não aparece em `messages`. Sem tratar, a
                # Central mostraria a conversa pela metade, só o lado do cliente.
                if campo == 'smb_message_echoes':
                    for echo in value.get('message_echoes', []):
                        _processar_echo(value, echo)
                    continue

                # Ainda não consumidos: `history` são os 180 dias anteriores ao
                # onboarding (chega em 3 fases) e `smb_app_state_sync` são os
                # contatos do celular. Registrar em log é de propósito — assim se
                # vê que chegaram, em vez de descobrir o silêncio depois. A Meta dá
                # 24h para sincronizar, então implementar isto é decisão com prazo.
                if campo in ('history', 'smb_app_state_sync'):
                    logger.info(
                        'Webhook de coexistência recebido e ignorado (field=%s, '
                        'phone_number_id=%s)',
                        campo, value.get('metadata', {}).get('phone_number_id', ''),
                    )
                    continue

                for msg in value.get('messages', []):
                    _processar_mensagem_recebida(value, msg)
                for status in value.get('statuses', []):
                    _processar_status(status)
    except Exception:
        logger.exception('Falha ao processar webhook do WhatsApp')


# O que escrever na bolha do que saiu pelo celular e não é texto nem mídia.
_RESUMO_ECHO = {
    'revoke': '[mensagem apagada no celular]',
    'edit': '[mensagem editada no celular]',
}


def _processar_echo(value: dict, echo: dict):
    """
    Mensagem que a EMPRESA mandou pelo app WhatsApp Business (ou por um aparelho
    conectado), espelhada para cá pelo webhook `smb_message_echoes`.

    Entra como saída sem autor: quem digitou foi alguém no celular, não um
    usuário da Central. Ninguém é notificado — notificação é para mensagem de
    cliente; avisar a fila do que a própria equipe escreveu só faria barulho.
    """
    wa_message_id = echo.get('id')
    telefone = echo.get('to') or ''
    if not wa_message_id or not telefone:
        return
    # Pega os dois casos de uma vez: retry da Meta e o eco do que NÓS mesmos
    # enviamos pela API (o `wa_message_id` já está gravado desde o envio), que
    # senão viraria bolha duplicada em toda resposta dada pela Central.
    if Mensagem.objects.filter(wa_message_id=wa_message_id).exists():
        return

    phone_number_id = value.get('metadata', {}).get('phone_number_id', '')
    numero = NumeroNegocio.resolver(phone_number_id)
    conversa = _conversa_do_echo(telefone, numero, phone_number_id)

    tipo_echo = echo.get('type') or 'text'
    corpo = echo.get(tipo_echo)
    corpo = corpo if isinstance(corpo, dict) else {}
    if tipo_echo == 'text':
        texto = corpo.get('body', '')
    else:
        texto = corpo.get('caption', '')
    tipo_interno = (_TIPO_MEDIA_CAMPO.get(tipo_echo)
                    or _TIPO_ESTRUTURADO.get(tipo_echo)
                    or 'TEXTO')
    if not texto and tipo_echo not in _TIPO_MEDIA_CAMPO:
        texto = (_RESUMO_ECHO.get(tipo_echo)
                 or _RESUMO_POR_TIPO.get(tipo_echo)
                 or f'[{tipo_echo}]')

    # `ultima_mensagem_cliente_em` NÃO se toca aqui: a janela de 24h é contada da
    # fala do CLIENTE, e mensagem nossa não a reabre. Mexer nela deixaria a
    # Central achando que pode mandar texto livre quando a Meta já só aceita
    # template.
    conversa.ultima_mensagem_em = timezone.now()
    conversa.save(update_fields=['ultima_mensagem_em'])

    mensagem = Mensagem.objects.create(
        conversa=conversa,
        direcao='SAIDA',
        tipo=tipo_interno,
        texto=texto,
        autor=None,
        wa_message_id=wa_message_id,
        # A Meta já aceitou e entregou — o `statuses` do mesmo número atualiza
        # daqui para frente, se vier.
        status_entrega='ENVIADA',
        # Sem isto a bolha sairia marcada como "automático" na Central: robô e
        # celular são os dois saída sem autor.
        enviada_pelo_celular=True,
        payload_bruto=echo,
        responde_a=_mensagem_citada(echo),
    )

    if tipo_echo in _TIPO_MEDIA_CAMPO and corpo.get('id'):
        # Mídia do echo é mídia da Meta como qualquer outra: baixar com o token do
        # número, senão a foto que o RH mandou pelo celular não aparece na Central.
        baixar_midia_whatsapp.delay(mensagem.id, corpo['id'])


def _conversa_do_echo(telefone: str, numero, phone_number_id: str):
    """
    A conversa a que este echo pertence, criando-a quando a empresa é que puxou
    o assunto pelo celular.
    """
    qs = Conversa.objects.filter(services.filtro_telefone(telefone))
    if numero is not None:
        qs = qs.filter(Q(numero=numero) | Q(numero__isnull=True))
    conversa = qs.order_by('-created_at').first()

    if conversa is None:
        # Nasce EM_ATENDIMENTO e na fila do número: quem falou primeiro foi a
        # empresa, então perguntar "para qual setor você quer falar?" depois
        # seria absurdo — e o robô faria isso na primeira resposta do cliente.
        return Conversa.objects.create(
            contato_telefone=telefone,
            numero=numero,
            numero_negocio_id=phone_number_id,
            fila=numero.fila_padrao() if numero is not None else None,
            estado_menu='EM_ATENDIMENTO',
        )

    campos = []
    if conversa.numero_id is None and numero is not None:
        conversa.numero = numero
        conversa.numero_negocio_id = phone_number_id
        campos += ['numero', 'numero_negocio_id']
    if conversa.status == 'ENCERRADA':
        # Retomada pelo celular: reabre EM_ATENDIMENTO, e não em
        # AGUARDANDO_SETOR como na volta pelo cliente — já tem gente falando.
        #
        # Sem dono, pelo mesmo motivo da volta pelo cliente: o echo não diz QUEM
        # digitou no celular, então deixar a conversa com quem a encerrou antes
        # esconderia dela a equipe inteira.
        conversa.status = 'ABERTA'
        conversa.estado_menu = 'EM_ATENDIMENTO'
        conversa.responsavel = None
        campos += ['status', 'estado_menu', 'responsavel']
    if conversa.fila_id is None and numero is not None:
        conversa.fila = numero.fila_padrao()
        campos.append('fila')
    if campos:
        conversa.save(update_fields=campos)
    return conversa


def _processar_mensagem_recebida(value: dict, msg: dict):
    telefone = msg.get('from')
    wa_message_id = msg.get('id')
    if Mensagem.objects.filter(wa_message_id=wa_message_id).exists():
        return  # retry do Meta — idempotente

    contato_nome = ''
    for contato in value.get('contacts', []):
        if contato.get('wa_id') == telefone:
            contato_nome = contato.get('profile', {}).get('name', '')
            break

    # Em qual número da empresa a mensagem entrou. `resolver` cai no número padrão
    # quando o id não está cadastrado, para número novo configurado na Meta e
    # esquecido aqui não fazer o webhook perder a mensagem do cliente.
    phone_number_id = value.get('metadata', {}).get('phone_number_id', '')
    numero = NumeroNegocio.resolver(phone_number_id)

    # A busca é pelo PAR (telefone, número): o mesmo cliente escrevendo para o TI e
    # para o Comercial são dois atendimentos, não um. `numero` nulo é conversa
    # anterior ao cadastro dos números — ela continua sendo reaproveitada.
    #
    # E é por TODAS as formas do telefone, não pela string crua: o `wa_id` que a
    # Meta manda aqui é a forma canônica DELA (no Brasil, às vezes sem o nono
    # dígito), enquanto a conversa aberta por template nasceu com o telefone como
    # está na agenda. Comparando cru, a resposta do cliente ao template abria um
    # atendimento novo e partia o histórico em dois.
    conversas_do_contato = Conversa.objects.filter(services.filtro_telefone(telefone))
    if numero is not None:
        conversas_do_contato = conversas_do_contato.filter(
            Q(numero=numero) | Q(numero__isnull=True))
    conversa = conversas_do_contato.order_by('-created_at').first()
    if conversa is None:
        conversa = Conversa.objects.create(
            contato_telefone=telefone,
            contato_nome=contato_nome,
            numero=numero,
            numero_negocio_id=phone_number_id,
        )
    elif conversa.contato_telefone != telefone:
        # Casou por variante: passa a gravar o `wa_id`. É para lá que a Meta
        # entrega, então convergir agora evita que a próxima resposta tenha de
        # casar por variante de novo — e é o número que o atendente vê na tela.
        conversa.contato_telefone = telefone

    if conversa.numero_id is None and numero is not None:
        # Conversa que existia antes dos números cadastrados: assume este.
        conversa.numero = numero
        conversa.numero_negocio_id = phone_number_id
    if conversa.status == 'ENCERRADA':
        conversa.status = 'ABERTA'
        conversa.estado_menu = 'AGUARDANDO_SETOR'
        conversa.tentativas_menu = 0
        # Conversa que volta é atendimento NOVO: solta o dono anterior.
        #
        # No RH cada conversa tem dono, e dono é quem recebe o aviso e quem
        # consegue abrir (services.usuarios_para_avisar / filtro_de_conversas).
        # Mantendo o `responsavel` de quem encerrou dias atrás, o cliente que
        # escrevia de novo virava badge de uma pessoa só — as colegas não eram
        # avisadas e nem enxergavam a conversa para assumir. Zerando aqui, ela
        # entra sem dono: a equipe do número toda é avisada e quem estiver livre
        # assume, exatamente como numa conversa que nasce agora.
        conversa.responsavel = None
    if not conversa.contato_nome and contato_nome:
        conversa.contato_nome = contato_nome

    tipo_msg = msg.get('type', 'text')
    texto = msg.get('text', {}).get('body', '') if tipo_msg == 'text' else ''
    if tipo_msg == 'text':
        tipo_interno = 'TEXTO'
    else:
        tipo_interno = (_TIPO_MEDIA_CAMPO.get(tipo_msg)
                        or _TIPO_ESTRUTURADO.get(tipo_msg)
                        or 'TEXTO')
    # Mídia tem prévia própria na bolha e não precisa de texto; o resto precisa,
    # senão a bolha sai vazia. O payload cru fica guardado de todo jeito.
    if not texto and tipo_msg not in _TIPO_MEDIA_CAMPO:
        texto = _RESUMO_POR_TIPO.get(tipo_msg, f'[{tipo_msg}]') if tipo_msg != 'text' else ''

    agora = timezone.now()
    conversa.ultima_mensagem_em = agora
    conversa.ultima_mensagem_cliente_em = agora
    conversa.save()

    mensagem = Mensagem.objects.create(
        conversa=conversa,
        direcao='ENTRADA',
        tipo=tipo_interno,
        texto=texto,
        wa_message_id=wa_message_id,
        status_entrega='ENTREGUE',
        payload_bruto=msg,
        # Cliente respondendo uma mensagem específica: a Meta manda o id da citada
        # em context.id. Guardar o vínculo é o que deixa a central mostrar "em
        # resposta a" — sem isso um "sim" solto não diz a que ele se refere.
        responde_a=_mensagem_citada(msg),
    )

    media_info = msg.get(tipo_msg) if tipo_msg in _TIPO_MEDIA_CAMPO else None
    if media_info and media_info.get('id'):
        baixar_midia_whatsapp.delay(mensagem.id, media_info['id'])

    if conversa.estado_menu == 'EM_ATENDIMENTO' and conversa.fila_id:
        _notificar_nova_mensagem(conversa, texto or f"[{tipo_interno.lower()}]")
    elif numero is not None and not numero.menu_automatico:
        # Número atendido também pelo app WhatsApp Business (coexistência): o robô
        # não pode falar. Mandar o menu de setores aqui significaria o cliente
        # recebendo "escolha um setor" enquanto uma pessoa já responde à mão pelo
        # celular. A conversa entra direto na fila do número e só avisa a equipe.
        conversa.fila = conversa.fila or numero.fila_padrao()
        conversa.estado_menu = 'EM_ATENDIMENTO'
        conversa.save(update_fields=['fila', 'estado_menu'])
        # Saudação só aqui dentro: este ramo é alcançado uma vez por atendimento
        # (na mensagem seguinte a conversa já está EM_ATENDIMENTO e cai no `if`
        # de cima), então o cliente não recebe o mesmo texto a cada frase que
        # escreve. Em branco, não manda nada.
        services.saudar_se_configurado(conversa)
        _notificar_nova_mensagem(conversa, texto or f"[{tipo_interno.lower()}]")
    else:
        services.resolver_fila_por_texto(texto, conversa)


def _mensagem_citada(msg: dict):
    """
    A mensagem que o cliente citou, quando ela existe no nosso histórico.

    Devolve None sem drama quando o id não é conhecido: a citada pode ser
    anterior à integração, ou ter sido enviada por outro canal.
    """
    citada_id = (msg.get('context') or {}).get('id')
    if not citada_id:
        return None
    return Mensagem.objects.filter(wa_message_id=citada_id).first()


def _notificar_nova_mensagem(conversa: Conversa, preview: str):
    """
    Avisa quem CONSEGUE abrir a conversa, não a fila inteira.

    Era `fila.membros.all()` cru: no RH, onde cada atendente só enxerga o que é
    dele ou o que ainda não tem dono, isso mandava para a colega o aviso de uma
    conversa que ela abre e leva 404 — o "está notificando pra Ana as minhas
    conversas e vice-versa". Na TI o resultado é o mesmo de antes, porque lá o
    atendimento é compartilhado e todo membro da fila passa no filtro.
    """
    notificacoes = [
        WhatsAppNotificacao(
            conversa=conversa, usuario_notificado=membro,
            tipo='NOVA_MENSAGEM', mensagem=preview[:255],
        )
        for membro in services.membros_avisaveis(conversa)
    ]
    if notificacoes:
        WhatsAppNotificacao.objects.bulk_create(notificacoes)


def _motivo_da_falha(status: dict) -> str:
    """
    Texto legível a partir do array `errors` do status.

    Cada erro traz `title` (curto), `error_data.details` (a explicação de verdade)
    e `code`, que é o que se procura na documentação da Meta.
    """
    partes = []
    for erro in status.get('errors') or []:
        titulo = erro.get('title') or erro.get('message') or ''
        detalhes = (erro.get('error_data') or {}).get('details') or ''
        # title e details costumam repetir a mesma frase; só vale juntar se diferem.
        texto = titulo if detalhes.strip() == titulo.strip() else ' — '.join(x for x in (titulo, detalhes) if x)
        codigo = erro.get('code')
        partes.append(f'{texto} (code {codigo})' if codigo else texto)
    return ' | '.join(p for p in partes if p.strip())


def _processar_status(status: dict):
    wa_message_id = status.get('id')
    novo_status = {
        'sent': 'ENVIADA', 'delivered': 'ENTREGUE',
        'read': 'LIDA', 'failed': 'FALHOU',
    }.get(status.get('status'))
    if not novo_status:
        return

    campos = {'status_entrega': novo_status}
    if novo_status == 'FALHOU':
        # Sem isto a mensagem virava um "falhou" mudo na tela: a recusa da Meta é
        # assíncrona, então o envio não levanta exceção nenhuma e o único lugar
        # onde o motivo existe é este payload — que antes era descartado.
        campos['erro_detalhe'] = (
            _motivo_da_falha(status)
            or 'O WhatsApp recusou a mensagem e não informou o motivo.'
        )
        logger.warning('WhatsApp recusou a mensagem %s: %s', wa_message_id, status)

    Mensagem.objects.filter(wa_message_id=wa_message_id).update(**campos)


@shared_task
def baixar_midia_whatsapp(mensagem_id: int, wa_media_id: str):
    try:
        mensagem = Mensagem.objects.select_related('conversa').get(id=mensagem_id)
        # O token importa aqui: mídia de conversa que entrou por número de outra
        # WABA não é acessível com o token do .env.
        numero = mensagem.conversa.numero
        url = graph_api.obter_url_midia(wa_media_id, numero=numero)
        conteudo, content_type = graph_api.baixar_midia(url, numero=numero)
        anexo = MensagemAnexo(mensagem=mensagem, wa_media_id=wa_media_id, mime_type=content_type)
        # Com extensão: o arquivo é servido pelo nginx, que decide o Content-Type
        # pelo nome. Sem ela a foto descia como octet-stream e o navegador não a
        # tratava como imagem (nem no <img> da bolha, nem ao abrir em aba nova).
        anexo.arquivo.save(f'{wa_media_id}{_extensao_da_midia(content_type)}', ContentFile(conteudo), save=True)
    except Exception:
        logger.exception('Falha ao baixar mídia do WhatsApp (media_id=%s)', wa_media_id)


def _extensao_da_midia(content_type: str) -> str:
    """
    Extensão a partir do Content-Type que a Meta devolveu.

    A tabela vem antes do `guess_extension` porque o palpite dele depende da tabela
    de MIME do sistema operacional e varia entre versões do Python — no áudio do
    WhatsApp, por exemplo, ele devolve '.oga' para audio/ogg, extensão que a lista
    padrão do nginx não conhece. Aqui os tipos que sempre aparecem ficam fixos.
    """
    mime = (content_type or '').split(';')[0].strip().lower()
    conhecidas = {
        'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
        'audio/ogg': '.ogg', 'audio/mpeg': '.mp3', 'audio/mp4': '.m4a',
        'video/mp4': '.mp4', 'application/pdf': '.pdf',
    }
    if mime in conhecidas:
        return conhecidas[mime]
    return mimetypes.guess_extension(mime) or ''


def _marcar_enviada(mensagem: Mensagem, resposta: dict):
    mensagem.wa_message_id = resposta.get('messages', [{}])[0].get('id')
    mensagem.status_entrega = 'ENVIADA'
    mensagem.save(update_fields=['wa_message_id', 'status_entrega'])


def _marcar_falha(mensagem: Mensagem, exc: Exception, contexto: str):
    logger.exception('%s (mensagem_id=%s)', contexto, mensagem.id)
    mensagem.status_entrega = 'FALHOU'
    mensagem.erro_detalhe = graph_api.detalhe_do_erro(exc)
    mensagem.save(update_fields=['status_entrega', 'erro_detalhe'])


@shared_task
def enviar_mensagem_whatsapp(mensagem_id: int):
    """
    Entrega ao WhatsApp a mensagem que o atendente escreveu.

    Com anexo o caminho é outro: sobe o arquivo, pega o `media_id` e manda a
    mensagem referenciando esse id. Antes esta task só chamava
    `enviar_mensagem_texto`, então o anexo era gravado no servidor e nunca saía —
    o atendente via o arquivo na tela e o cliente não recebia nada.

    O texto que vai para o cliente não é o mesmo que está gravado: leva o nome do
    atendente na frente (ver `services.assinar_para_cliente`). O cálculo é feito
    uma vez só, antes do envio, porque ele depende de qual foi a última saída da
    conversa — e esta mensagem passa a ser a última assim que sai.
    """
    mensagem = (
        Mensagem.objects
        .select_related('conversa', 'autor', 'responde_a')
        .prefetch_related('anexos')
        .get(id=mensagem_id)
    )
    telefone = mensagem.conversa.contato_telefone
    anexo = mensagem.anexos.first()
    texto_para_cliente = services.assinar_para_cliente(mensagem.texto, mensagem)
    # Só cita o que a Meta conhece: mensagem nossa que ainda não saiu (ou anterior
    # à integração) não tem wa_message_id, e mandar `context` com id inválido faz
    # a Meta recusar a mensagem inteira em vez de só ignorar a citação.
    citando = (mensagem.responde_a.wa_message_id or '') if mensagem.responde_a_id else ''

    if anexo is None:
        try:
            _marcar_enviada(
                mensagem,
                graph_api.enviar_mensagem_texto(
                telefone, texto_para_cliente, citando=citando, numero=mensagem.conversa.numero),
            )
        except Exception as exc:
            _marcar_falha(mensagem, exc, 'Falha ao enviar texto do WhatsApp')
        return

    try:
        nome = anexo.nome_original or anexo.arquivo.name.rsplit('/', 1)[-1]
        with anexo.arquivo.open('rb') as arquivo:
            conteudo = arquivo.read()

        categoria = graph_api.categoria_da_midia(anexo.mime_type, nome)
        mime_envio = anexo.mime_type
        if categoria == graph_api.CATEGORIA_AUDIO:
            # O arquivo guardado continua sendo o original — é o que a central
            # toca para o atendente, e o navegador dele lê webm sem problema.
            # A conversão vale só para o que sobe à Meta.
            conteudo, mime_envio, nome = audio.preparar_para_whatsapp(conteudo, anexo.mime_type, nome)

        media_id = graph_api.upload_midia(conteudo, nome, mime_envio, numero=mensagem.conversa.numero)
        anexo.wa_media_id = media_id
        anexo.save(update_fields=['wa_media_id'])

        resposta = graph_api.enviar_midia(
            telefone, media_id, categoria, legenda=texto_para_cliente,
            nome_arquivo=nome, citando=citando, numero=mensagem.conversa.numero,
        )
        _marcar_enviada(mensagem, resposta)
    except Exception as exc:
        _marcar_falha(mensagem, exc, 'Falha ao enviar mídia do WhatsApp')
        return

    # Áudio não aceita legenda na Cloud API. Em vez de descartar o que o atendente
    # escreveu, o texto sai como mensagem própria, logo depois do áudio.
    #
    # A condição olha o texto JÁ assinado: num áudio sem legenda que seria a
    # primeira fala do atendente, o que sobra é só o nome — e ele precisa sair,
    # senão o cliente nunca fica sabendo quem mandou o áudio e a mensagem seguinte
    # já não assina mais (esta aqui passa a ser a última saída da conversa).
    if texto_para_cliente and categoria not in graph_api.CATEGORIAS_COM_LEGENDA:
        try:
            graph_api.enviar_mensagem_texto(
                telefone, texto_para_cliente, numero=mensagem.conversa.numero)
        except Exception:
            logger.exception(
                'Mídia enviada, mas a legenda avulsa falhou (mensagem_id=%s)', mensagem_id,
            )


@shared_task
def enviar_template_whatsapp(mensagem_id: int, nome_template: str, idioma: str, componentes: list | None):
    """
    Envia um template aprovado — o único caminho fora da janela de 24h.

    Fica em task separada porque o payload é outro e porque a falha aqui é
    diferente: template não aprovado, nome errado ou idioma inexistente devolvem
    erro da Meta que o atendente precisa ler para corrigir.
    """
    mensagem = Mensagem.objects.select_related('conversa').get(id=mensagem_id)
    try:
        resposta = graph_api.enviar_template(
            mensagem.conversa.contato_telefone, nome_template, idioma, componentes,
            numero=mensagem.conversa.numero,
        )
        _marcar_enviada(mensagem, resposta)
    except Exception as exc:
        _marcar_falha(mensagem, exc, 'Falha ao enviar template do WhatsApp')


@shared_task
def enviar_contato_whatsapp(mensagem_id: int):
    """
    Envia os cartões de contato já montados na hora do POST.

    Os cartões vêm prontos de `payload_bruto['contacts']`: quem monta é a view,
    porque é lá que estão os ids da agenda. A task só entrega — assim uma
    mudança na agenda depois do envio não reescreve o que o cliente recebeu.
    """
    mensagem = Mensagem.objects.select_related('conversa').get(id=mensagem_id)
    cartoes = (mensagem.payload_bruto or {}).get('contacts') or []
    if not cartoes:
        _marcar_falha(mensagem, ValueError('sem cartões no payload'),
                      'Mensagem de contato sem cartão para enviar')
        return

    citando = mensagem.responde_a.wa_message_id if mensagem.responde_a_id else ''
    try:
        resposta = graph_api.enviar_contatos(
            mensagem.conversa.contato_telefone, cartoes, citando=citando or '',
            numero=mensagem.conversa.numero,
        )
        _marcar_enviada(mensagem, resposta)
    except Exception as exc:
        _marcar_falha(mensagem, exc, 'Falha ao enviar contato do WhatsApp')


@shared_task
def notificar_andamento_tarefa(tarefa_id: int):
    """
    Avisa o cliente que a tarefa nascida do atendimento dele mudou de andamento.

    Enfileirada pelo signal em `kanban/signals.py`, já depois do commit — a
    decisão de o que mandar (texto livre ou template) fica em `services`, aqui só
    o que depende de I/O e do estado atual do banco.

    A tarefa é relida em vez de receber os dados por parâmetro: entre o commit e a
    execução ela pode ter sido movida de novo, e o que interessa ao cliente é onde
    ela está agora, não o passo intermediário que disparou a fila.
    """
    from kanban.models import KanbanTask

    tarefa = (
        KanbanTask.objects
        .select_related('conversa_whatsapp', 'coluna')
        .filter(pk=tarefa_id)
        .first()
    )
    # Apagada, desvinculada ou com o aviso desligado entre o commit e agora.
    if tarefa is None or tarefa.conversa_whatsapp is None or not tarefa.notificar_whatsapp:
        return

    andamento = 'Concluída' if tarefa.concluido_em else tarefa.coluna.titulo
    services.avisar_andamento_tarefa(tarefa.conversa_whatsapp, tarefa.titulo, andamento)


# ── Disparo em massa ─────────────────────────────────────────────────────────
# Teto e ritmo ficam em settings para se ajustarem sem deploy: o limite da Meta
# sobe sozinho conforme a qualidade do número (250 -> 2.000 -> 10.000...), e
# descobrir isso num dia de convocação não é hora de mexer em código.
_TETO_24H_PADRAO = 250
_PAUSA_ENTRE_ENVIOS = 0.25  # 4 por segundo; o teto da Meta é 20/s


def _teto_24h() -> int:
    return int(getattr(settings, 'WHATSAPP_TETO_DESTINATARIOS_24H', _TETO_24H_PADRAO))


def _enviados_nas_ultimas_24h(numero) -> int:
    """
    Quantos destinatários ÚNICOS este número já alcançou nas últimas 24h.

    Conta por telefone distinto, e não por mensagem, porque é assim que a Meta
    conta: três avisos para a mesma pessoa gastam uma vaga, não três.
    """
    desde = timezone.now() - timedelta(hours=24)
    return (DisparoDestinatario.objects
            .filter(disparo__numero=numero, status='ENVIADO', enviado_em__gte=desde)
            .values('telefone').distinct().count())


def _conversa_para_disparo(destinatario, disparo):
    """
    A conversa onde a mensagem do disparo entra.

    Reaproveita a conversa aberta do contato em vez de criar outra: quem receber
    o aviso e responder deve continuar o mesmo histórico, e não abrir um
    atendimento paralelo. Conversa nova nasce EM_ATENDIMENTO porque fomos nós que
    puxamos o assunto — mandar o menu de setores depois seria absurdo.
    """
    # Pelo par (telefone, número), e por todas as formas do telefone: um aviso do
    # RH não deve entrar na conversa que a pessoa tem aberta com a TI, e o
    # telefone da agenda quase nunca está escrito como a Meta o devolve.
    conversa = (Conversa.objects
                .filter(services.filtro_telefone(destinatario.telefone), status='ABERTA')
                .filter(Q(numero=disparo.numero) | Q(numero__isnull=True))
                .order_by('-created_at').first())
    if conversa is not None:
        return conversa
    return Conversa.objects.create(
        contato_telefone=destinatario.telefone,
        contato_nome=destinatario.nome or '',
        numero=disparo.numero,
        fila=disparo.numero.fila_padrao(),
        estado_menu='EM_ATENDIMENTO',
    )


@shared_task
def processar_disparo(disparo_id: int):
    """
    Entrega o disparo, um destinatário por vez, e para quando bate o teto.

    Sequencial de propósito: paralelizar aqui só adiantaria a hora de estourar o
    limite da Meta, e um número que estoura tem a qualidade rebaixada — o que
    encarece e atrasa TODOS os envios seguintes, inclusive o atendimento normal.

    Reentrante: só olha para os PENDENTES, então continuar um disparo pausado é
    chamar a task de novo. É isso que permite retomar no dia seguinte, quando o
    teto de 24h zera.
    """
    disparo = Disparo.objects.select_related('numero').get(id=disparo_id)
    if disparo.status in ('CONCLUIDO', 'CANCELADO'):
        return

    disparo.status = 'ENVIANDO'
    disparo.detalhe_status = ''
    if disparo.iniciado_em is None:
        disparo.iniciado_em = timezone.now()
    disparo.save(update_fields=['status', 'detalhe_status', 'iniciado_em'])

    teto = _teto_24h()
    pendentes = list(disparo.destinatarios.filter(status='PENDENTE').order_by('id'))

    for destinatario in pendentes:
        # Relido a cada volta: é assim que Cancelar/Pausar na tela interrompe um
        # disparo já em andamento, sem precisar revogar a task no Celery.
        disparo.refresh_from_db(fields=['status'])
        if disparo.status in ('CANCELADO', 'PAUSADO'):
            logger.info('Disparo %s interrompido (%s)', disparo.id, disparo.status)
            return

        if _enviados_nas_ultimas_24h(disparo.numero) >= teto:
            disparo.status = 'PAUSADO'
            disparo.detalhe_status = (
                f'Teto de {teto} destinatários em 24h atingido. '
                f'Continue amanhã: os pendentes seguem na fila.'
            )
            disparo.save(update_fields=['status', 'detalhe_status'])
            logger.warning('Disparo %s pausado no teto de 24h', disparo.id)
            return

        conversa = _conversa_para_disparo(destinatario, disparo)
        mensagem = Mensagem.objects.create(
            conversa=conversa,
            direcao='SAIDA',
            tipo='TEXTO',
            autor=disparo.criado_por,
            texto=disparo.previa or f'[template: {disparo.template_nome}]',
            template_nome=disparo.template_nome,
            status_entrega='PENDENTE',
            payload_bruto={'disparo': disparo.id, 'template': disparo.template_nome},
        )
        destinatario.mensagem = mensagem

        try:
            resposta = graph_api.enviar_template(
                destinatario.telefone, disparo.template_nome, disparo.idioma,
                disparo.componentes, numero=disparo.numero,
            )
            _marcar_enviada(mensagem, resposta)
            destinatario.status = 'ENVIADO'
            destinatario.erro = ''
            destinatario.enviado_em = timezone.now()
            conversa.ultima_mensagem_em = destinatario.enviado_em
            conversa.save(update_fields=['ultima_mensagem_em'])
        except Exception as exc:
            _marcar_falha(mensagem, exc, 'Falha ao enviar destinatário de disparo')
            destinatario.status = 'FALHA'
            # Truncado porque o detalhe da Meta é longo e o campo é de tela: o
            # texto inteiro continua em `Mensagem.erro_detalhe`.
            destinatario.erro = graph_api.detalhe_do_erro(exc)[:255]
        destinatario.save(update_fields=['status', 'erro', 'enviado_em', 'mensagem'])

        time.sleep(_PAUSA_ENTRE_ENVIOS)

    disparo.refresh_from_db(fields=['status'])
    if disparo.status == 'ENVIANDO':
        disparo.status = 'CONCLUIDO'
        disparo.concluido_em = timezone.now()
        disparo.detalhe_status = ''
        disparo.save(update_fields=['status', 'concluido_em', 'detalhe_status'])
