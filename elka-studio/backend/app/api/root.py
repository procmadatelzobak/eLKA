"""Root endpoints for the eLKA Studio backend."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/", tags=["Meta"], summary="Backend status")
async def read_root() -> dict[str, str]:
    """Return a lightweight message confirming the API is available."""
    return {
        "message": "eLKA Studio backend is running.",
        "docs": "/docs",
    }
