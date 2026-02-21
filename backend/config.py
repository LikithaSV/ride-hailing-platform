from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GoComet DAW Ride Hailing"
    env: str = "dev"
    api_prefix: str = "/v1"

    database_url: str = "sqlite:///./ride_hailing.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False

    default_search_radius_km: float = 8.0
    assignment_offer_timeout_sec: int = 20
    surge_base: float = 1.0
    surge_max: float = 3.0

    cors_origins: str = "*"

    new_relic_app_name: str = "ride-hailing-platform"
    new_relic_enabled: bool = False

    payment_provider: str = "cashfree"
    cashfree_enabled: bool = False
    cashfree_base_url: str = "https://sandbox.cashfree.com/pg"
    cashfree_api_version: str = "2023-08-01"
    cashfree_app_id: str = ""
    cashfree_secret_key: str = ""
    cashfree_return_url: str = "https://example.com/payment/return"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
