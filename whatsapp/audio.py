"""
Preparo do áudio para a Cloud API.

O gravador do navegador não produz nada que a Meta aceite: o Chrome grava em
`audio/webm;codecs=opus` e a lista de tipos suportados em `type: audio` não tem
webm — a mensagem inteira é recusada, não só o arquivo. O conteúdo já é Opus; o
que está errado é o empacotamento. Daí a conversão para ogg/opus aqui, antes do
upload.
"""
import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Tipos que a Meta aceita como áudio e que, portanto, sobem sem passar por
# conversão nenhuma.
#
# `audio/ogg` fica de fora de propósito, mesmo sendo aceito: a Meta só admite ogg
# com codec Opus, e o tipo MIME do contêiner não diz qual codec tem dentro. Um
# ogg/vorbis passaria por aqui e quebraria só lá na frente, com erro da Meta.
# Reconverter um ogg que já era Opus custa poucos milissegundos.
FORMATOS_ACEITOS = {'audio/aac', 'audio/amr', 'audio/mpeg', 'audio/mp4'}

MIME_CONVERTIDO = 'audio/ogg'
EXTENSAO_CONVERTIDA = '.ogg'
TIMEOUT_CONVERSAO = 60


class FfmpegIndisponivel(Exception):
    """ffmpeg não está instalado no servidor."""


class FalhaNaConversao(Exception):
    """O ffmpeg rodou mas não devolveu áudio utilizável."""


def _normalizar(mime: str) -> str:
    return (mime or '').lower().split(';')[0].strip()


def precisa_converter(mime: str) -> bool:
    return _normalizar(mime) not in FORMATOS_ACEITOS


def converter_para_opus(conteudo: bytes) -> bytes:
    """
    Converte qualquer áudio para ogg/opus mono, 32 kbps — a mesma faixa que o
    próprio WhatsApp usa em mensagem de voz.

    A entrada vai por arquivo temporário, e não por `pipe:0`: contêiner com índice
    no fim (mp4/mov) exige que o ffmpeg volte no arquivo, e um pipe não permite
    voltar. A saída pode ficar no pipe porque ogg é sequencial.
    """
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise FfmpegIndisponivel(
            'ffmpeg não está instalado no servidor; sem ele o áudio não pode ser '
            'convertido para o formato que o WhatsApp aceita.'
        )

    entrada = tempfile.NamedTemporaryFile(suffix='.entrada', delete=False)
    try:
        entrada.write(conteudo)
        entrada.close()
        processo = subprocess.run(
            [
                ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
                '-i', entrada.name,
                '-vn',                      # descarta capa/arte embutida
                '-map_metadata', '-1',      # nome de arquivo e tags não vão junto
                '-ac', '1', '-ar', '48000', # opus é 48kHz; mono basta para voz
                '-c:a', 'libopus', '-b:a', '32k',
                '-f', 'ogg', 'pipe:1',
            ],
            input=b'',
            capture_output=True,
            timeout=TIMEOUT_CONVERSAO,
        )
    finally:
        try:
            os.unlink(entrada.name)
        except OSError:
            pass

    if processo.returncode != 0 or not processo.stdout:
        detalhe = (processo.stderr or b'').decode('utf-8', 'replace').strip()[:300]
        raise FalhaNaConversao(f'Não foi possível converter o áudio. {detalhe}'.strip())
    return processo.stdout


def preparar_para_whatsapp(conteudo: bytes, mime: str, nome: str) -> tuple[bytes, str, str]:
    """
    Devolve `(conteúdo, mime, nome)` prontos para o upload.

    Áudio já em formato aceito passa direto — não faz sentido recodificar um mp3
    que o atendente anexou e perder qualidade à toa.
    """
    if not precisa_converter(mime):
        return conteudo, _normalizar(mime), nome

    convertido = converter_para_opus(conteudo)
    base = os.path.splitext(nome or 'audio')[0] or 'audio'
    logger.info('Áudio convertido de %s para ogg/opus (%d KB)', mime, len(convertido) // 1024)
    return convertido, MIME_CONVERTIDO, f'{base}{EXTENSAO_CONVERTIDA}'
