from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from src.plataforma_saas.web.schemas.stripe_saas import IntegrationSalesOut, IntegrationStockOut
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/integrations/v1", tags=["Integraciones · API v1"])


@router.get("/sales", response_model=ApiResponse[IntegrationSalesOut])
def sales(since: datetime | None = None, limit: int = Query(default=100, ge=1, le=500)):
    raise HTTPException(501, "Implementación pendiente de API v1.")


@router.get("/stock", response_model=ApiResponse[IntegrationStockOut])
def stock(branch_code: str | None = None):
    raise HTTPException(501, "Implementación pendiente de API v1.")
