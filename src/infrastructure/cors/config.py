from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.infrastructure.config.settings import settings


def configure_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
