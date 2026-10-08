from dataclasses import dataclass
from datetime import date, datetime
from time import monotonic
from typing import Any, Callable

from app.integrations.weather_contracts import (
    WeatherProvider,
    WeatherProviderError,
)
from app.models import Farm
from app.schemas.weather import (
    CurrentWeatherRead,
    DailyWeatherRead,
    WeatherForecastRead,
)


class InvalidWeatherDataError(RuntimeError):
    pass


@dataclass
class _CachedForecast:
    forecast: WeatherForecastRead
    fresh_until: float
    stale_until: float


class WeatherForecastCache:
    def __init__(
        self,
        fresh_seconds: float = 30 * 60,
        stale_seconds: float = 6 * 60 * 60,
        clock: Callable[[], float] = monotonic,
    ):
        self._fresh_seconds = fresh_seconds
        self._stale_seconds = stale_seconds
        self._clock = clock
        self._entries: dict[tuple[str, float, float, int], _CachedForecast] = {}

    def get(
        self,
        key: tuple[str, float, float, int],
        *,
        allow_stale: bool = False,
    ) -> WeatherForecastRead | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        deadline = entry.stale_until if allow_stale else entry.fresh_until
        if self._clock() <= deadline:
            return entry.forecast
        if self._clock() > entry.stale_until:
            self._entries.pop(key, None)
        return None

    def put(
        self,
        key: tuple[str, float, float, int],
        forecast: WeatherForecastRead,
    ) -> None:
        now = self._clock()
        self._entries[key] = _CachedForecast(
            forecast=forecast,
            fresh_until=now + self._fresh_seconds,
            stale_until=now + self._stale_seconds,
        )


_shared_forecast_cache = WeatherForecastCache()


class WeatherService:
    def __init__(
        self,
        provider: WeatherProvider,
        cache: WeatherForecastCache | None = None,
    ):
        self._provider = provider
        self._cache = cache or _shared_forecast_cache

    async def forecast(self, farm: Farm, days: int) -> WeatherForecastRead:
        cache_key = (str(farm.id), farm.latitude, farm.longitude, days)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            forecast = await self._load_forecast(farm, days)
        except (WeatherProviderError, InvalidWeatherDataError):
            stale = self._cache.get(cache_key, allow_stale=True)
            if stale is not None:
                return stale
            raise

        self._cache.put(cache_key, forecast)
        return forecast

    async def _load_forecast(self, farm: Farm, days: int) -> WeatherForecastRead:
        try:
            payload = await self._provider.fetch_forecast(
                latitude=farm.latitude,
                longitude=farm.longitude,
                days=days,
            )
            return _build_forecast(payload, farm, days)
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidWeatherDataError(
                "The weather provider returned incomplete forecast data."
            ) from error


def _build_forecast(
    payload: dict[str, Any], farm: Farm, days: int,
) -> WeatherForecastRead:
    return WeatherForecastRead(
        farm_id=farm.id,
        farm_name=farm.name,
        provider=payload.get("provider", "Open-Meteo"),
        latitude=payload.get("latitude", farm.latitude),
        longitude=payload.get("longitude", farm.longitude),
        timezone=payload["timezone"],
        current=_current_conditions(payload["current"]),
        daily=_daily_forecast(payload["daily"], days),
    )


def _current_conditions(values: dict[str, Any]) -> CurrentWeatherRead:
    return CurrentWeatherRead(
        observed_at=datetime.fromisoformat(values["time"]),
        temperature_c=values["temperature_2m"],
        relative_humidity_pct=values["relative_humidity_2m"],
        precipitation_mm=values["precipitation"],
        weather_code=values["weather_code"],
        condition=weather_condition(values["weather_code"]),
        wind_speed_kmh=values["wind_speed_10m"],
    )


def _daily_forecast(
    values: dict[str, list[Any]], requested_days: int,
) -> list[DailyWeatherRead]:
    fields = (
        "time", "weather_code", "temperature_2m_max", "temperature_2m_min",
        "precipitation_sum", "precipitation_probability_max",
        "et0_fao_evapotranspiration",
    )
    if any(not isinstance(values.get(field), list) for field in fields):
        raise InvalidWeatherDataError("The weather provider returned incomplete daily data.")
    if any(len(values[field]) < requested_days for field in fields):
        raise InvalidWeatherDataError("The weather provider returned fewer days than requested.")
    daily = []
    for index in range(requested_days):
        day = {field: values[field][index] for field in fields}
        daily.append(_daily_conditions(day))
    return daily


def _daily_conditions(values: dict[str, Any]) -> DailyWeatherRead:
    return DailyWeatherRead(
        date=date.fromisoformat(values["time"]),
        weather_code=values["weather_code"],
        condition=weather_condition(values["weather_code"]),
        temperature_max_c=values["temperature_2m_max"],
        temperature_min_c=values["temperature_2m_min"],
        precipitation_mm=values["precipitation_sum"],
        precipitation_probability_pct=values["precipitation_probability_max"],
        reference_evapotranspiration_mm=values["et0_fao_evapotranspiration"],
    )


_WEATHER_CONDITIONS: dict[int, str] = {
    0: "Despejado",
    1: "Parcialmente nublado",
    2: "Parcialmente nublado",
    3: "Nublado",
    **dict.fromkeys((45, 48), "Niebla"),
    **dict.fromkeys(range(51, 58), "Llovizna"),
    **dict.fromkeys(range(61, 68), "Lluvia"),
    **dict.fromkeys(range(71, 78), "Nieve"),
    **dict.fromkeys(range(80, 83), "Chubascos"),
    **dict.fromkeys(range(85, 87), "Chubascos de nieve"),
    **dict.fromkeys(range(95, 100), "Tormenta eléctrica"),
}


def weather_condition(code: int) -> str:
    return _WEATHER_CONDITIONS.get(code, "Condición desconocida")
