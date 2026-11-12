# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
# Qwen3-TTS on CPU. The CUDA wheel would add ~2 GiB of libraries this box can
# never use, so torch and torchaudio come from the CPU index explicitly.
#
# They must be installed as a matched pair: pip resolves torchaudio from PyPI by
# default, which is built against CUDA, and the CPU torch then fails to load
# _torchaudio.so at import time. Pinning both here is what keeps them aligned.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    PIP_NO_CACHE_DIR=1

# libsndfile1 is what soundfile loads; nothing else is needed at the system level.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 sox libsox-fmt-all \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --index-url https://download.pytorch.org/whl/cpu \
        torch==2.11.0 torchaudio==2.11.0 \
    && python -m pip install -r /app/requirements.txt

COPY app.py /app/app.py

# Without this, uvicorn starts in / and the /app directory shadows app.py as a
# namespace package: "Attribute app not found in module app".
WORKDIR /app

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
