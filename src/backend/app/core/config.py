from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ChargeOpt"
    environment: str = "production"
    log_level: str = "INFO"

    database_url: str
    jwt_secret: str = Field(min_length=32)
    jwt_expire_minutes: int = 480
    cookie_secure: bool = False
    cors_origins: str = ""

    fleet_timezone: str = "UTC"
    currency: str = "USD"

    seed_demo_data: bool = True
    demo_user_password: str | None = Field(default=None, min_length=8)
    integration_api_key: str | None = Field(default=None, min_length=24)
    ocpp_basic_auth_password: str | None = Field(default=None, min_length=12)

    simulation_enabled: bool = True
    simulation_tick_seconds: float = Field(default=5.0, ge=1.0, le=60.0)

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
