"""Compose the concrete weather adapters at the application boundary."""

from app.core.config import settings
from app.integrations.weather_http import HttpWeatherTransport
from app.integrations.weather_normalization import MetNorwayNormalizer, OpenMeteoNormalizer
from app.integrations.weather_provider import (
    FallbackWeatherProvider, MetNorwayProvider, OpenMeteoProvider,
)
from app.services.weather_service import WeatherForecastCache, WeatherService
from app.services.weather_http_cache import PersistentWeatherHttpCache, PersistentForecastCache
from app.db.session import AsyncSessionLocal


_forecast_cache = WeatherForecastCache(
    fresh_seconds=settings.WEATHER_CACHE_FRESH_SECONDS,
    stale_seconds=settings.WEATHER_CACHE_STALE_SECONDS,
    retry_seconds=settings.WEATHER_CACHE_RETRY_SECONDS,
)
_http_cache = PersistentWeatherHttpCache(
    AsyncSessionLocal, fresh_seconds=settings.WEATHER_CACHE_FRESH_SECONDS,
    stale_seconds=settings.WEATHER_CACHE_STALE_SECONDS,
    retry_seconds=settings.WEATHER_CACHE_RETRY_SECONDS,
)
_normalized_cache = PersistentForecastCache(
    AsyncSessionLocal,
    namespace=(settings.WEATHER_API_BASE_URL, settings.WEATHER_FALLBACK_API_BASE_URL),
    max_concurrent=max(1, settings.DB_POOL_SIZE // 2),
    fresh_seconds=settings.WEATHER_CACHE_FRESH_SECONDS,
    stale_seconds=settings.WEATHER_CACHE_STALE_SECONDS,
    retry_seconds=settings.WEATHER_CACHE_RETRY_SECONDS,
)


def get_weather_service() -> WeatherService:
    def transport(attempts: int) -> HttpWeatherTransport:
        return HttpWeatherTransport(
            attempts=attempts,
            timeout_seconds=settings.WEATHER_TIMEOUT_SECONDS,
            connect_timeout_seconds=settings.WEATHER_CONNECT_TIMEOUT_SECONDS,
            cache=_http_cache,
        )

    primary = OpenMeteoProvider(
        transport=transport(settings.WEATHER_REQUEST_ATTEMPTS),
        normalizer=OpenMeteoNormalizer(), base_url=settings.WEATHER_API_BASE_URL,
    )
    fallback = MetNorwayProvider(
        transport=transport(settings.WEATHER_FALLBACK_REQUEST_ATTEMPTS),
        normalizer=MetNorwayNormalizer(),
        base_url=settings.WEATHER_FALLBACK_API_BASE_URL,
        user_agent=settings.WEATHER_FALLBACK_USER_AGENT,
    )
    return WeatherService(
        provider=FallbackWeatherProvider(primary=primary, fallback=fallback),
        cache=_forecast_cache,
        persistent=True,
        persistent_cache=_normalized_cache,
    )
