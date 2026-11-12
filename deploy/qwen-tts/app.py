# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Qwen3-TTS speech service with an OpenAI-shaped surface.

The upstream container (k8bit/qwen3-tts) hardcodes ``cuda:0``; this one runs on
CPU so an instance without a GPU can still produce audio. It exposes the same
``POST /v1/audio/speech`` the application already knows, which means swapping
this service for a GPU deployment later is a matter of changing a URL.

One sentence at a time: synthesis is serialised behind a lock, because a small
box cannot afford two 0.6B models decoding in parallel.

Config (environment):
  TTS_MODEL      Hugging Face id, default the 0.6B CustomVoice checkpoint
  TTS_THREADS    torch threads, default 6
  TTS_MAX_CHARS  refused above this, default 4000
  TTS_BITRATE    MP3 bitrate, default 64 (kbit/s)
  HF_HOME        model cache, mount it as a volume
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time

import lameenc
import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

LOG = logging.getLogger("qwen-tts")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MODEL_ID = os.getenv("TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
THREADS = int(os.getenv("TTS_THREADS", "6"))
MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "4000"))
BITRATE = int(os.getenv("TTS_BITRATE", "64"))
DTYPE = os.getenv("TTS_DTYPE", "float32")

# The nine timbres of the CustomVoice checkpoint, with the language each one was
# recorded in. Qwen recommends the native language, but these voices do read the
# other eight; the accent is the trade-off of a model this small.
SPEAKERS = {
    "Vivian": "Chinese",
    "Serena": "Chinese",
    "Uncle_Fu": "Chinese",
    "Dylan": "Chinese",
    "Eric": "Chinese",
    "Ryan": "English",
    "Aiden": "English",
    "Ono_Anna": "Japanese",
    "Sohee": "Korean",
}

# The nine languages the checkpoint actually supports. Hindi, Bengali and Arabic
# are absent from the model, so they are absent here too: a request for them is
# refused instead of being read out in the wrong language.
LANGUAGES = {
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "ru": "Russian",
    "pt": "Portuguese",
    "es": "Spanish",
    "it": "Italian",
}

app = FastAPI(title="Qwen3-TTS", version="1.0")

_model = None
_lock = threading.Lock()
_started_at = time.time()


class SpeechRequest(BaseModel):
    model: str | None = None
    input: str = Field(min_length=1)
    voice: str = "Serena"
    language: str | None = None
    response_format: str = "mp3"
    instruct: str | None = None


@app.on_event("startup")
def load_model() -> None:
    from qwen_tts import Qwen3TTSModel

    torch.set_num_threads(THREADS)
    dtype = {"float32": torch.float32, "bfloat16": torch.bfloat16}.get(DTYPE, torch.float32)
    LOG.info("loading %s on cpu (%s, %d threads)", MODEL_ID, DTYPE, THREADS)
    started = time.time()
    global _model
    _model = Qwen3TTSModel.from_pretrained(
        MODEL_ID,
        device_map="cpu",
        dtype=dtype,
        attn_implementation="sdpa",
    )
    LOG.info("model ready in %.1fs", time.time() - started)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok" if _model is not None else "loading",
        "model": MODEL_ID,
        "device": "cpu",
        "threads": THREADS,
        "uptime": round(time.time() - _started_at, 1),
    }


@app.get("/v1/audio/voices")
def voices() -> dict[str, object]:
    return {"voices": [{"name": name, "native": lang} for name, lang in SPEAKERS.items()]}


def _encode_mp3(samples: np.ndarray, rate: int) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype("<i2")
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(BITRATE)
    encoder.set_in_sample_rate(rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    return bytes(encoder.encode(pcm16.tobytes()) + encoder.flush())


@app.post("/v1/audio/speech")
def speech(body: SpeechRequest) -> Response:
    if _model is None:
        raise HTTPException(status_code=503, detail="The model is still loading.")
    text = body.input.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Empty input.")
    if len(text) > MAX_CHARS:
        raise HTTPException(
            status_code=413, detail=f"Input is longer than {MAX_CHARS} characters ({len(text)})."
        )
    speaker = SPEAKERS.get(body.voice)
    if speaker is None:
        raise HTTPException(status_code=422, detail=f"Unknown voice '{body.voice}'.")
    language = body.language or "Auto"
    if language != "Auto":
        language = LANGUAGES.get(language.lower(), language)
        if language not in LANGUAGES.values():
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported language '{body.language}'. Known: {', '.join(LANGUAGES.values())}.",
            )

    started = time.time()
    with _lock:
        wavs, rate = _model.generate_custom_voice(
            text=text,
            language=language,
            speaker=body.voice,
            instruct=body.instruct or "",
        )
    samples = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
    seconds = len(samples) / float(rate)
    elapsed = time.time() - started
    # RTF: audio seconds produced per second of CPU. Above 1 is faster than
    # real time; the application's chunking is sized from this number.
    LOG.info(
        "synth %d chars -> %.1fs audio in %.1fs (rtf %.2f, %.1f KiB)",
        len(text), seconds, elapsed, seconds / elapsed if elapsed else 0.0, 0.0,
    )

    if body.response_format == "wav":
        buffer = io.BytesIO()
        sf.write(buffer, samples, rate, format="WAV", subtype="PCM_16")
        return Response(content=buffer.getvalue(), media_type="audio/wav")

    payload = _encode_mp3(samples, rate)
    LOG.info("mp3 %d KiB", len(payload) // 1024)
    return Response(content=payload, media_type="audio/mpeg", headers={"X-Audio-Seconds": f"{seconds:.2f}"})
