"""Translate MET Norway symbols into the codes consumed by Agrifos.

These are adapter compatibility rules, not configurable agronomic thresholds.
The conversion is approximate: MET symbols and WMO codes do not have a
one-to-one correspondence. Preserve the existing grouping and fallback.
"""

from enum import IntEnum


class WeatherCode(IntEnum):
    CLEAR_SKY = 0
    MAINLY_CLEAR = 1
    PARTLY_CLOUDY = 2
    OVERCAST = 3
    FOG = 45
    MODERATE_RAIN = 63
    HEAVY_RAIN = 65
    HEAVY_FREEZING_RAIN = 67
    MODERATE_SNOW = 73
    HEAVY_SNOW = 75
    MODERATE_RAIN_SHOWERS = 81
    HEAVY_RAIN_SHOWERS = 82
    SLIGHT_SNOW_SHOWERS = 85
    THUNDERSTORM = 95


# First match wins: thunder and showers must precede rain/snow matches.
# Sleet retains the legacy freezing-rain approximation for compatibility.
_SYMBOL_RULES: tuple[tuple[str, WeatherCode], ...] = (
    ("thunder", WeatherCode.THUNDERSTORM),
    ("heavyrainshowers", WeatherCode.HEAVY_RAIN_SHOWERS),
    ("rainshowers", WeatherCode.MODERATE_RAIN_SHOWERS),
    ("snowshowers", WeatherCode.SLIGHT_SNOW_SHOWERS),
    ("sleet", WeatherCode.HEAVY_FREEZING_RAIN),
    ("heavyrain", WeatherCode.HEAVY_RAIN),
    ("rain", WeatherCode.MODERATE_RAIN),
    ("heavysnow", WeatherCode.HEAVY_SNOW),
    ("snow", WeatherCode.MODERATE_SNOW),
    ("fog", WeatherCode.FOG),
    ("partlycloudy", WeatherCode.PARTLY_CLOUDY),
    ("cloudy", WeatherCode.OVERCAST),
    ("fair", WeatherCode.MAINLY_CLEAR),
    ("clearsky", WeatherCode.CLEAR_SKY),
)


def met_weather_code(symbol: str | None) -> int:
    """Normalize time-of-day suffixes and apply ordered compatibility rules."""
    base = (symbol or "").removesuffix("_day").removesuffix("_night").removesuffix(
        "_polartwilight"
    )
    for fragment, code in _SYMBOL_RULES:
        if fragment in base:
            return int(code)
    return int(WeatherCode.OVERCAST)
