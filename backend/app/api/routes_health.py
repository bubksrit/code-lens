from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str = "ok"


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def get_health():
    """Health check endpoint returning application status."""
    return HealthResponse(status="ok")
