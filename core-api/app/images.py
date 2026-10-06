"""Validate and normalize uploaded photos.

Every upload is decoded and re-encoded as JPEG, which:
- rejects anything that is not really a JPEG, PNG or WebP image (whatever its name says),
- strips EXIF metadata, including the GPS location phones embed in photos,
- applies the EXIF rotation first so the photo stays upright,
- shrinks large photos so storage and AI calls stay small.
"""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PIXELS = 40_000_000  # refuse "decompression bombs" before decoding them
MAX_SIDE = 1600
JPEG_QUALITY = 85


class ImageRejected(ValueError):
    pass


def process(raw: bytes) -> tuple[bytes, int, int]:
    """Return (jpeg_bytes, width, height) or raise ImageRejected."""
    try:
        img = Image.open(BytesIO(raw))
        if img.format not in ALLOWED_FORMATS:
            raise ImageRejected("Only JPEG, PNG and WebP photos are supported")
        width, height = img.size
        if width * height > MAX_PIXELS:
            raise ImageRejected("Photo dimensions are too large")
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = BytesIO()
        img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)  # no exif= : stripped
        return out.getvalue(), img.width, img.height
    except ImageRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise ImageRejected("The file is not a valid image") from e
