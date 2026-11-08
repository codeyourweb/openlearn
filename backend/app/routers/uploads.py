# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Image upload for question media and wiki illustrations.

Uploads are treated as hostile input: size capped, decoded by Pillow, checked
against an allowlist of pixel formats and re-encoded from scratch (which drops
EXIF, embedded scripts and any polyglot payload).
"""

from __future__ import annotations

import io
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from PIL import Image, UnidentifiedImageError

from ..config import settings
from ..deps import enforce_rate_limit, require_user
from ..models import User

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])

ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
MAX_QUESTION_DIMENSION = 1600
# A wiki illustration may be a diagram or a screenshot: keep more pixels, but
# still re-encode, so the stored file never carries the original metadata.
MAX_WIKI_DIMENSION = 2400


def _store_image(raw: bytes, *, max_dimension: int) -> dict[str, object]:
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
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        # Pillow reports a truncated or corrupted file as SyntaxError; a broken
        # upload is a bad request, never a 500.
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


async def _read_upload(file: UploadFile) -> bytes:
    raw = await file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        limit_mb = max(1, settings.max_upload_bytes // (1024 * 1024))
        raise HTTPException(status_code=413, detail=f"File is larger than {limit_mb} MB.")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")
    return raw


@router.post("/question-image", status_code=status.HTTP_201_CREATED)
async def upload_question_image(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_user),
):
    enforce_rate_limit(request, "uploads", 30, 60)
    payload = await _read_upload(file)
    return _store_image(payload, max_dimension=MAX_QUESTION_DIMENSION)


@router.post("/image", status_code=status.HTTP_201_CREATED)
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_user),
):
    """Wiki illustrations: same hardening, a larger canvas."""
    enforce_rate_limit(request, "uploads", 30, 60)
    payload = await _read_upload(file)
    return _store_image(payload, max_dimension=MAX_WIKI_DIMENSION)
