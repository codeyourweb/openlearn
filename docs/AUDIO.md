# Audio transcripts

OpenLearn can read a wiki page or a scene of an adventure aloud. A plain
questionnaire has no transcript: it is a sequence of questions, not prose, and a
voice reading it adds nothing to the screen.
The audio is made **when the author asks for it**, once, and stored; a reader who
presses play waits for nothing.

This is a separate switch from AI assistance: a speech engine is a local service,
not a model provider, and an instance can have one without the other.

## Why it is generated at editing time

A page of 6 000 characters takes about four minutes of speech. Synthesising that
while a reader waits would be the slowest page in the application. Generating it
from the editor moves the cost to the one moment when waiting is acceptable — and
the result is cached, so a second reader pays nothing.

The consequence is a rule worth knowing: **an edited document stops serving its
transcript**. A rendition is stored with the hash of the script it was made from;
if the text changed, the player disappears until someone regenerates it. Nobody
ever hears a text that is no longer on the page.

## What is read, and what is not

The script is built from the saved content, never from the text currently in an
editor textarea:

| Read aloud | Ignored |
|---|---|
| Titles (as sentences, so the voice pauses) | Code blocks |
| Paragraphs | Tables |
| List items, one by one | Image captions and alt text |
| Question prompts and their options | Raw URLs |
| Scene text of an adventure | Footnote markers, HTML tags |

Only the document's own language is spoken: a French wiki reads in French even
when the interface is in Japanese. The nine languages supported are the ones the
shipped engine can pronounce:

`en`, `fr`, `de`, `es`, `it`, `pt`, `ru`, `zh`, `ja`

Hindi, Bengali and Arabic are **not** covered by the Qwen3-TTS checkpoint. On an
instance that needs them, point `OL_AUDIO_SERVICE_URL` at another engine and add
the codes to `OL_AUDIO_LANGUAGES`; the interface follows the list, so a language
without a voice simply does not offer the button.

## Configuration

All of it is environment; nothing is configured from the browser.

| Variable | Default | Meaning |
|---|---|---|
| `OL_AUDIO_ENABLED` | `false` | Master switch. Off means no button, no endpoint, no player. |
| `OL_AUDIO_SERVICE_URL` | *(empty)* | Base URL of the speech service. `/v1/audio/speech` is appended. |
| `OL_AUDIO_MODEL` | `qwen3-tts` | Model name sent to the service; part of the cache key. |
| `OL_AUDIO_TIMEOUT_SECONDS` | `1800` | Per-segment timeout. A CPU box needs minutes per paragraph. |
| `OL_AUDIO_CONCURRENCY` | `1` | Segments synthesised at once. One, on purpose. |
| `OL_AUDIO_VOICE_FEMALE` | `Serena` | Voice name for “female”, as the engine spells it. |
| `OL_AUDIO_VOICE_MALE` | `Aiden` | Voice name for “male”. |
| `OL_AUDIO_MAX_CHARS` | `12000` | Refused above this. 1 000 characters ≈ 4 minutes of CPU. |
| `OL_AUDIO_CHUNK_CHARS` | `900` | Size of one request, about a minute of audio. |
| `OL_AUDIO_LANGUAGES` | nine codes above | What the engine can speak here. |

```bash
OL_AUDIO_ENABLED=true
OL_AUDIO_SERVICE_URL=http://qwen-tts:8000
```

The voices are the engine's names, not ours: swapping engines renames two
settings, and no code changes.

## The service

`deploy/qwen-tts/` ships a CPU-capable container that exposes the same shape as
the OpenAI speech endpoint, so an instance with a GPU can use the upstream
container instead without touching the application.

```bash
docker build -t qwen-tts-cpu:local deploy/qwen-tts
docker run -d --name qwen-tts --restart unless-stopped \
  -m 9g --cpus 6 -e TTS_THREADS=6 \
  -v /srv/qwen-tts-models:/models \
  -p 127.0.0.1:8021:8000 qwen-tts-cpu:local
```

Then put `qwen-tts` on the same Docker network as the application and set
`OL_AUDIO_SERVICE_URL=http://qwen-tts:8000`.

Measured on eight cores with no GPU, in float32, on the same 306-character
French paragraph:

