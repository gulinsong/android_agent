#!/usr/bin/env python3
"""OpenAI-compatible TTS adapter for VoxCPM2 (vLLM-Omni).

Three independent dimensions:
  - Voice preset: ref_audio (preset) or prompt_text→ref_audio (custom with auto_ref)
  - Dialect: global setting, set by app
  - Tone/mood: global setting, set by app

Usage:
    python adapter.py [--voxcpm-url http://172.20.10.5:8000] [--port 8091]
"""
import argparse
import io
import json
import os
import re
import time
import threading
import logging
import base64
import wave

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tts-adapter")

app = FastAPI()

VOXCPM_URL = "http://172.20.10.5:8000"
VOICE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_FILE = "voices.json"
SETTINGS_FILE = "settings.json"

# PCM stream params. vllm-omni/VoxCPM2 outputs 48kHz mono s16le (96000 bytes/sec).
TTS_SAMPLE_RATE = 48000
# Silence injected between independently-generated segments. Each segment's
# head/tail samples may not be zero (vllm-omni doesn't pad), so direct
# concatenation produces clicks at the boundary. A short silence gap lets
# the trailing transient of one segment and the leading transient of the
# next both decay before audio resumes — audibly a brief pause rather than
# a pop. 80ms is the shortest gap that reliably masks the transients.
SEGMENT_SILENCE_MS = 80
SEGMENT_SILENCE_BYTES = TTS_SAMPLE_RATE * 2 * SEGMENT_SILENCE_MS // 1000
# Linear fade-in applied to the first chunk of each segment to suppress the
# leading transient (vllm-omni emits non-zero head samples). 10ms is short
# enough to be inaudible as a separate effect but long enough to avoid clicks.
SEGMENT_FADE_IN_MS = 10
SEGMENT_FADE_IN_SAMPLES = TTS_SAMPLE_RATE * SEGMENT_FADE_IN_MS // 1000


def apply_fade_in(pcm: bytearray, samples_to_fade: int) -> bytearray:
    """Linear fade-in on the first N samples of a 16-bit signed little-endian PCM buffer."""
    if samples_to_fade <= 0 or len(pcm) < 4:
        return pcm
    n = len(pcm) // 2
    fade = min(samples_to_fade, n)
    for i in range(fade):
        ratio = (i + 1) / fade
        lo = pcm[i * 2]
        hi = pcm[i * 2 + 1]
        raw = (hi << 8) | lo
        if raw >= 32768:
            raw -= 65536
        faded = int(raw * ratio)
        if faded < 0:
            faded += 65536
        pcm[i * 2] = faded & 0xFF
        pcm[i * 2 + 1] = (faded >> 8) & 0xFF
    return pcm

_ref_audio_cache: dict[str, str] = {}
_lock = threading.Lock()


# ── Voice presets ──────────────────────────────────────────────────────────

def load_voices() -> dict:
    path = os.path.join(VOICE_DIR, VOICES_FILE)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"default": {"description": "Default", "ref_audio": None}}


def save_voices(voices: dict):
    with open(os.path.join(VOICE_DIR, VOICES_FILE), "w") as f:
        json.dump(voices, f, indent=2, ensure_ascii=False)


def resolve_voice(voice_id: str) -> dict:
    voices = load_voices()
    return voices.get(voice_id, voices.get("default", {}))


# ── Global settings (dialect, tone) ────────────────────────────────────────

def load_settings() -> dict:
    path = os.path.join(VOICE_DIR, SETTINGS_FILE)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"dialect": "", "tone": ""}


def save_settings(settings: dict):
    with open(os.path.join(VOICE_DIR, SETTINGS_FILE), "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


# ── Ref audio handling ─────────────────────────────────────────────────────

def _load_ref_audio(ref_audio_path: str) -> str | None:
    full_path = os.path.join(VOICE_DIR, ref_audio_path)
    if not os.path.exists(full_path):
        log.warning(f"Ref audio not found: {full_path}")
        return None
    wav_bytes = open(full_path, "rb").read()
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    data_url = f"data:audio/wav;base64,{b64}"
    _ref_audio_cache[ref_audio_path] = data_url
    log.info(f"Loaded ref audio: {full_path} -> {len(wav_bytes)} bytes")
    return data_url


def warmup_ref_audios():
    voices = load_voices()
    for vid, preset in voices.items():
        ref = preset.get("ref_audio")
        if ref and ref not in _ref_audio_cache:
            log.info(f"Warmup: loading ref audio for '{vid}' -> {ref}")
            _load_ref_audio(ref)


def get_ref_audio_data_url(ref_audio_path: str) -> str | None:
    if ref_audio_path in _ref_audio_cache:
        return _ref_audio_cache[ref_audio_path]
    return _load_ref_audio(ref_audio_path)


# ── Text preprocessing ─────────────────────────────────────────────────────

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # ZWJ
    "\U00002B50"             # ⭐
    "\U0000231A-\U0000231B"  # watch, hourglass
    "\U000023E9-\U000023F3"  # media controls
    "\U000023F8-\U000023FA"  # media controls
    "\U000025AA-\U000025FE"  # geometric shapes
    "\U00002614-\U00002615"  # umbrella, hot beverage
    "\U00002648-\U00002653"  # zodiac
    "\U000026A0-\U000026A1"  # warning, high voltage
    "\U000026BD-\U000026BE"  # soccer, baseball
    "\U000026C4-\U000026C5"  # snowman, sun
    "\U000026CE"             # Ophiuchus
    "\U000026D3-\U000026D4"  # chains, no entry
    "\U000026EA"             # church
    "\U000026F2-\U000026F3"  # fountain, golf
    "\U000026F5"             # sailboat
    "\U000026FA"             # tent
    "\U000026FD"             # fuel pump
    "\U00002702-\U000027B0"  # dingbats
    "\U00002934-\U00002935"  # arrows
    "\U00002B05-\U00002B07"  # arrows
    "]+",
    flags=re.UNICODE,
)

_STRIP_RE = re.compile(r"[#*~`>\[\]{}<>|]")

# LLM formatting artifacts that shouldn't be spoken
_FORMAT_RE = re.compile(r"(?:^|\s)[-—]+(?:\s|$)|——")

_SPLIT_PUNCT = re.compile(r"([。！？；\n]+)")


