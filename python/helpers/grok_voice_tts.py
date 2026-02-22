from __future__ import annotations

import asyncio
import base64
import io
import json
import wave
from typing import Any


REALTIME_ENDPOINT = "wss://api.x.ai/v1/realtime"
SUPPORTED_VOICES = {"Ara", "Rex", "Sal", "Eve", "Leo"}


def _build_audio_format(audio_format: str, sample_rate: int) -> dict[str, Any]:
    fmt: dict[str, Any] = {"type": audio_format}
    if audio_format == "audio/pcm":
        fmt["rate"] = sample_rate
    return fmt


def _to_wav_from_pcm16(pcm_bytes: bytes, sample_rate: int) -> bytes:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # 16-bit PCM
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)
        return buffer.getvalue()


async def synthesize_text(
    text: str,
    *,
    api_key: str,
    voice: str = "Ara",
    input_format: str = "audio/pcm",
    input_rate: int = 24000,
    output_format: str = "audio/pcm",
    output_rate: int = 24000,
    turn_detection_type: str = "server_vad",
    timeout_seconds: int = 45,
) -> tuple[bytes, str]:
    if not text.strip():
        raise ValueError("No text provided")
    if not api_key.strip():
        raise ValueError("XAI_API_KEY missing")
    if voice not in SUPPORTED_VOICES:
        raise ValueError(f"Unsupported Grok voice: {voice}")
    if output_format != "audio/pcm":
        raise ValueError("Only audio/pcm output is currently supported in this implementation")

    import websockets  # type: ignore[import-not-found]

    headers = {"Authorization": f"Bearer {api_key}"}
    session_update = {
        "type": "session.update",
        "session": {
            "voice": voice,
            "turn_detection": (
                {"type": turn_detection_type}
                if turn_detection_type and turn_detection_type.lower() != "none"
                else {"type": None}
            ),
            "audio": {
                "input": {"format": _build_audio_format(input_format, int(input_rate))},
                "output": {"format": _build_audio_format(output_format, int(output_rate))},
            },
        },
    }
    user_item = {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        },
    }
    response_create = {"type": "response.create"}

    audio_chunks: list[bytes] = []
    transcript_parts: list[str] = []

    async with websockets.connect(  # type: ignore[attr-defined]
        REALTIME_ENDPOINT,
        additional_headers=headers,
        open_timeout=15,
        close_timeout=5,
        ping_interval=20,
        ping_timeout=20,
        max_size=8 * 1024 * 1024,
    ) as websocket:
        await websocket.send(json.dumps(session_update))
        await websocket.send(json.dumps(user_item))
        await websocket.send(json.dumps(response_create))

        while True:
            raw_message = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
            event = json.loads(raw_message)
            event_type = event.get("type", "")

            if event_type == "error":
                details = event.get("error") or event
                raise RuntimeError(f"Grok realtime error: {details}")

            if event_type == "response.output_audio.delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    audio_chunks.append(base64.b64decode(delta))
                continue

            if event_type == "response.output_audio_transcript.delta":
                delta_text = event.get("delta")
                if isinstance(delta_text, str) and delta_text:
                    transcript_parts.append(delta_text)
                continue

            if event_type == "response.done":
                break

    pcm_audio = b"".join(audio_chunks)
    if not pcm_audio:
        raise RuntimeError("Grok Voice returned no audio")

    wav_audio = _to_wav_from_pcm16(pcm_audio, int(output_rate))
    transcript = "".join(transcript_parts).strip()
    return wav_audio, transcript
