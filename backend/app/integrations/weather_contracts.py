"""Small contracts shared by weather adapters and their consumers."""

from typing import Any, Protocol


class WeatherProviderError(RuntimeError):
    """Base error raised when the meteorological provider cannot be used."""


class WeatherProviderTimeout(WeatherProviderError):
    pass


class WeatherProviderUnavailable(WeatherProviderError):
    pass


class WeatherProviderRateLimited(WeatherProviderUnavailable):
    pass


class WeatherProvider(Protocol):
    async def fetch_forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> dict[str, Any]:
        """Return normalized current/daily data or raise WeatherProviderError.

        Temperatures are Celsius, precipitation is mm, and wind is km/h.
        Optional unavailable measurements are represented by None.
        """
        ...


class WeatherTransport(Protocol):
    async def get_json(
        self, url: str, *, params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...


class ForecastNormalizer(Protocol):
    def normalize(
        self, payload: dict[str, Any], latitude: float, longitude: float,
        days: int,
    ) -> dict[str, Any]: ...
