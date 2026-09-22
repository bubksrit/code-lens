from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.config import settings
from backend.app.api.router import api_router


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="Grounded developer assistant for Python codebases",
        version="0.1.0",
        debug=settings.debug,
    )

    # Configure CORS for local development & frontend integration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API router
    app.include_router(api_router)

    return app


app = create_app()
