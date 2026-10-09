from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENV: str = "development"
    APP_DEBUG: bool = True

    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 300

    SUPABASE_URL: str
    AUTH_PROVIDER: Literal["supabase", "native"] = "supabase"
    AUTH_JWT_SECRET: SecretStr = SecretStr("")
    AUTH_JWT_ISSUER: str = "agrifos"
    AUTH_JWT_AUDIENCE: str = "agrifos-api"
    AUTH_ACCESS_TOKEN_SECONDS: int = Field(default=900, gt=0)
    AUTH_MAX_LOGIN_ATTEMPTS: int = Field(default=5, gt=0)
    AUTH_LOGIN_LOCK_SECONDS: int = Field(default=900, gt=0)
    WEATHER_TIMEOUT_SECONDS: float = Field(default=15.0, gt=0)
    WEATHER_CONNECT_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)
    WEATHER_REQUEST_ATTEMPTS: int = Field(default=2, ge=1)
    WEATHER_FALLBACK_REQUEST_ATTEMPTS: int = Field(default=1, ge=1)
    WEATHER_CACHE_FRESH_SECONDS: float = Field(default=1800, gt=0)
    WEATHER_CACHE_STALE_SECONDS: float = Field(default=21600, gt=0)
    WEATHER_CACHE_RETRY_SECONDS: float = Field(default=60, gt=0)
    WEATHER_API_BASE_URL: str = "https://api.open-meteo.com/v1"
    WEATHER_FALLBACK_API_BASE_URL: str = (
        "https://api.met.no/weatherapi/locationforecast/2.0"
    )
    WEATHER_FALLBACK_USER_AGENT: str = (
        "Agrifos/0.1 https://github.com/ferjovel06/agrifos"
    )
    ALLOWED_ORIGINS: str = ""

    @model_validator(mode="after")
    def validate_native_auth(self):
        if self.AUTH_PROVIDER == "native" and len(self.AUTH_JWT_SECRET.get_secret_value().encode()) < 32:
            raise ValueError("Native authentication requires a JWT secret of at least 32 bytes.")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