| Model | Audio produced | CPU time | Real-time factor |
|---|---|---|---|
| 0.6B CustomVoice | 18.5 s | 68 s | 0.27 |
| 1.7B CustomVoice | 18.5 s | 131 s | 0.43 |

The 1.7B checkpoint is the default: the extra CPU buys a clearly steadier
reading. Budget about seven minutes per 1 000 characters, and roughly 85 minutes
for a 12 000-character document — allowed, and the job queue is why it blocks
nothing. Switch back to the 0.6B with `TTS_MODEL` if the machine is short on
cores.

## One portion at a time

A transcript belongs to **one page or one scene**, never to a whole story. The
author controls it from the document itself:

- nothing yet → “Create the transcript”, with the choice of a female or a male
  voice **and a narrator tone**, an estimate of the audio length and of the CPU
  time, and a progress bar that follows the job;
- ready → “Transcript ready · 0:42”, then *Listen*, *Make it again* and *Remove*;
- unavailable → the block is not rendered at all.

### The estimate and the bar

The estimate is arithmetic: the character count, read at roughly 15 characters
per second of audio, on a processor that runs about a quarter of real time. It
answers "may I go and make coffee?" before anything is spent.

The bar answers something else — what the engine is actually doing. Every
portion committed updates the job's `progress`, so the bar advances portion by
portion: a scene is one step, a long page moves several times. Until the first
portion is measured the bar travels rather than inventing a percentage, and it
is a `role="progressbar"` with `aria-valuenow`, so a screen reader hears the
advance instead of silence.

### The narrator tone

Four readings of the same paragraph:

| Tone | Sent to the engine as |
| --- | --- |
| `neutral` | nothing: the engine's own reading |
| `formal` | “a calm, precise, professional tone, as in a lecture or a briefing” |
| `warm` | “a warm, kind, unhurried tone, as if explaining to someone you care about” |
| `lively` | “energy and enthusiasm, lively but still clear and articulate” |

A reference page and a children's adventure do not read the same way, so the
tone is chosen per transcript, shown beside the duration, and kept when *Make it
again* is pressed. It is part of the cache key: asking for the same paragraph in
a warmer voice is a second recording, never the neutral one replayed.

*Make it again* replaces the previous rendition for the same voice, **tone** and
language, so an author who dislikes a reading never ends up with two versions of
it. *Remove* deletes the rendition **and the cached pieces nothing else uses**:
the player disappears from the page and the next request really synthesises
again. (Removing the row alone used to leave the segments in place, so asking
again answered from the cache in a fraction of a second — the recording the
author had just deleted came back.) A segment still pointed at by another page
survives, since two documents may share a sentence.

Leaving the page stops the narrator: the router announces the view change, and
every mounted player pauses and releases its file. A detached `Audio` object
used to keep playing with no control left on screen.

An adventure therefore gets exactly the scenes its author asked for. Rendering
scene 4 of 13 costs one scene of CPU, not the whole graph.

## Storage and cost

- One MP3 per ≈900-character chunk, in the media directory, served like any
  other `/media/...` file.
- Segments are cached on the hash of their text, voice, **tone**, language and
  model: a 12 000-character page with one corrected sentence re-synthesises
  **one** segment, not thirteen.
- Storage is the only recurring cost on a local engine: about 8 KiB per second
  of audio, so roughly 470 KiB per minute.

## Guarantees

- **Nothing leaves the instance.** The engine runs beside the application.
- **One job at a time.** A semaphore serialises synthesis, so a large document
  cannot starve the web server; requests queue instead.
- **A failed engine fails the job, not the page.** The error is stored on the job
  and shown to the author; no partial rendition is published.
- **No audio leaks past the document's own visibility.** The list endpoint
  returns nothing for a document the caller cannot read — a draft's transcript is
  invisible to a visitor, exactly like the draft.
- **An MP3 is checked before it is stored.** A proxy returning an HTML error page
  is refused rather than saved with an `.mp3` extension.

## Tests

`tests/test_audio.py` covers the script builder (what is read, what is dropped,
chunk sizes), the cache (a second render costs nothing; one edited sentence costs
one segment), staleness, the character ceiling, language refusal, permission,
deletion, and a broken engine.

The end-to-end suite checks the opposite direction: on an instance without a
speech service, no button and no player appears.
