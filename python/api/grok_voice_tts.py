from __future__ import annotations

import os

from flask import Request, Response

from python.helpers.api import ApiHandler
from python.helpers import settings
from python.helpers import grok_voice_tts


class GrokVoiceTts(ApiHandler):
    """Proxy text-to-speech to xAI realtime voice API."""

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        text = (input.get("text") or "").strip()
        if not text:
            return {"success": False, "error": "No text provided"}

        set = settings.get_settings()
        api_key = (os.getenv("XAI_API_KEY") or "").strip()
        if not api_key:
            return {"success": False, "error": "XAI_API_KEY missing"}

        voice = (set.get("grok_voice_name") or "Ara").strip()
        input_format = (set.get("grok_voice_input_format") or "audio/pcm").strip()
        output_format = (set.get("grok_voice_output_format") or "audio/pcm").strip()
        input_rate = int(set.get("grok_voice_input_rate") or 24000)
        output_rate = int(set.get("grok_voice_output_rate") or 24000)
        turn_detection = (set.get("grok_voice_turn_detection") or "server_vad").strip()

        try:
            wav_audio, transcript = await grok_voice_tts.synthesize_text(
                text,
                api_key=api_key,
                voice=voice,
                input_format=input_format,
                input_rate=input_rate,
                output_format=output_format,
                output_rate=output_rate,
                turn_detection_type=turn_detection,
            )
            response = Response(wav_audio, mimetype="audio/wav", status=200)
            if transcript:
                response.headers["X-Grok-Transcript"] = transcript[:512]
            return response
        except Exception as e:
            return {"success": False, "error": f"Grok Voice request failed: {e}"}
