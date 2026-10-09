"""Weather adapters and provider failover; concrete wiring lives in dependencies."""

import logging
import math
from typing import Any

from app.integrations.weather_contracts import (
    ForecastNormalizer, WeatherTransport, WeatherProvider, WeatherProviderError,
    WeatherProviderRateLimited, WeatherProviderTimeout, WeatherProviderUnavailable,
)

# Preserve existing import paths for consumers of the provider contract/errors.
__all__ = [
    "OpenMeteoProvider", "MetNorwayProvider", "FallbackWeatherProvider",
    "WeatherProvider", "WeatherProviderError", "WeatherProviderRateLimited",
    "WeatherProviderTimeout", "WeatherProviderUnavailable",
]

logger = logging.getLogger(__name__)


async def _fetch_normalized(
    transport: WeatherTransport, normalizer: ForecastNormalizer,
    url: str, params: dict[str, Any], latitude: float, longitude: float,
    days: int, headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = await transport.get_json(url, params=params, headers=headers)
    try:
        normalized = normalizer.normalize(payload, latitude, longitude, days)
        if "_agrifos_cache" in payload:
            normalized["_agrifos_cache"] = payload["_agrifos_cache"]
        if "properties" in payload:
            normalized["generated_at"] = payload["properties"].get("meta", {}).get("updated_at")
        return normalized
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        raise WeatherProviderUnavailable(
            "The weather service returned invalid forecast data."
        ) from error


class OpenMeteoProvider:
    """Build Open-Meteo requests using injected transport and normalization."""

    _CURRENT_FIELDS = (
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "weather_code",
        "wind_speed_10m",
    )
    _DAILY_FIELDS = (
        "weather_code",
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_sum",
        "precipitation_probability_max",
        "et0_fao_evapotranspiration",
    )

    def __init__(
        self, *, transport: WeatherTransport, normalizer: ForecastNormalizer,
        base_url: str,
    ):
        self._transport = transport
        self._normalizer = normalizer
        self._base_url = base_url.rstrip("/")

    async def fetch_forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> dict[str, Any]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(self._CURRENT_FIELDS),
            "daily": ",".join(self._DAILY_FIELDS),
            "timezone": "auto",
            "forecast_days": days,
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }
        return await _fetch_normalized(
            self._transport, self._normalizer, f"{self._base_url}/forecast",
            params, latitude, longitude, days,
        )


class MetNorwayProvider:
    """Build MET Norway requests using injected transport and normalization."""

    def __init__(
        self, *, transport: WeatherTransport, normalizer: ForecastNormalizer,
        base_url: str, user_agent: str,
    ):
        self._transport = transport
        self._normalizer = normalizer
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent

    async def fetch_forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> dict[str, Any]:
        params = {
            "lat": math.trunc(latitude * 10000) / 10000,
            "lon": math.trunc(longitude * 10000) / 10000,
        }
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }
        return await _fetch_normalized(
            self._transport, self._normalizer, f"{self._base_url}/compact",
            params, latitude, longitude, days, headers,
        )


class FallbackWeatherProvider:
    """Try any two providers implementing the normalized forecast contract."""

    def __init__(self, *, primary: WeatherProvider, fallback: WeatherProvider):
        self._primary = primary
        self._fallback = fallback

    async def fetch_forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> dict[str, Any]:
        try:
            return await self._primary.fetch_forecast(latitude, longitude, days)
        except WeatherProviderError as primary_error:
            logger.warning(
                "Primary weather provider failed; using fallback: %s",
                primary_error,
            )
            try:
                return await self._fallback.fetch_forecast(latitude, longitude, days)
            except WeatherProviderError as fallback_error:
                raise WeatherProviderUnavailable(
                    "Both weather services are temporarily unavailable."
                ) from fallback_error
