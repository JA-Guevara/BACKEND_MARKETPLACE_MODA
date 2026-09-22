"""Contrato del dictado del asistente: el audio se transcribe sin persistirse."""

import asyncio
from io import BytesIO

from fastapi import UploadFile
from starlette.datastructures import Headers

from src.infrastructure.config.settings import settings
from src.ventas_pagos.web import router


class _OpenAIReply:
    def raise_for_status(self):
        return None

    def json(self):
        return {"text": "Exportame ventas de este mes en Excel"}


def _audio(content: bytes = b"a" * 600) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename="consulta.webm",
        headers=Headers({"content-type": "audio/webm"}),
    )


def test_transcribe_audio_sends_ephemeral_file_to_transcription(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_transcription_model", "gpt-4o-mini-transcribe")
    monkeypatch.setattr(router.httpx, "post", lambda *args, **kwargs: calls.append((args, kwargs)) or _OpenAIReply())

    result = asyncio.run(router.transcribe_assistant_audio(object(), _audio()))

    assert result.data == {"available": True, "text": "Exportame ventas de este mes en Excel"}
    assert calls[0][0][0] == "https://api.openai.com/v1/audio/transcriptions"
    assert calls[0][1]["data"]["language"] == "es"
    assert calls[0][1]["files"]["file"][0] == "consulta.webm"


def test_transcribe_audio_reports_missing_ai_configuration(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "")

    result = asyncio.run(router.transcribe_assistant_audio(object(), _audio()))

    assert result.data["available"] is False
    assert "AI_API_KEY" in result.data["message"]
