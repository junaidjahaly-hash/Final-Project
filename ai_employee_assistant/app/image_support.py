import base64
import io
import warnings

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


def prepare_image(content: bytes) -> str:
    """Validate an attachment and normalize it to a bounded PNG for the model."""
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError('Choose an image smaller than 8 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {'PNG', 'JPEG', 'WEBP'}:
                    raise ValueError('Only PNG, JPEG, and WebP images are supported.')
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError('Choose an image with fewer than 20 million pixels.')
                image.load()
                image.thumbnail((2048, 2048))
                output = io.BytesIO()
                image.convert('RGB').save(output, format='PNG')
                return base64.b64encode(output.getvalue()).decode('ascii')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('This image could not be read. Try another PNG, JPEG, or WebP file.') from exc
