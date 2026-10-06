from io import BytesIO

from PIL import Image


def make_image(fmt="PNG", size=(64, 48), color=(200, 50, 50), mode="RGB", exif=None) -> bytes:
    img = Image.new(mode, size, color if mode == "RGB" else (*color, 128))
    out = BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(out, format=fmt, **kwargs)
    return out.getvalue()
