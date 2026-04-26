from fastapi import APIRouter

from trade_surveillance.api.routes.alerts import router as alerts_router
from trade_surveillance.api.routes.health import router as health_router
from trade_surveillance.api.routes.metrics import router as metrics_router
from trade_surveillance.api.routes.investigation_notes import router as investigation_notes_router
from trade_surveillance.api.routes.investigations import router as investigations_router
from trade_surveillance.api.routes.model_runs import router as model_runs_router
from trade_surveillance.api.routes.trades import router as trades_router
from trade_surveillance.api.routes.users import router as users_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router, tags=["health"])
api_router.include_router(trades_router, tags=["trades"])
api_router.include_router(alerts_router, tags=["alerts"])
api_router.include_router(investigations_router, tags=["investigations"])
api_router.include_router(investigation_notes_router, tags=["investigation-notes"])
api_router.include_router(model_runs_router, tags=["model-runs"])
api_router.include_router(users_router, tags=["users"])
api_router.include_router(metrics_router, tags=["metrics"])
