# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Shared image storage: decode, re-encode, write.

Every image that enters the platform goes through here — question illustrations,
wiki pictures, and pictures found inside an imported archive. Uploads are treated
as hostile: size is capped by the caller, Pillow decodes the bytes, the format is
checked against an allowlist, and the file is re-encoded from scratch, which drops
EXIF, embedded scripts and any polyglot payload.
"""

from __future__ import annotations

import io
import secrets

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from .config import settings

ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
MAX_QUESTION_DIMENSION = 1600
# A wiki illustration may be a diagram or a screenshot: keep more pixels, but
# still re-encode, so the stored file never carries the original metadata.
MAX_WIKI_DIMENSION = 2400


def store_image(raw: bytes, *, max_dimension: int = MAX_QUESTION_DIMENSION) -> dict[str, object]:
    if not raw:
        raise HTTPException(status_code=422, detail="The image is empty.")
    Image.MAX_IMAGE_PIXELS = 40_000_000
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise HTTPException(
                    status_code=415, detail="Unsupported image format (PNG, JPEG, WEBP, GIF)."
                )
            image = image.convert("RGBA" if image.mode in {"RGBA", "LA", "P"} else "RGB")
            image.thumbnail((max_dimension, max_dimension))
            buffer = io.BytesIO()
            image.save(buffer, format="WEBP", quality=82, method=4)
            payload = buffer.getvalue()
            width, height = image.size
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=415, detail="The file is not a valid image.") from exc

    settings.media_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_hex(16)}.webp"
    (settings.media_dir / filename).write_bytes(payload)
    return {
        "path": f"/media/{filename}",
        "width": width,
        "height": height,
        "bytes": len(payload),
    }
