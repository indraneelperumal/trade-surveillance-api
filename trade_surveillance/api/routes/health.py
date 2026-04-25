from fastapi import APIRouter

from trade_surveillance.config import get_settings

router = APIRouter()


@router.get("/health")
def health_v1() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "service": "trade-surveillance-api", "env": settings.app_env}
