from __future__ import annotations

from app.core.config import Settings
from app.services.dex.base import DexClient
from app.services.dex.delta import DeltaExchangeClient
from app.services.dex.oneinch import OneInchDexClient
from app.services.dex.paper import MockVolatileDexClient, PaperDexClient


def create_dex_client(settings: Settings) -> DexClient:
    if settings.dex_provider == "delta":
        return DeltaExchangeClient(settings)
    if settings.dex_provider == "oneinch":
        return OneInchDexClient(settings)
    if settings.dex_provider == "mock":
        return MockVolatileDexClient()
    return PaperDexClient()
