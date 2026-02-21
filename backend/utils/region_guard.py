from fastapi import HTTPException

from backend.config import settings


def ensure_region_local(region: str):
    if settings.local_region and settings.local_region != region:
        raise HTTPException(
            status_code=409,
            detail=f"Cross-region write blocked. Local region={settings.local_region}, request region={region}",
        )