def clean_text(text: str) -> str:
    """Strip emojis, markdown symbols, and other non-speakable characters."""
    text = _EMOJI_RE.sub("", text)
    text = _STRIP_RE.sub("", text)
    # Remove standalone dashes (LLM list markers, em dashes)
    text = _FORMAT_RE.sub("，", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Remove duplicate commas and fix colon+comma
    text = re.sub(r"，+", "，", text)
    text = re.sub(r"([：；])，", r"\1", text)
    text = text.strip("，")
    return text


MAX_SEGMENT_LEN = 200


def split_text(text: str, max_len: int = MAX_SEGMENT_LEN) -> list[str]:
    """Split text into TTS-friendly segments at sentence boundaries."""
    if len(text) <= max_len:
        return [text]

    # Primary split at strong sentence endings
    parts = _SPLIT_PUNCT.split(text)
    sentences: list[str] = []
    buf = ""
    for part in parts:
        if _SPLIT_PUNCT.fullmatch(part):
            buf += part
            sentences.append(buf)
            buf = ""
        else:
            if buf and len(buf) + len(part) > max_len:
                sentences.append(buf)
                buf = part
            else:
                buf += part
    if buf:
        sentences.append(buf)

    # Merge short fragments and force-split anything still too long
    result: list[str] = []
    buf = ""
    for s in sentences:
        if len(s) > max_len:
            if buf:
                result.append(buf)
                buf = ""
            # Force split by comma/soft punctuation
            for chunk in re.split(r"(，|,|、|；)", s):
                if len(buf) + len(chunk) > max_len and buf:
                    result.append(buf)
                    buf = chunk
                else:
                    buf += chunk
        elif len(buf) + len(s) > max_len:
            result.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        result.append(buf)

    # Final pass: force-split any segment still over max_len
    final: list[str] = []
    for s in result:
        s = s.strip()
        if not s:
            continue
        if len(s) > max_len:
            final.extend(_force_split(s, max_len))
        else:
            final.append(s)
    return final


def _force_split(text: str, max_len: int) -> list[str]:
    """Last-resort split: hard break at max_len boundaries."""
    return [text[i:i + max_len] for i in range(0, len(text), max_len)]


def concat_wav(wav_chunks: list[bytes]) -> bytes:
    """Concatenate multiple WAV byte buffers into one WAV."""
    if len(wav_chunks) == 1:
        return wav_chunks[0]

    frames = b""
    params = None
    for chunk in wav_chunks:
        with wave.open(io.BytesIO(chunk), "rb") as wf:
            if params is None:
                params = wf.getparams()
            frames += wf.readframes(wf.getnframes())

    out = io.BytesIO()
    with wave.open(out, "wb") as wo:
        wo.setparams(params)
        wo.writeframes(frames)
    return out.getvalue()


# ── Input text builder ─────────────────────────────────────────────────────

def build_input_text(preset: dict, settings: dict, text: str) -> str:
    """Build VoxCPM2 input with optional prefix: (prompt_text, tone, dialect)text.

    - Preset voice: only ref_audio, no prompt prefix from voice
    - Custom voice first-time: prompt_text as voice description (no ref_audio yet)
    - Custom voice second-time: ref_audio saved, prompt_text cleared by auto_ref
    - Tone and dialect are always independent global settings
    """
    parts = []
    prompt_text = preset.get("prompt_text", "")
    if prompt_text:
        parts.append(prompt_text)
    tone = settings.get("tone", "")
    if tone:
        parts.append(tone)
    dialect = settings.get("dialect", "")
    if dialect:
        parts.append(dialect)
    if parts:
        return f"({'，'.join(parts)}){text}"
    return text


# ── TTS endpoint ───────────────────────────────────────────────────────────

async def _stream_speech(body: dict, t0: float):
    """Streaming branch for /v1/audio/speech.

    Forwards vllm-omni PCM chunks to the client as they arrive. Each segment
    is generated independently and concatenated in stream order. Caller must
    pass stream=true and response_format=pcm (wav header collisions across
    segments make wav streaming unsafe — reject it explicitly).

    Returns a StreamingResponse whose body iterator yields raw PCM bytes.
    Errors mid-stream are logged and the iterator closes cleanly so the
    client sees a truncated-but-valid stream rather than a hang.
    """
    raw_text = body.get("input", "")
    text = clean_text(raw_text)
    if not text:
        return JSONResponse({"error": "input is empty after cleaning"}, status_code=400)

    response_format = body.get("response_format", "pcm").lower()
    if response_format not in ("pcm", ""):
        return JSONResponse(
            {"error": f"stream=true requires response_format=pcm, got '{response_format}'"},
            status_code=400,
        )

    segments = split_text(text)
    voice_id = body.get("voice", "default")
    preset = resolve_voice(voice_id)
    settings = load_settings()
    ref_audio = preset.get("ref_audio")
    ref_data_url = get_ref_audio_data_url(ref_audio) if ref_audio else None

    log.info(
        f"TTS stream: voice={voice_id}, ref={'yes' if ref_audio else 'no'}, "
        f"segments={len(segments)}, raw_len={len(raw_text)}, clean_len={len(text)}"
    )

    async def gen():
        first_byte_at = None
        total_bytes = 0
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
                for i, seg in enumerate(segments):
                    input_text = build_input_text(preset, settings, seg)
                    payload = {
                        "input": input_text,
                        "response_format": "pcm",
                        "stream": True,
                    }
                    if ref_data_url:
                        payload["ref_audio"] = ref_data_url

                    # Inject silence between segments to suppress boundary clicks.
                    # vllm-omni emits non-zero head/tail samples per segment; padding
                    # gives the trailing transient of seg N time to decay before seg
                    # N+1's leading transient arrives.
                    if i > 0:
                        pad = b"\x00" * SEGMENT_SILENCE_BYTES
                        total_bytes += len(pad)
                        yield pad

                    seg_t0 = time.monotonic()
                    seg_bytes = 0
                    seg_first_chunk_faded = False
                    try:
                        async with client.stream(
                            "POST", f"{VOXCPM_URL}/v1/audio/speech", json=payload
                        ) as resp:
                            if resp.status_code != 200:
                                err = await resp.aread()
                                log.error(
                                    f"stream seg {i+1}/{len(segments)} HTTP "
                                    f"{resp.status_code}: {err[:200]}"
                                )
                                break
                            async for chunk in resp.aiter_bytes():
                                # Apply fade-in on the first chunk of this segment
                                # to suppress the leading transient.
                                if not seg_first_chunk_faded:
                                    chunk = bytes(apply_fade_in(
                                        bytearray(chunk), SEGMENT_FADE_IN_SAMPLES
                                    ))
                                    seg_first_chunk_faded = True
                                if first_byte_at is None:
                                    first_byte_at = time.monotonic() - t0
                                    log.info(
                                        f"  first byte: {first_byte_at*1000:.0f}ms "
                                        f"(seg {i+1})"
                                    )
                                total_bytes += len(chunk)
                                seg_bytes += len(chunk)
                                yield chunk
                    except Exception as e:
                        log.error(f"stream seg {i+1} failed: {e}")
                        break
                    log.info(
                        f"  seg {i+1}/{len(segments)} done: {seg_bytes}B in "
                        f"{time.monotonic()-seg_t0:.2f}s"
                    )
        finally:
            elapsed = time.monotonic() - t0
            audio_sec = total_bytes / (TTS_SAMPLE_RATE * 2)  # 48kHz × 2 bytes/sample
            log.info(
                f"stream done: {total_bytes}B ({audio_sec:.2f}s audio), "
                f"total {elapsed:.2f}s, RTF={elapsed/audio_sec:.2f}"
                if audio_sec > 0
                else f"stream done: 0 bytes in {elapsed:.2f}s"
            )

    return StreamingResponse(gen(), media_type="audio/pcm")


@app.post("/v1/audio/speech")
async def speech(request: Request):
    t0 = time.monotonic()
    body = await request.json()
    raw_text = body.get("input", "")
    if not raw_text:
        return JSONResponse({"error": "input is required"}, status_code=400)

    text = clean_text(raw_text)
    if not text:
        return JSONResponse({"error": "input is empty after cleaning"}, status_code=400)

    # Stream branch: forward vllm-omni PCM chunks as they arrive.
    # Triggered by body["stream"]=true. Falls back to legacy buffered path
    # if stream is absent/false — preserves existing app behavior 100%.
    if body.get("stream") is True:
        return await _stream_speech(body, t0)

    segments = split_text(text)
    voice_id = body.get("voice", "default")
    preset = resolve_voice(voice_id)
    settings = load_settings()

    response_format = body.get("response_format", "wav")
    ref_audio = preset.get("ref_audio")
    ref_data_url = get_ref_audio_data_url(ref_audio) if ref_audio else None
    seed = settings.get("seed", 42)
    cfg_value = preset.get("cfg_value", settings.get("cfg_value", 2.0))
    temperature = preset.get("temperature", None)

    log.info(f"TTS: voice={voice_id}, ref={'yes' if ref_audio else 'no'}, segments={len(segments)}, seed={seed}, cfg={cfg_value}, tone='{settings.get('tone', '')}', dialect='{settings.get('dialect', '')}', raw_len={len(raw_text)}, clean_len={len(text)}")

    chunks: list[bytes] = []
    is_wav = response_format in ("wav", "wave", "")
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
        for i, seg in enumerate(segments):
            input_text = build_input_text(preset, settings, seg)
            payload = {
                "input": input_text,
                "response_format": response_format,
                "seed": seed,
                "extra_params": {"cfg_value": cfg_value, **({"temperature": temperature} if temperature is not None else {})},
            }
            if ref_data_url:
                payload["ref_audio"] = ref_data_url

            log.info(f"  segment {i+1}/{len(segments)} ({len(seg)} chars): '{seg}'")
            resp = await client.post(f"{VOXCPM_URL}/v1/audio/speech", json=payload)
            if resp.status_code != 200:
                log.error(f"VoxCPM2 error on segment {i+1}: {resp.status_code} {resp.text[:200]}")
                return JSONResponse({"error": f"VoxCPM2 error: {resp.status_code}"}, status_code=resp.status_code)
            chunks.append(resp.content)

    audio = concat_wav(chunks) if is_wav and len(chunks) > 1 else chunks[0]
    elapsed = time.monotonic() - t0
    log.info(f"TTS done: {len(audio)} bytes, {len(segments)} segments, format={response_format}, {elapsed:.2f}s")

    # Auto-ref: custom voice first generation → save as ref_audio for future use
    if preset.get("auto_ref") and not preset.get("ref_audio"):
        if len(audio) > 10000:
            with _lock:
                ref_dir = os.path.join(VOICE_DIR, "voice_samples")
                os.makedirs(ref_dir, exist_ok=True)
                ref_path = os.path.join(ref_dir, "custom_ref.wav")
                with open(ref_path, "wb") as f:
                    f.write(audio)
                log.info(f"Auto-ref saved: {ref_path}")

                voices = load_voices()
                if voice_id in voices:
                    voices[voice_id]["ref_audio"] = "voice_samples/custom_ref.wav"
                    voices[voice_id]["prompt_text"] = ""
                    voices[voice_id]["auto_ref"] = False
                    save_voices(voices)
                    log.info(f"Auto-ref upgraded: {voice_id} -> voice_samples/custom_ref.wav")

    fmt_media = {"wav": "audio/wav", "opus": "audio/ogg", "ogg": "audio/ogg",
                 "mp3": "audio/mpeg", "flac": "audio/flac"}.get(response_format, "audio/wav")
    fmt_ext = response_format if response_format else "wav"
    return StreamingResponse(
        iter([audio]),
        media_type=fmt_media,
        headers={"Content-Disposition": f"attachment; filename=speech.{fmt_ext}"},
    )


# ── Voice preset API ───────────────────────────────────────────────────────

@app.get("/v1/models")
async def models():
    voices = load_voices()
    return {"data": [{"id": k, "object": "model", "description": v.get("description", "")} for k, v in voices.items()]}


@app.get("/v1/voices/{voice_id}")
async def get_voice(voice_id: str):
    voices = load_voices()
    if voice_id in voices:
        return {"id": voice_id, **voices[voice_id]}
    return JSONResponse({"error": f"voice '{voice_id}' not found"}, status_code=404)


@app.post("/v1/voices")
async def update_voice(request: Request):
    body = await request.json()
    voice_id = body.get("id")
    if not voice_id:
        return JSONResponse({"error": "id is required"}, status_code=400)

    with _lock:
        voices = load_voices()
        current = voices.get(voice_id, {})

        for key in ("description", "ref_audio", "prompt_text", "auto_ref", "cfg_value", "temperature"):
            if key in body:
                current[key] = body[key]

        voices[voice_id] = current
        save_voices(voices)

        old_ref = current.get("ref_audio")
        if old_ref and old_ref in _ref_audio_cache:
            if "ref_audio" in body and body["ref_audio"] != old_ref:
                _ref_audio_cache.pop(old_ref, None)

    log.info(f"Voice '{voice_id}' updated: {current}")
    return {"ok": True, "voice": voices[voice_id]}


# ── Settings API (dialect, tone) ───────────────────────────────────────────

@app.get("/v1/tts-settings")
async def get_settings():
    return load_settings()


@app.post("/v1/tts-settings")
async def update_settings(request: Request):
    body = await request.json()
    with _lock:
        settings = load_settings()
        for key in ("dialect", "tone", "seed", "cfg_value"):
            if key in body:
                settings[key] = body[key]
        save_settings(settings)
    log.info(f"Settings updated: {settings}")
    return {"ok": True, "settings": settings}


# ── Voice clone ────────────────────────────────────────────────────────────

CLONE_REF = "voice_samples/user_clone.wav"


@app.post("/v1/clone/clear")
async def clone_clear():
    full_path = os.path.join(VOICE_DIR, CLONE_REF)
    if os.path.exists(full_path):
        os.remove(full_path)
        log.info(f"Clone audio cleared: {full_path}")
    _ref_audio_cache.pop(CLONE_REF, None)
    return {"ok": True}


@app.get("/v1/clone/status")
async def clone_status():
    full_path = os.path.join(VOICE_DIR, CLONE_REF)
    exists = os.path.exists(full_path)
    info = {"has_clone_audio": exists}
    if exists:
        info["size"] = os.path.getsize(full_path)
    return info


@app.post("/v1/clone/activate")
async def clone_activate():
    full_path = os.path.join(VOICE_DIR, CLONE_REF)
    if not os.path.exists(full_path):
        return JSONResponse({"ok": False, "error": "no clone audio found"}, status_code=404)

    with _lock:
        voices = load_voices()
        current = voices.get("default", {})
        old_ref = current.get("ref_audio")

        current["ref_audio"] = CLONE_REF
        current["prompt_text"] = ""
        current["auto_ref"] = False
        voices["default"] = current
        save_voices(voices)

        if old_ref and old_ref in _ref_audio_cache:
            _ref_audio_cache.pop(old_ref, None)
        _ref_audio_cache.pop(CLONE_REF, None)

    log.info(f"Clone voice activated: default -> {CLONE_REF}")
    return {"ok": True}


# ── Health ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Filler generation ──────────────────────────────────────────────────────

DEFAULT_FILLER_PHRASES = [
    "好的，请稍等一下哈",
    "嗯，让我想想看",
    "好嘞，马上给您查一下",
    "您稍等，我这就看看",
    "好，我帮您查一下",
    "稍等我一下，马上好",
]


@app.post("/v1/filler/generate")
async def generate_fillers(request: Request):
    """Generate filler clips (short "请稍等"-style utterances) for the watchdog.

    Body:
      voice: voice id from voices.json (default "default")
      phrases: list[str] — falls back to DEFAULT_FILLER_PHRASES
      response_format: "ogg" | "mp3" | "wav" (default "ogg")

    Returns base64-encoded audio per phrase so the caller can write them to the
    device's filler directory (e.g. /data/local/tmp/openclaw-home/.openclaw/media/filler/{voice}/).
    """
    body = await request.json()
    voice_id = body.get("voice", "default")
    phrases = body.get("phrases") or DEFAULT_FILLER_PHRASES
    response_format = body.get("response_format", "ogg")

    preset = resolve_voice(voice_id)
    settings = load_settings()
    ref_audio = preset.get("ref_audio")
    ref_data_url = get_ref_audio_data_url(ref_audio) if ref_audio else None
    seed = settings.get("seed", 42)
    cfg_value = preset.get("cfg_value", settings.get("cfg_value", 2.0))
    temperature = preset.get("temperature", None)

    log.info(f"Filler gen: voice={voice_id}, phrases={len(phrases)}, format={response_format}")

    fillers = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
        for idx, phrase in enumerate(phrases, start=1):
            input_text = build_input_text(preset, settings, phrase)
            payload = {
                "input": input_text,
                "response_format": response_format,
                "seed": seed,
                "extra_params": {"cfg_value": cfg_value, **({"temperature": temperature} if temperature is not None else {})},
            }
            if ref_data_url:
                payload["ref_audio"] = ref_data_url

            resp = await client.post(f"{VOXCPM_URL}/v1/audio/speech", json=payload)
            if resp.status_code != 200:
                log.error(f"Filler gen failed on phrase '{phrase}': {resp.status_code} {resp.text[:200]}")
                return JSONResponse(
                    {"error": f"VoxCPM2 error on phrase '{phrase}': {resp.status_code}"},
                    status_code=resp.status_code,
                )
            audio_b64 = base64.b64encode(resp.content).decode("ascii")
            fillers.append({
                "idx": idx,
                "phrase": phrase,
                "filename": f"{idx:02d}.{response_format}",
                "audio_base64": audio_b64,
                "size": len(resp.content),
            })
            log.info(f"  filler {idx}/{len(phrases)}: '{phrase}' ({len(resp.content)} bytes)")

    log.info(f"Filler gen done: voice={voice_id}, {len(fillers)} clips")
    return {"voice": voice_id, "format": response_format, "fillers": fillers}


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--voxcpm-url", default="http://172.20.10.5:8000")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--voices", default="voices.json")
    args = parser.parse_args()
    VOXCPM_URL = args.voxcpm_url
    VOICES_FILE = args.voices
    import uvicorn

    @app.on_event("startup")
    async def _warmup():
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, warmup_ref_audios)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
