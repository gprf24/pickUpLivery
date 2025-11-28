# app/core/image_utils.py
from __future__ import annotations

from io import BytesIO
from typing import Tuple

from fastapi import UploadFile
from PIL import Image, ImageOps  # <-- добавили ImageOps


def compress_image(
    file: UploadFile,
    *,
    max_size_px: int = 1600,
    quality: int = 80,
) -> Tuple[bytes, str]:
    """
    Compress an uploaded image to a reasonable size and JPEG format.

    - Works for any common input format (JPEG/PNG/HEIC/WebP, etc.) as long as Pillow supports it.
    - Resizes so that the longest side <= max_size_px.
    - Re-encodes as JPEG with given quality.
    - Applies EXIF orientation (so photos from phones are not rotated incorrectly).
    """

    # Move cursor to start (in case somebody already read from the file)
    file.file.seek(0)

    # Open with Pillow (it will handle different formats)
    img = Image.open(file.file)

    # 🔧 Fix orientation according to EXIF (common for phone photos)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        # If EXIF is missing or broken, just ignore and continue
        pass

    # Convert to RGB (drops alpha channel if present)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Resize preserving aspect ratio
    img.thumbnail((max_size_px, max_size_px))

    # Save to buffer as JPEG with compression
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    compressed_bytes = buf.getvalue()

    # We'll serve everything as JPEG
    content_type = "image/jpeg"

    return compressed_bytes, content_type
