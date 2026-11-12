# Qwen3-TTS, CPU edition

A speech service for OpenLearn that runs without a GPU.

The upstream container (`k8bit/qwen3-tts`) is built around `device_map="cuda:0"`
and refuses to start without `--gpus all`. This directory wraps the same model in
the same HTTP surface — `POST /v1/audio/speech`, `GET /v1/audio/voices`,
`GET /health` — but loads it on CPU, so a small instance can produce audio.

## Build and run

```bash
docker build -t qwen-tts-cpu:local .
docker run -d --name qwen-tts --restart unless-stopped \
  -m 9g --cpus 6 \
  -e TTS_THREADS=6 \
  -v /srv/qwen-tts-models:/models \
  -p 127.0.0.1:8021:8000 \
  qwen-tts-cpu:local
```

The first start downloads ≈1.2 GB of weights into `/models`; later starts load in
about 25 seconds. Do not publish the port beyond the loopback or the Docker
network: the service has no authentication, and it should never be reachable from
outside.

Then let OpenLearn talk to it over the shared network:

```bash
docker network connect <openlearn_network> qwen-tts
# OL_AUDIO_SERVICE_URL=http://qwen-tts:8000
# OL_AUDIO_ENABLED=true
```

## Request

```bash
curl -s http://127.0.0.1:8021/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"Bonjour, ceci est un test.","voice":"Serena","language":"fr","response_format":"mp3"}' \
  --output test.mp3
```

| Field | Meaning |
|---|---|
| `input` | Text to read. Refused above `TTS_MAX_CHARS` (default 4 000). |
| `voice` | One of the nine timbres below. |
| `language` | `zh`, `en`, `ja`, `ko`, `de`, `fr`, `ru`, `pt`, `es`, `it`, or `Auto`. |
| `response_format` | `mp3` (default) or `wav`. |
| `instruct` | Optional style hint, in words (“Speak slowly”). |

The response carries `X-Audio-Seconds`, which OpenLearn uses to size the player.
Without it the application falls back to an estimate from the file size.

## Voices and languages

| Timbre | Native language |
|---|---|
| Vivian, Serena | Chinese |
| Uncle_Fu, Dylan, Eric | Chinese |
| Ryan, Aiden | English |
| Ono_Anna | Japanese |
| Sohee | Korean |

The model is multilingual: these timbres read the other languages too, with an
accent. There is no native French, German, Spanish, Italian, Portuguese or Russian
timbre in this checkpoint — that is a property of the model, not of this wrapper.
Hindi, Bengali and Arabic are not supported at all and are refused rather than
read out in the wrong language.

## Performance

Measured on 8 vCPU, float32, `TTS_THREADS=6`:

| Text | Audio | CPU | Ratio |
|---|---|---|---|
| 410 characters | 26.7 s | 99 s | 0.27 |

MP3 at 64 kbit/s mono: about 8 KiB per second, 470 KiB per minute. Synthesis is
serialised behind a lock — two models decoding at once on CPU would both crawl.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TTS_MODEL` | `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` | Hugging Face id or local path. |
| `TTS_THREADS` | `6` | Torch threads. |
| `TTS_MAX_CHARS` | `4000` | Refuse longer inputs. |
| `TTS_BITRATE` | `64` | MP3 bitrate, kbit/s. |
| `TTS_DTYPE` | `float32` | `bfloat16` is smaller but not faster on CPU. |
| `HF_HOME` | `/models` | Model cache; mount it as a volume. |

The 1.7B checkpoints are about three times larger and need ≈6 GB of RAM; they buy
a slightly more natural voice at roughly three times the CPU per sentence.

## Licence

Qwen3-TTS weights are Apache-2.0. This wrapper is AGPL-3.0-only, like the rest of
the project.
