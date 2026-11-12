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
import time
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
        timeout: int | float | None = None,
    ) -> str:
        """Envia una solicitud a la IA configurada con presupuesto y corta al primer error de red/timeout."""
        if not settings.ai_api_key:
            raise ValueError("AI_API_KEY no configurada.")

        timeout_sec = float(timeout if timeout is not None else settings.ai_timeout or 8.0)
        tokens_limit = max_tokens or settings.ai_max_tokens
        candidate_models = cls.get_candidate_models()

        # 1. Via Google Gemini nativo (máxima velocidad, sin latencia de proxies)
        if "generativelanguage.googleapis.com" in settings.ai_base_url:
            # Presupuesto total: el tiempo se reparte entre los modelos candidatos.
            # Un modelo saturado o no disponible (respuesta HTTP de error) cede el
            # turno al siguiente; un timeout o error de red corta de inmediato,
            # porque reintentar solo alargaría la espera del usuario.
            limite = time.monotonic() + timeout_sec
            ultimo_error: Exception | None = None
            for model in (candidate_models or ["gemini-3.5-flash-lite"]):
                restante = limite - time.monotonic()
                if restante < 0.5:
                    break
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                headers = {"x-goog-api-key": settings.ai_api_key}
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
                    response = httpx.post(url, headers=headers, json=payload, timeout=restante)
                    response.raise_for_status()
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text = parts[0].get("text", "").strip() if parts else ""
                        if text:
                            return text
                    ultimo_error = RuntimeError(f"El modelo {model} no devolvió contenido")
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    logger.warning("AIService fallo por tiempo o error de red con modelo %s: %s", model, exc.__class__.__name__)
                    raise TimeoutError("Tiempo agotado o error de red con el servicio de IA") from exc
                except httpx.HTTPStatusError as exc:
                    # No se registra la excepción completa: su texto incluye la URL.
                    logger.warning("AIService: el modelo %s respondió %s; se prueba el siguiente", model, exc.response.status_code)
                    ultimo_error = exc
                except (httpx.HTTPError, KeyError, IndexError) as exc:
                    logger.warning("AIService Gemini nativo fallo con modelo %s: %s", model, exc.__class__.__name__)
                    raise
            if isinstance(ultimo_error, httpx.HTTPStatusError):
                raise ultimo_error
            raise RuntimeError("El servicio de IA no devolvió contenido dentro del tiempo disponible")

        # 2. Via endpoint compatible con OpenAI
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        model = candidate_models[0] if candidate_models else "gpt-4o-mini"
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
                timeout=timeout_sec,
            )
            response.raise_for_status()
            choices = response.json().get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning("AIService OpenAI fallo por tiempo o red con modelo %s: %s", model, exc.__class__.__name__)
            raise TimeoutError("Tiempo agotado o error de red con el servicio de IA") from exc
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            logger.warning("AIService OpenAI fallo con modelo %s: %s", model, exc.__class__.__name__)
            raise

        raise RuntimeError(f"El servicio de IA no devolvió contenido con modelo {model}")
