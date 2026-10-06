from io import BytesIO

import pytest
from PIL import Image

from app import images
from app.images import ImageRejected, process
from tests.helpers import make_image


def open_out(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_supported_formats_become_jpeg(fmt):
    out, w, h = process(make_image(fmt))
    img = open_out(out)
    assert img.format == "JPEG" and img.mode == "RGB"
    assert (w, h) == img.size == (64, 48)


def test_transparent_png_is_flattened_to_rgb():
    out, _, _ = process(make_image("PNG", mode="RGBA"))
    assert open_out(out).mode == "RGB"


def test_large_photo_is_shrunk_keeping_aspect_ratio():
    out, w, h = process(make_image("JPEG", size=(4000, 3000)))
    assert (w, h) == (1600, 1200)


def test_exif_including_location_is_stripped():
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x010E] = "my home address"  # ImageDescription
    exif[0x8825] = {2: (32.0, 42.0, 0.0)}  # GPSInfo latitude
    src = make_image("JPEG", exif=exif.tobytes())
    assert open_out(src).getexif()  # the source really has EXIF
    out, _, _ = process(src)
    assert not open_out(out).getexif()
    assert "exif" not in open_out(out).info


def test_exif_rotation_is_applied_before_stripping():
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 degrees
    out, w, h = process(make_image("JPEG", size=(200, 100), exif=exif.tobytes()))
    assert (w, h) == (100, 200)


@pytest.mark.parametrize(
    "raw",
    [b"just some text", b"%PDF-1.4 fake", make_image("GIF"), make_image("JPEG")[:200], b""],
)
def test_non_images_unsupported_and_broken_files_are_rejected(raw):
    with pytest.raises(ImageRejected):
        process(raw)


def test_huge_dimensions_rejected_before_decoding(monkeypatch):
    monkeypatch.setattr(images, "MAX_PIXELS", 100)
    with pytest.raises(ImageRejected, match="too large"):
        process(make_image("PNG", size=(20, 20)))
