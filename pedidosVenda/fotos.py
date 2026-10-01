"""Redimensiona a foto enviada: uma versão para ampliar e uma miniatura para a lista."""
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

LADO_IMAGEM = 1200
LADO_MINIATURA = 240


class FotoInvalida(ValueError):
    pass


def _jpeg(img: Image.Image, lado: int, qualidade: int) -> bytes:
    copia = img.copy()
    copia.thumbnail((lado, lado), Image.LANCZOS)
    buf = BytesIO()
    copia.save(buf, format='JPEG', quality=qualidade, optimize=True, progressive=True)
    return buf.getvalue()


def processar(arquivo) -> tuple[ContentFile, ContentFile]:
    try:
        img = Image.open(arquivo)
        # Foto de celular vem deitada sem isto: a rotação está só no EXIF.
        img = ImageOps.exif_transpose(img)
    except Exception as exc:
        raise FotoInvalida('Arquivo não é uma imagem que eu consiga abrir.') from exc
    if img.mode in ('RGBA', 'LA', 'P'):
        # Fundo branco no lugar da transparência: JPEG não tem canal alfa.
        img = img.convert('RGBA')
        fundo = Image.new('RGB', img.size, (255, 255, 255))
        fundo.paste(img, mask=img.split()[-1])
        img = fundo
    else:
        img = img.convert('RGB')
    nome = uuid.uuid4().hex
    return (
        ContentFile(_jpeg(img, LADO_IMAGEM, 85), name=f'{nome}.jpg'),
        ContentFile(_jpeg(img, LADO_MINIATURA, 80), name=f'{nome}_mini.jpg'),
    )
