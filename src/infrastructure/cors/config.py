from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.infrastructure.config.settings import settings


def configure_cors(app: FastAPI) -> None:
    origins = list(settings.cors_origins or [])
    if settings.frontend_url and settings.frontend_url not in origins:
        origins.append(settings.frontend_url)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if "*" in origins else origins,
        allow_origin_regex=r"https://.*\.railway\.app|https://.*\.up\.railway\.app|https://.*\.vercel\.app|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Retry-After", "X-App-Env", "X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )
