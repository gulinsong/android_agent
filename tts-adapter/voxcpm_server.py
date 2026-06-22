#!/usr/bin/env python3
"""VoxCPM2 TTS server using nanovllm-voxcpm for voice cloning.

Uses AsyncVoxCPM2ServerPool for compatibility with FastAPI's async event loop.
Supports voice cloning via /encode_latents + ref_audio_latents in /generate.
Includes audio truncation safety net for stop-token bug.

Usage:
    python voxcpm_server.py [--model-path /path/to/VoxCPM2] [--port 8000]
"""
import argparse
import base64
import io
import time
import logging
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("voxcpm-server")

server = None
sample_rate = 48000


@asynccontextmanager
async def lifespan(app):
    global server, sample_rate
    from nanovllm_voxcpm.models.voxcpm2.server import AsyncVoxCPM2ServerPool

    log.info(f"Loading VoxCPM2 from {app.state.model_path}...")
    server = AsyncVoxCPM2ServerPool(
        model_path=app.state.model_path,
        gpu_memory_utilization=app.state.gpu_memory,
        max_num_batched_tokens=8192,
        max_num_seqs=16,
        max_model_len=4096,
        enforce_eager=False,
        devices=[0],
    )
    await server.wait_for_ready()
    log.info("VoxCPM2 ready")

    model_info = await server.get_model_info()
    sample_rate = int(model_info["sample_rate"])
    log.info(f"Output sample rate: {sample_rate}")

    yield

    await server.stop()
    server = None


def create_app(model_path, gpu_memory=0.9):
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse, JSONResponse

    app = FastAPI(title="VoxCPM2 TTS Server", lifespan=lifespan)
    app.state.model_path = model_path
    app.state.gpu_memory = gpu_memory

    @app.post("/encode_latents")
    async def encode_latents(request: Request):
        wav_bytes = await request.body()
        wav_format = request.query_params.get("wav_format", "wav")
        try:
            latents = await server.encode_latents(wav_bytes, wav_format)
            log.info(f"Encoded latents: {len(latents)} bytes")
            return StreamingResponse(
                iter([latents]),
                media_type="application/octet-stream",
            )
        except Exception as e:
            log.error(f"Encode latents failed: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/generate")
    async def generate(request: Request):
        t0 = time.monotonic()
        body = await request.json()
        text = body.get("target_text", "")
        if not text:
            return JSONResponse({"error": "target_text is required"}, status_code=400)

        cfg_value = float(body.get("cfg_value", 2.0))
        temperature = float(body.get("temperature", 1.0))
        ref_audio_latents = None
        raw_latents = body.get("ref_audio_latents")
        raw_latents_b64 = body.get("ref_audio_latents_b64")
        if raw_latents_b64:
            ref_audio_latents = base64.b64decode(raw_latents_b64)
        elif raw_latents:
            ref_audio_latents = bytes(raw_latents) if isinstance(raw_latents, list) else raw_latents
        log.info(f"Generate: {len(text)} chars, text={text[:60]!r}, ref_latents={'yes' if ref_audio_latents else 'no'}, cfg={cfg_value}")

        try:
            chunks = []
            async for data in server.generate(
                target_text=text,
                cfg_value=cfg_value,
                temperature=temperature,
                ref_audio_latents=ref_audio_latents,
            ):
                chunks.append(data)

            if not chunks:
                return JSONResponse({"error": "no audio generated"}, status_code=500)

            wav = np.concatenate(chunks, axis=0)

            # Truncate if excessively long (stop-token bug safety net)
            char_count = len(text)
            max_duration = max(char_count * 0.5, 5.0)
            generated_duration = wav.shape[0] / sample_rate
            if generated_duration > max_duration:
                trim_samples = int(max_duration * sample_rate)
                wav = wav[:trim_samples]
                log.warning(f"Truncated {generated_duration:.1f}s -> {max_duration:.1f}s (text={char_count} chars)")

            buf = io.BytesIO()
            sf.write(buf, wav, sample_rate, format="WAV")
            wav_bytes = buf.getvalue()

            elapsed = time.monotonic() - t0
            duration = wav.shape[0] / sample_rate
            log.info(f"Generated {duration:.1f}s audio in {elapsed:.2f}s (RTF={elapsed/duration:.2f})")

            return StreamingResponse(
                iter([wav_bytes]),
                media_type="audio/wav",
                headers={"Content-Disposition": "attachment; filename=speech.wav"},
            )
        except Exception as e:
            log.error(f"Generation failed: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/health")
    async def health():
        return {"status": "ok" if server else "loading"}

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", default="/home/tsm/work/models/VoxCPM2")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--gpu-memory", type=float, default=0.9)
    args = parser.parse_args()

    app = create_app(args.model_path, args.gpu_memory)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
