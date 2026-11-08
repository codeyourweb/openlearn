# syntax=docker/dockerfile:1
FROM python:3.12-slim

LABEL org.opencontainers.image.title="OpenLearn" \
      org.opencontainers.image.description="Free, open source knowledge platform: wiki, quizzes, revision cards, branching stories." \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.source="https://github.com/codeyourweb/openlearn"
# AGPL section 13: anyone offering this image as a service must be able to hand
# the corresponding source to its users.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OL_DATABASE_URL=sqlite:////app/data/openlearn.db \
    OL_MEDIA_DIR=/app/data/media

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
# DejaVu keeps Cyrillic, Greek and Hebrew glyphs in exported PDFs; ReportLab's
# built-in fonts stop at Latin-1.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-dejavu-extra \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend
COPY docs /app/docs
# The runtime user reads the Markdown guide; keep it world-readable.
RUN chmod -R a+rX /app/docs
# The demo catalogue is data, not code: an instance started with
# OL_DEMO_MODE=1 reads it, every other instance ignores it.
COPY demo /app/demo
COPY serve.sh /app/serve.sh
COPY healthcheck.py /app/healthcheck.py
# The AGPL is a licence you have to be able to read from the running image.
COPY LICENSE NOTICE /app/

RUN chmod -R a+rX /app/backend /app/frontend /app/demo \
    && chmod 755 /app/serve.sh \
    && chmod 644 /app/healthcheck.py \
    && chmod 644 /app/LICENSE /app/NOTICE \
    && useradd --system --uid 10001 --create-home quiz \
    && mkdir -p /app/data/media \
    && chown -R quiz:quiz /app/data

USER quiz

EXPOSE 8000 8443

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

CMD ["/app/serve.sh"]
