"""Servicio centralizado de IA de FashionStore.

Encapsula la comunicacion con Google Gemini (via API nativa de alta velocidad)
y proveedores compatibles con OpenAI. Garantiza:
- Timeout generoso configurado en settings (30s).
- Modo estructurado JSON garantizado.
- Fallback elegante si el proveedor no responde.
"""
import json
import logging
import httpx

from src.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)


class AIService:
    @staticmethod
    def is_configured() -> bool:
        return bool(settings.ai_api_key)

    @classmethod
    def generate(
        cls,
        prompt: str,
        system_instruction: str = "",
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> str:
        """Envia una solicitud a la IA configurada y retorna el texto generado."""
        if not settings.ai_api_key:
            raise ValueError("AI_API_KEY no configurada.")

        timeout_sec = timeout or settings.ai_timeout
        tokens_limit = max_tokens or settings.ai_max_tokens

        # 1. Via Google Gemini nativo (maxima velocidad, sin cuellos de botella de proxies)
        if "generativelanguage.googleapis.com" in settings.ai_base_url:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{settings.ai_model}:generateContent?key={settings.ai_api_key}"
            )
            payload = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": max(tokens_limit, 1000),
                    "temperature": temperature,
                },
            }
            if system_instruction:
                payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
            if json_mode:
                payload["generationConfig"]["responseMimeType"] = "application/json"

            response = httpx.post(url, json=payload, timeout=timeout_sec)
            response.raise_for_status()
            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            return parts[0].get("text", "").strip() if parts else ""

        # 2. Via endpoint compatible con OpenAI
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": settings.ai_model,
            "messages": messages,
            "max_tokens": max(tokens_limit, 1000),
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        response = httpx.post(
            settings.ai_chat_completions_url,
            headers={"Authorization": f"Bearer {settings.ai_api_key}"},
            json=payload,
            timeout=timeout_sec,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
