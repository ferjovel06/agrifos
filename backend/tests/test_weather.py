import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from app.integrations.weather_provider import (
    FallbackWeatherProvider,
    MetNorwayProvider,
    OpenMeteoProvider,
    WeatherProviderRateLimited,
    WeatherProviderTimeout,
    WeatherProviderUnavailable,
)
from app.routers import weather as router
from app.integrations.weather_http import HttpWeatherTransport
from app.integrations.weather_normalization import OpenMeteoNormalizer, MetNorwayNormalizer
from app.services.weather_service import (
    InvalidWeatherDataError,
    WeatherForecastCache,
    WeatherService,
)


def test_transport(client, attempts=2):
    return HttpWeatherTransport(
        client=client, attempts=attempts, timeout_seconds=15,
        connect_timeout_seconds=5,
    )


def open_meteo(client, base_url="https://weather.test/v1"):
    return OpenMeteoProvider(
        transport=test_transport(client), normalizer=OpenMeteoNormalizer(),
        base_url=base_url,
    )


def met_norway(client):
    return MetNorwayProvider(
        transport=test_transport(client, attempts=1), normalizer=MetNorwayNormalizer(),
        base_url="https://weather.test/met",
        user_agent="Agrifos/0.1 https://github.com/ferjovel06/agrifos",
    )

def provider_payload(days: int = 2):
    dates = [f"2026-09-0{index + 1}" for index in range(days)]
    return {
        "latitude": 12.1,
        "longitude": -86.2,
        "timezone": "America/Managua",
        "current": {
            "time": "2026-09-01T10:00",
            "temperature_2m": 27.4,
            "relative_humidity_2m": 78,
            "precipitation": 0.2,
            "weather_code": 61,
            "wind_speed_10m": 8.5,
        },
        "daily": {
            "time": dates,
            "weather_code": [61] * days,
            "temperature_2m_max": [30.0] * days,
            "temperature_2m_min": [21.0] * days,
            "precipitation_sum": [8.2] * days,
            "precipitation_probability_max": [75] * days,
            "et0_fao_evapotranspiration": [3.1] * days,
        },
    }


def met_norway_payload(days: int = 2):
    timeseries = []
    for day in range(days):
        for hour in (0, 6, 12, 18):
            timeseries.append(
                {
                    "time": f"2026-09-{day + 1:02d}T{hour:02d}:00:00Z",
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": 22.0 + hour / 6,
                                "relative_humidity": 78.4,
                                "wind_speed": 3.5,
                            }
                        },
                        "next_6_hours": {
                            "summary": {"symbol_code": "rain_day"},
                            "details": {
                                "precipitation_amount": 1.5,
                                "probability_of_precipitation": 70.2,
                            },
                        },
                    },
                }
            )
    return {
        "geometry": {"coordinates": [-86.2, 12.1, 90]},
        "properties": {"timeseries": timeseries},
    }


class WeatherTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_errors_follow_retry_policy_and_preserve_the_cause(self):
        for status_code, expected_attempts, error_type in (
            (400, 1, WeatherProviderUnavailable),
            (429, 1, WeatherProviderRateLimited),
            (503, 2, WeatherProviderUnavailable),
        ):
            with self.subTest(status_code=status_code):
                attempts = 0

                async def handler(request):
                    nonlocal attempts
                    attempts += 1
                    return httpx.Response(status_code)

                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    with self.assertRaises(error_type) as raised:
                        await test_transport(client).get_json("https://weather.test", params={})
                    self.assertIsInstance(raised.exception.__cause__, httpx.HTTPStatusError)
                    self.assertFalse(client.is_closed)
                self.assertEqual(attempts, expected_attempts)

    async def test_connection_failure_stops_after_configured_attempts(self):
        attempts = 0

        async def handler(request):
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("offline", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(WeatherProviderUnavailable) as raised:
                await test_transport(client, attempts=3).get_json("https://weather.test", params={})
        self.assertEqual(attempts, 3)
        self.assertIsInstance(raised.exception.__cause__, httpx.ConnectError)


class OpenMeteoProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_invalid_json_and_non_object_responses(self):
        for content in (b"not json", b"[]"):
            with self.subTest(content=content):
                async def handler(request):
                    return httpx.Response(200, content=content)

                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    with self.assertRaises(WeatherProviderUnavailable):
                        await open_meteo(client).fetch_forecast(12.1, -86.2, 2)

    async def test_retries_server_failure_before_success(self):
        attempts = 0

        async def handler(request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(503)
            return httpx.Response(200, json=provider_payload())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await open_meteo(client).fetch_forecast(12.1, -86.2, 2)
        self.assertEqual(attempts, 2)

    async def test_requests_forecast_for_coordinates_and_days(self):
        async def handler(request: httpx.Request):
            self.assertEqual(request.url.params["latitude"], "12.1")
            self.assertEqual(request.url.params["longitude"], "-86.2")
            self.assertEqual(request.url.params["forecast_days"], "2")
            self.assertEqual(request.url.params["timezone"], "auto")
            self.assertIn("precipitation_sum", request.url.params["daily"])
            return httpx.Response(200, json=provider_payload())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = open_meteo(
                client=client,
                base_url="https://weather.test/v1",
            )
            result = await provider.fetch_forecast(12.1, -86.2, 2)

        self.assertEqual(result["timezone"], "America/Managua")

    async def test_translates_provider_timeout(self):
        attempts = 0

        async def handler(request: httpx.Request):
            nonlocal attempts
            attempts += 1
            raise httpx.ReadTimeout("timeout", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = open_meteo(client)
            with self.assertRaises(WeatherProviderTimeout):
                await provider.fetch_forecast(12.1, -86.2, 7)

        self.assertEqual(attempts, 2)

    async def test_retries_a_transient_provider_failure(self):
        attempts = 0

        async def handler(request: httpx.Request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectError("temporary failure", request=request)
            return httpx.Response(200, json=provider_payload())

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            provider = open_meteo(client)
            result = await provider.fetch_forecast(12.1, -86.2, 2)

        self.assertEqual(attempts, 2)
        self.assertEqual(result["timezone"], "America/Managua")

    async def test_does_not_retry_rate_limit_response(self):
        attempts = 0

        async def handler(request: httpx.Request):
            nonlocal attempts
            attempts += 1
            return httpx.Response(429, request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            provider = open_meteo(client)
            with self.assertRaises(WeatherProviderRateLimited):
                await provider.fetch_forecast(12.1, -86.2, 7)

        self.assertEqual(attempts, 1)


class MetNorwayProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_the_shared_rate_limit_error_contract(self):
        async def handler(request):
            return httpx.Response(429)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(WeatherProviderRateLimited):
                await met_norway(client).fetch_forecast(12.1, -86.2, 2)

    async def test_identifies_client_and_normalizes_compact_forecast(self):
        async def handler(request: httpx.Request):
            self.assertEqual(request.url.params["lat"], "12.1")
            self.assertEqual(request.url.params["lon"], "-86.2")
            self.assertEqual(
                request.headers["User-Agent"],
                "Agrifos/0.1 https://github.com/ferjovel06/agrifos",
            )
            return httpx.Response(200, json=met_norway_payload())

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            provider = met_norway(client)
            result = await provider.fetch_forecast(12.1, -86.2, 2)

        self.assertEqual(result["provider"], "MET Norway")
        self.assertAlmostEqual(result["current"]["wind_speed_10m"], 12.6)
        self.assertEqual(result["current"]["relative_humidity_2m"], 78)
        self.assertEqual(result["daily"]["precipitation_sum"], [6.0, 6.0])
        self.assertEqual(len(result["daily"]["time"]), 2)


class MetNorwayNormalizationTests(unittest.TestCase):
    def test_aggregates_each_day_and_limits_the_requested_dates(self):
        payload = met_norway_payload(days=3)
        first_day = payload["properties"]["timeseries"][:4]
        for entry, temperature in zip(first_day, (-1, 5, 12, 3)):
            entry["data"]["instant"]["details"]["air_temperature"] = temperature
        first_day[0]["data"]["next_1_hours"] = {
            "summary": {"symbol_code": "rainandthunder"},
            "details": {"precipitation_amount": 0.25, "probability_of_precipitation": 90.6},
        }
        first_day[1]["data"]["next_12_hours"] = first_day[1]["data"].pop("next_6_hours")
        del first_day[3]["data"]["next_6_hours"]
        result = MetNorwayNormalizer().normalize(payload, 0, 0, 2)
        daily = result["daily"]
        self.assertEqual(daily["time"], ["2026-09-01", "2026-09-02"])
        self.assertEqual(daily["temperature_2m_min"], [-1, 22])
        self.assertEqual(daily["temperature_2m_max"], [12, 25])
        self.assertEqual(daily["precipitation_sum"], [3.25, 6])
        self.assertEqual(daily["precipitation_probability_max"], [91, 70])
        self.assertEqual(daily["weather_code"], [95, 63])
        self.assertEqual(result["current"]["precipitation"], 0.25)
        self.assertEqual((result["latitude"], result["longitude"]), (12.1, -86.2))

    def test_missing_periods_preserve_defaults_and_requested_coordinates(self):
        payload = met_norway_payload(days=1)
        del payload["geometry"]
        for entry in payload["properties"]["timeseries"]:
            del entry["data"]["next_6_hours"]
        result = MetNorwayNormalizer().normalize(payload, 10, -85, 1)
        self.assertEqual((result["latitude"], result["longitude"]), (10, -85))
        self.assertEqual(result["current"]["precipitation"], 0)
        self.assertEqual(result["current"]["weather_code"], 3)
        self.assertEqual(result["daily"]["precipitation_sum"], [0])
        self.assertEqual(result["daily"]["weather_code"], [3])
        self.assertEqual(result["daily"]["precipitation_probability_max"], [None])
        self.assertEqual(result["daily"]["et0_fao_evapotranspiration"], [None])


class WeatherProviderContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_providers_can_be_consumed_by_the_same_service(self):
        for factory, payload, wind_speed in (
            (open_meteo, provider_payload(), 8.5),
            (met_norway, met_norway_payload(), 12.6),
        ):
            with self.subTest(provider=factory.__name__):
                transport = SimpleNamespace(get_json=AsyncMock(return_value=payload))
                if factory is open_meteo:
                    provider = OpenMeteoProvider(
                        transport=transport, normalizer=OpenMeteoNormalizer(),
                        base_url="https://weather.test",
                    )
                else:
                    provider = MetNorwayProvider(
                        transport=transport, normalizer=MetNorwayNormalizer(),
                        base_url="https://weather.test", user_agent="test",
                    )
                farm = SimpleNamespace(id=uuid.uuid4(), name="Test", latitude=12.1, longitude=-86.2)
                forecast = await WeatherService(
                    provider=provider, cache=WeatherForecastCache(),
                ).forecast(farm, 2)
                self.assertEqual(len(forecast.daily), 2)
                self.assertAlmostEqual(forecast.current.wind_speed_kmh, wind_speed)

    async def test_both_providers_reject_a_short_forecast(self):
        for normalizer, payload in (
            (OpenMeteoNormalizer(), provider_payload(days=1)),
            (MetNorwayNormalizer(), met_norway_payload(days=1)),
        ):
            with self.subTest(normalizer=type(normalizer).__name__):
                with self.assertRaises(ValueError):
                    normalizer.normalize(payload, 12.1, -86.2, 2)


class FallbackWeatherProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_primary_forecast_activates_fallback(self):
        transport = SimpleNamespace(get_json=AsyncMock(return_value={"current": {}}))
        primary = OpenMeteoProvider(
            transport=transport, normalizer=OpenMeteoNormalizer(),
            base_url="https://weather.test",
        )
        expected = provider_payload()
        fallback = SimpleNamespace(fetch_forecast=AsyncMock(return_value=expected))
        result = await FallbackWeatherProvider(
            primary=primary, fallback=fallback,
        ).fetch_forecast(12.1, -86.2, 2)
        self.assertIs(result, expected)
        fallback.fetch_forecast.assert_awaited_once_with(12.1, -86.2, 2)

    async def test_reports_failure_when_both_providers_fail(self):
        primary = SimpleNamespace(
            fetch_forecast=AsyncMock(side_effect=WeatherProviderTimeout("timeout"))
        )
        fallback = SimpleNamespace(
            fetch_forecast=AsyncMock(side_effect=WeatherProviderUnavailable("offline"))
        )
        with self.assertRaises(WeatherProviderUnavailable) as raised:
            await FallbackWeatherProvider(
                primary=primary, fallback=fallback,
            ).fetch_forecast(12.1, -86.2, 2)
        self.assertIsInstance(raised.exception.__cause__, WeatherProviderUnavailable)

    async def test_uses_fallback_when_primary_is_rate_limited(self):
        primary = SimpleNamespace(
            fetch_forecast=AsyncMock(
                side_effect=WeatherProviderRateLimited("busy")
            )
        )
        fallback = SimpleNamespace(
            fetch_forecast=AsyncMock(return_value={"provider": "fallback"})
        )
        provider = FallbackWeatherProvider(primary=primary, fallback=fallback)

        result = await provider.fetch_forecast(12.1, -86.2, 7)

        self.assertEqual(result["provider"], "fallback")
        fallback.fetch_forecast.assert_awaited_once_with(12.1, -86.2, 7)

    async def test_does_not_call_fallback_when_primary_succeeds(self):
        primary = SimpleNamespace(
            fetch_forecast=AsyncMock(return_value={"provider": "primary"})
        )
        fallback = SimpleNamespace(fetch_forecast=AsyncMock())
        provider = FallbackWeatherProvider(primary=primary, fallback=fallback)

        result = await provider.fetch_forecast(12.1, -86.2, 7)

        self.assertEqual(result["provider"], "primary")
        fallback.fetch_forecast.assert_not_awaited()


class WeatherServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_data_uses_stale_cache_only_until_its_deadline(self):
        now = 0.0
        provider = SimpleNamespace(fetch_forecast=AsyncMock(return_value=provider_payload()))
        service = WeatherService(
            provider=provider,
            cache=WeatherForecastCache(fresh_seconds=10, stale_seconds=60, clock=lambda: now),
        )
        forecast = await service.forecast(self.farm, 2)
        invalid_payload = provider_payload()
        invalid_payload["current"]["relative_humidity_2m"] = 200
        provider.fetch_forecast.return_value = invalid_payload
        now = 20.0
        self.assertIs(await service.forecast(self.farm, 2), forecast)
        now = 61.0
        with self.assertRaises(InvalidWeatherDataError) as raised:
            await service.forecast(self.farm, 2)
        self.assertIsInstance(raised.exception.__cause__, ValueError)

    async def test_preserves_provider_error_when_no_cached_forecast_exists(self):
        error = WeatherProviderTimeout("timeout")
        provider = SimpleNamespace(fetch_forecast=AsyncMock(side_effect=error))
        service = WeatherService(provider=provider, cache=WeatherForecastCache())
        with self.assertRaises(WeatherProviderTimeout) as raised:
            await service.forecast(self.farm, 2)
        self.assertIs(raised.exception, error)

    def setUp(self):
        self.farm = SimpleNamespace(
            id=uuid.uuid4(),
            name="Finca El Edén",
            latitude=12.1,
            longitude=-86.2,
        )

    async def test_normalizes_current_and_daily_forecast(self):
        provider = SimpleNamespace(
            fetch_forecast=AsyncMock(return_value=provider_payload())
        )
        result = await WeatherService(provider=provider).forecast(self.farm, 2)

        provider.fetch_forecast.assert_awaited_once_with(
            latitude=12.1,
            longitude=-86.2,
            days=2,
        )
        self.assertEqual(result.farm_id, self.farm.id)
        self.assertEqual(result.current.condition, "Lluvia")
        self.assertEqual(result.daily[0].precipitation_probability_pct, 75)
        self.assertEqual(len(result.daily), 2)

    async def test_rejects_incomplete_daily_forecast(self):
        payload = provider_payload(days=1)
        provider = SimpleNamespace(fetch_forecast=AsyncMock(return_value=payload))

        with self.assertRaises(InvalidWeatherDataError):
            await WeatherService(
                provider=provider,
                cache=WeatherForecastCache(),
            ).forecast(self.farm, 2)

    async def test_reuses_a_fresh_cached_forecast(self):
        provider = SimpleNamespace(
            fetch_forecast=AsyncMock(return_value=provider_payload())
        )
        service = WeatherService(
            provider=provider,
            cache=WeatherForecastCache(),
        )

        first = await service.forecast(self.farm, 2)
        second = await service.forecast(self.farm, 2)

        self.assertIs(second, first)
        provider.fetch_forecast.assert_awaited_once()

    async def test_returns_stale_cache_during_provider_failure(self):
        now = 0.0
        provider = SimpleNamespace(
            fetch_forecast=AsyncMock(return_value=provider_payload())
        )
        cache = WeatherForecastCache(
            fresh_seconds=10,
            stale_seconds=60,
            clock=lambda: now,
        )
        service = WeatherService(provider=provider, cache=cache)
        first = await service.forecast(self.farm, 2)
        now = 20.0
        provider.fetch_forecast.side_effect = WeatherProviderUnavailable(
            "rate limited"
        )

        second = await service.forecast(self.farm, 2)

        self.assertIs(second, first)


class WeatherRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4(), role="farmer")
        self.farm = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=self.user.id,
            name="Finca El Edén",
            latitude=12.1,
            longitude=-86.2,
        )
        self.db = AsyncMock()

    async def test_returns_forecast_for_owned_farm(self):
        expected = SimpleNamespace(provider="Open-Meteo")
        service = SimpleNamespace(forecast=AsyncMock(return_value=expected))
        with patch.object(
            router.farm_repo,
            "get_farm",
            AsyncMock(return_value=self.farm),
        ):
            result = await router.get_farm_forecast(
                farm_id=self.farm.id,
                days=7,
                current_user=self.user,
                db=self.db,
                service=service,
            )

        self.assertIs(result, expected)
        service.forecast.assert_awaited_once_with(self.farm, 7)

    async def test_rejects_foreign_farm(self):
        foreign_farm = SimpleNamespace(
            **{**self.farm.__dict__, "user_id": uuid.uuid4()}
        )
        service = SimpleNamespace(forecast=AsyncMock())
        with patch.object(
            router.farm_repo,
            "get_farm",
            AsyncMock(return_value=foreign_farm),
        ):
            with self.assertRaises(HTTPException) as raised:
                await router.get_farm_forecast(
                    farm_id=self.farm.id,
                    days=7,
                    current_user=self.user,
                    db=self.db,
                    service=service,
                )

        self.assertEqual(raised.exception.status_code, 403)
        service.forecast.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
