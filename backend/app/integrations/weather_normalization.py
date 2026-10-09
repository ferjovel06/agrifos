"""Provider payload conversion and shared forecast contract validation."""

from datetime import datetime
from typing import Any

from app.integrations.met_weather_codes import WeatherCode, met_weather_code


def validate_forecast(payload: dict[str, Any], days: int) -> dict[str, Any]:
    current = payload["current"]
    for field in (
        "time", "temperature_2m", "relative_humidity_2m", "precipitation",
        "weather_code", "wind_speed_10m",
    ):
        if current[field] is None:
            raise ValueError(f"Missing current weather value: {field}")
    if not isinstance(payload["timezone"], str):
        raise ValueError("Missing weather timezone.")
    daily = payload["daily"]
    for field in (
        "time", "weather_code", "temperature_2m_max", "temperature_2m_min",
        "precipitation_sum", "precipitation_probability_max",
        "et0_fao_evapotranspiration",
    ):
        values = daily[field]
        if not isinstance(values, list) or len(values) < days:
            raise ValueError(f"Incomplete daily weather values: {field}")
    return payload


class OpenMeteoNormalizer:
    def normalize(
        self, payload: dict[str, Any], latitude: float, longitude: float,
        days: int,
    ) -> dict[str, Any]:
        return validate_forecast(payload, days)


class MetNorwayNormalizer:
    def normalize(
        self,
        payload: dict[str, Any],
        latitude: float,
        longitude: float,
        days: int,
    ) -> dict[str, Any]:
        timeseries = payload["properties"]["timeseries"]
        if not isinstance(timeseries, list) or not timeseries:
            raise ValueError("The fallback forecast has no time series.")

        coordinates = payload.get("geometry", {}).get("coordinates", [])
        if len(coordinates) >= 2:
            longitude, latitude = coordinates[:2]
        normalized = {
            "provider": "MET Norway",
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "UTC",
            "current": self._current_conditions(timeseries[0]),
            "daily": self._daily_forecast(timeseries, days),
        }
        return validate_forecast(normalized, days)

    def _current_conditions(self, entry: dict[str, Any]) -> dict[str, Any]:
        details = entry["data"]["instant"]["details"]
        period = _met_period(entry["data"]) or {}
        period_details = period.get("details", {})
        symbol = period.get("summary", {}).get("symbol_code")
        return {
            "time": entry["time"],
            "temperature_2m": details["air_temperature"],
            "relative_humidity_2m": round(details["relative_humidity"]),
            "precipitation": period_details.get("precipitation_amount", 0.0),
            "weather_code": met_weather_code(symbol),
            "wind_speed_10m": details["wind_speed"] * 3.6,
        }

    def _daily_forecast(
        self, timeseries: list[dict[str, Any]], days: int,
    ) -> dict[str, list[Any]]:
        entries_by_day: dict[str, list[dict[str, Any]]] = {}
        for entry in timeseries:
            day = _parse_met_time(entry["time"]).date().isoformat()
            if day not in entries_by_day and len(entries_by_day) >= days:
                continue
            entries_by_day.setdefault(day, []).append(entry)

        daily: dict[str, list[Any]] = {
            "time": [],
            "weather_code": [],
            "temperature_2m_max": [],
            "temperature_2m_min": [],
            "precipitation_sum": [],
            "precipitation_probability_max": [],
            "et0_fao_evapotranspiration": [],
        }
        for day, entries in entries_by_day.items():
            daily["time"].append(day)
            for field, value in self._daily_summary(entries).items():
                daily[field].append(value)
        return daily

    def _daily_summary(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        temperatures = []
        precipitation = 0.0
        probabilities = []
        weather_codes = []
        for entry in entries:
            temperatures.append(entry["data"]["instant"]["details"]["air_temperature"])
            period = _met_period(entry["data"])
            if period is None:
                continue
            details = period.get("details", {})
            precipitation += details.get("precipitation_amount", 0.0)
            probability = details.get("probability_of_precipitation")
            if probability is not None:
                probabilities.append(round(probability))
            symbol = period.get("summary", {}).get("symbol_code")
            if symbol:
                weather_codes.append(met_weather_code(symbol))
        return {
            "weather_code": _representative_weather_code(weather_codes),
            "temperature_2m_max": max(temperatures),
            "temperature_2m_min": min(temperatures),
            "precipitation_sum": round(precipitation, 2),
            "precipitation_probability_max": max(probabilities, default=None),
            "et0_fao_evapotranspiration": None,
        }


def _parse_met_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _met_period(data: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("next_1_hours", "next_6_hours", "next_12_hours"):
        period = data.get(key)
        if isinstance(period, dict):
            return period
    return None


def _representative_weather_code(codes: list[int]) -> int:
    return max(codes, default=int(WeatherCode.OVERCAST))
