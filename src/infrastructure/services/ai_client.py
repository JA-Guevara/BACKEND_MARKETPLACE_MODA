"""Servicio centralizado de IA de FashionStore.

Encapsula la comunicacion con Google Gemini (via API nativa de alta velocidad)
y proveedores compatibles con OpenAI. Garantiza:
- Multi-model fallback automático (ej. gemini-3.5-flash-lite, gemini-flash-lite-latest).
- Timeouts ágiles por intento para evitar saturar proxies o exceder límites.
- Modo estructurado JSON garantizado.
- Fallback elegante si el proveedor no responde.
"""
import json
import logging
import httpx

from src.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)

FALLBACK_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
)


class AIService:
    @staticmethod
    def is_configured() -> bool:
        return bool(settings.ai_api_key)

    @classmethod
    def get_candidate_models(cls) -> list[str]:
        candidates: list[str] = []
        if settings.ai_model:
            candidates.append(settings.ai_model)
        for model in FALLBACK_MODELS:
            if model not in candidates:
                candidates.append(model)
        return candidates

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
        """Envia una solicitud a la IA configurada con fallback y retorna el texto generado."""
        if not settings.ai_api_key:
            raise ValueError("AI_API_KEY no configurada.")

        timeout_sec = timeout or settings.ai_timeout
        tokens_limit = max_tokens or settings.ai_max_tokens
        candidate_models = cls.get_candidate_models()

        # 1. Via Google Gemini nativo (máxima velocidad, sin latencia de proxies)
        if "generativelanguage.googleapis.com" in settings.ai_base_url:
            last_err = None
            for idx, model in enumerate(candidate_models):
                attempt_timeout = min(timeout_sec, 5.0) if idx < len(candidate_models) - 1 else min(timeout_sec, 7.0)
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={settings.ai_api_key}"
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

                try:
                    response = httpx.post(url, json=payload, timeout=attempt_timeout)
                    response.raise_for_status()
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text = parts[0].get("text", "").strip() if parts else ""
                    if text:
                        return text
                except (httpx.HTTPError, httpx.TimeoutException, KeyError, IndexError) as exc:
                    logger.warning("AIService Gemini nativo fallo con modelo %s: %s. Probando siguiente...", model, exc)
                    last_err = exc
                    continue

            logger.warning("Todos los modelos nativos de Gemini fallaron; intentando endpoint OpenAI...")

        # 2. Via endpoint compatible con OpenAI
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        last_openai_err = None
        for idx, model in enumerate(candidate_models):
            attempt_timeout = min(timeout_sec, 5.0) if idx < len(candidate_models) - 1 else min(timeout_sec, 7.0)
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max(tokens_limit, 1000),
                "temperature": temperature,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            try:
                response = httpx.post(
                    settings.ai_chat_completions_url,
                    headers={"Authorization": f"Bearer {settings.ai_api_key}"},
                    json=payload,
                    timeout=attempt_timeout,
                )
                response.raise_for_status()
                choices = response.json().get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
            except (httpx.HTTPError, httpx.TimeoutException, KeyError, IndexError) as exc:
                logger.warning("AIService OpenAI-compatible fallo con modelo %s: %s", model, exc)
                last_openai_err = exc
                continue

        raise RuntimeError(f"El servicio de IA no respondió tras intentar los modelos disponibles: {last_openai_err or 'desconocido'}")
