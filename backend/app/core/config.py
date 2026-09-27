"""Application configuration — secrets never leave the backend."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[3]
_ENV_CANDIDATES = (
    _ROOT / ".env",
    Path.cwd() / ".env",
    Path(__file__).resolve().parents[2] / ".env",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=tuple(str(p) for p in _ENV_CANDIDATES if p.exists()) or ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "DEX Trading Platform"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "dex_trading"

    # Auth
    jwt_secret: str = Field(default="change-me-to-a-long-random-secret-key-32+")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    admin_email: str = "admin@localhost"
    admin_password: str = "ChangeMeNow!123"

    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: Optional[str] = None

    # DEX
    dex_provider: Literal["paper", "mock", "oneinch", "delta"] = "delta"
    dex_api_key: Optional[str] = None
    dex_base_url: Optional[str] = "https://api.india.delta.exchange"
    # Delta Exchange credentials (server-side only — never sent to frontend/OpenAI)
    delta_api_key: Optional[str] = None
    delta_api_secret: Optional[str] = None
    delta_live_trading: bool = False
    chain_id: int = 1
    wallet_private_key: Optional[str] = None
    rpc_url: Optional[str] = None

    # Trading defaults — Delta symbols. XAUTUSD is Tether Gold.
    trading_mode: Literal["PAPER", "MANUAL_APPROVAL", "AUTO"] = "PAPER"
    trading_pairs: str = "XAUTUSD,BTCUSD,ETHUSD"
    paper_starting_balance: float = 100_000.0
    market_poll_seconds: int = 15
    engine_cycle_seconds: int = 30
    market_stale_seconds: int = 60

    # Risk defaults
    max_position_size_usd: float = 1_000.0
    max_daily_loss_usd: float = 500.0
    max_trades_per_day: int = 20
    max_portfolio_exposure_pct: float = 50.0
    stop_loss_pct: float = 3.0
    take_profit_pct: float = 6.0
    max_slippage_bps: int = 100
    min_liquidity_usd: float = 10_000.0
    max_gas_usd: float = 25.0
    min_confidence: float = 60.0
    max_open_positions: int = 5

    log_level: str = "INFO"

    # WhatsApp notifications (optional — off by default)
    whatsapp_enabled: bool = False
    whatsapp_to: str = "6206240867"  # normalized to +91… for 10-digit IN numbers
    whatsapp_provider: Literal["twilio", "meta", "callmebot"] = "callmebot"
    # Twilio
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_whatsapp_from: Optional[str] = None  # e.g. whatsapp:+14155238886
    # Meta Cloud API
    whatsapp_meta_token: Optional[str] = None
    whatsapp_meta_phone_id: Optional[str] = None
    # CallMeBot (https://www.callmebot.com/blog/free-api-whatsapp-messages/)
    callmebot_apikey: Optional[str] = None

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def whatsapp_to_e164(self) -> str:
        from app.services.notify.whatsapp import normalize_phone

        return normalize_phone(self.whatsapp_to)

    @property
    def pair_list(self) -> List[str]:
        return [p.strip() for p in self.trading_pairs.split(",") if p.strip()]

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    def validate_production(self) -> None:
        if self.environment != "production":
            return
        if "change-me" in self.jwt_secret.lower():
            raise RuntimeError("JWT_SECRET must be a strong secret in production")
        if self.admin_password == "ChangeMeNow!123":
            raise RuntimeError("ADMIN_PASSWORD must be changed in production")
        if (
            self.trading_mode == "AUTO"
            and self.dex_provider == "delta"
            and self.delta_live_trading
            and not (self.delta_api_key and self.delta_api_secret)
        ):
            raise RuntimeError("DELTA_API_KEY and DELTA_API_SECRET required for live AUTO trading")
        if (
            self.trading_mode == "AUTO"
            and self.dex_provider not in ("paper", "delta", "mock")
            and not self.wallet_private_key
        ):
            raise RuntimeError("WALLET_PRIVATE_KEY required for live AUTO trading")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    return settings
