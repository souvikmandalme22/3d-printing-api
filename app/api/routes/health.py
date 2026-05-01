from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    service: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns service liveness status.",
)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", service="3d-printing-api")
