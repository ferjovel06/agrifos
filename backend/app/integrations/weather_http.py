"""HTTP lifecycle, retries and error translation for weather requests."""

from typing import Any
import asyncio

import httpx

from app.integrations.weather_contracts import (
    WeatherProviderError,
    WeatherProviderRateLimited,
    WeatherProviderTimeout,
    WeatherProviderUnavailable,
)


def _is_retryable(error: httpx.HTTPError) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500
    return isinstance(error, httpx.RequestError)


def _provider_error(error: httpx.HTTPError) -> WeatherProviderError:
    if isinstance(error, httpx.TimeoutException):
        return WeatherProviderTimeout("The weather service took too long to respond.")
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        if status_code == 429:
            return WeatherProviderRateLimited("The weather service rate limit was reached.")
        return WeatherProviderUnavailable(f"The weather service returned HTTP {status_code}.")
    return WeatherProviderUnavailable("The weather service could not be reached.")


def _decode_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise WeatherProviderUnavailable(
            "The weather service returned an invalid response."
        ) from error
    if not isinstance(payload, dict):
        raise WeatherProviderUnavailable(
            "The weather service returned an invalid response."
        )
    return payload


class HttpWeatherTransport:
    def __init__(
        self,
        *,
        attempts: int,
        timeout_seconds: float,
        connect_timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
        cache=None,
    ):
        if attempts < 1:
            raise ValueError("Weather request attempts must be positive.")
        self._attempts = attempts
        self._timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds)
        self._client = client
        self._cache = cache

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if self._client is not None:
            return await self._get(self._client, url, params, headers)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._get(client, url, params, headers)

    async def _get(self, client, url, params, headers):
        if self._cache is not None:
            return await self._cache.get_json(
                url, params, headers,
                lambda conditional: self._response(client, url, params, conditional),
                _decode_json, _provider_error,
            )
        return _decode_json(await self._response(client, url, params, headers))

    async def _response(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        remaining_attempts = self._attempts
        while True:
            remaining_attempts -= 1
            try:
                response = await client.get(url, params=params, headers=headers)
                if response.status_code == 304:
                    return response
                response.raise_for_status()
            except httpx.HTTPError as error:
                if remaining_attempts == 0 or not _is_retryable(error):
                    if self._cache is not None:
                        raise
                    raise _provider_error(error) from error
                await asyncio.sleep(min(2, 0.25 * (self._attempts - remaining_attempts)))
                continue
            return response
