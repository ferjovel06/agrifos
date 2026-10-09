"""Cross-worker HTTP cache in the existing PostgreSQL database.

Only public provider responses are shared; farm IDs/names and tokens never enter
this cache. A transaction advisory lock deduplicates equivalent requests across
workers and restarts. Provider deadlines and failures are persisted as well.
"""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Callable

from sqlalchemy import text

from app.integrations.weather_contracts import WeatherProviderError, WeatherProviderUnavailable
from app.models.offline import WeatherHttpCache
from app.routers.offline import advisory_key
from app.schemas.weather import WeatherForecastRead
from app.services.weather_service import InvalidWeatherDataError
import uuid
import asyncio


def http_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def retry_deadline(value: str | None, now: datetime) -> datetime | None:
    if value is None:
        return None
    try:
        seconds = max(0, int(value))
        return now + timedelta(seconds=min(seconds, 7 * 86400))
    except (ValueError, OverflowError):
        return http_date(value)


class PersistentWeatherHttpCache:
    def __init__(self, sessions, *, fresh_seconds=1800, stale_seconds=21600,
                 retry_seconds=60, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.sessions, self.clock = sessions, clock
        self.fresh_seconds, self.stale_seconds, self.retry_seconds = fresh_seconds, stale_seconds, retry_seconds

    async def get_json(self, url, params, headers, request, decode, translate):
        key = hashlib.sha256(json.dumps({"url": url, "params": params, "format": 1},
                                       sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        async with self.sessions() as db:
            await db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                             {"key": advisory_key(f"weather:{key}")})
            entry = await db.get(WeatherHttpCache, key)
            if entry is None:
                entry = WeatherHttpCache(key=key, failures=0)
                db.add(entry)
            now = self.clock()
            if entry.payload is not None and entry.fresh_until is not None and now < entry.fresh_until:
                return self._result(entry, now)
            if entry.retry_at is not None and now < entry.retry_at:
                if entry.payload is not None:
                    return self._result(entry, now, failed=True)
                raise WeatherProviderUnavailable("Weather provider is in a controlled retry wait.")
            conditional = dict(headers or {})
            if entry.last_modified:
                conditional["If-Modified-Since"] = entry.last_modified
            try:
                response = await request(conditional)
                if response.status_code == 304:
                    if entry.payload is None:
                        raise WeatherProviderUnavailable("304 without previously cached forecast.")
                else:
                    response.raise_for_status()
                    entry.payload = decode(response)
                    entry.fetched_at = now
                entry.last_modified = response.headers.get("last-modified", entry.last_modified)
                entry.validated_at = now
                entry.fresh_until = max(now + timedelta(seconds=self.fresh_seconds),
                                        http_date(response.headers.get("expires")) or now)
                entry.retry_at, entry.error_code, entry.failures = None, None, 0
            except Exception as error:
                import httpx
                if isinstance(error, httpx.HTTPError):
                    provider_error = translate(error)
                elif isinstance(error, WeatherProviderError):
                    provider_error = error
                else:
                    raise
                entry.failures += 1
                entry.error_code = type(provider_error).__name__
                response = error.response if isinstance(error, httpx.HTTPStatusError) else None
                exponential = min(3600, self.retry_seconds * 2 ** min(entry.failures - 1, 6))
                # Stable key-based jitter avoids synchronized storms across locations.
                jitter = int(key[:4], 16) % max(1, int(self.retry_seconds / 4))
                entry.retry_at = max(now + timedelta(seconds=exponential + jitter),
                                     retry_deadline(response.headers.get("retry-after"), now)
                                     or now if response is not None else now)
                await db.commit()
                if entry.payload is None:
                    raise provider_error from error
                return self._result(entry, now, failed=True)
            await db.commit()
            return self._result(entry, now)

    def _result(self, entry, now, failed=False):
        age = (now - entry.fetched_at).total_seconds()
        freshness = "historical" if age >= self.stale_seconds else (
            "stale" if failed or now >= entry.fresh_until else "fresh")
        return {**entry.payload, "_agrifos_cache": {
            "updated_at": entry.fetched_at.isoformat(),
            "consulted_at": now.isoformat(),
            "validated_at": entry.validated_at.isoformat(),
            "fresh_until": entry.fresh_until.isoformat(),
            "freshness": freshness,
        }}


class PersistentForecastCache(PersistentWeatherHttpCache):
    """Cache the chosen fallback result, so a fresh MET forecast also prevents
    repeated attempts against a failing primary provider during its lifetime.
    """
    def __init__(self, sessions, *, namespace, max_concurrent=4, **options):
        super().__init__(sessions, **options)
        self.namespace = namespace
        self._slots = asyncio.Semaphore(max_concurrent)

    async def get_or_load(self, coordinates, load):
        # Bound nested normalized/HTTP transactions before acquiring a pooled
        # connection; waiting refreshes cannot exhaust their own connection pool.
        async with self._slots:
            return await self._get_or_load(coordinates, load)

    async def _get_or_load(self, coordinates, load):
        key = hashlib.sha256(json.dumps(["normalized-forecast-v1", self.namespace, coordinates],
                                        sort_keys=True).encode()).hexdigest()
        async with self.sessions() as db:
            await db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                             {"key": advisory_key(f"forecast:{key}")})
            entry = await db.get(WeatherHttpCache, key)
            now = self.clock()
            if entry is not None and entry.payload is not None:
                if entry.fresh_until is not None and now < entry.fresh_until:
                    return self._forecast(entry, now)
                if entry.retry_at is not None and now < entry.retry_at:
                    return self._forecast(entry, now)
            if entry is not None and entry.payload is None and entry.retry_at is not None and now < entry.retry_at:
                raise WeatherProviderUnavailable("Forecast refresh is in a controlled retry wait.")
            try:
                forecast = await load()
            except (WeatherProviderError, InvalidWeatherDataError) as error:
                if entry is None:
                    entry = WeatherHttpCache(key=key, failures=0)
                    db.add(entry)
                entry.failures += 1
                entry.error_code = type(error).__name__
                entry.retry_at = now + timedelta(seconds=min(3600, self.retry_seconds * 2 ** min(entry.failures - 1, 6)))
                if entry.payload is not None:
                    entry.fresh_until = now
                await db.commit()
                if entry.payload is not None:
                    return self._forecast(entry, now)
                raise
            if entry is None:
                entry = WeatherHttpCache(key=key, failures=0)
                db.add(entry)
            entry.payload = forecast.model_dump(mode="json", exclude={"farm_id", "farm_name"})
            entry.fetched_at = forecast.updated_at or now
            entry.validated_at = now
            entry.failures, entry.error_code = 0, None
            entry.fresh_until = max(now + timedelta(seconds=self.fresh_seconds), forecast.fresh_until or now)
            if forecast.freshness != "fresh":
                entry.fresh_until = now
                entry.retry_at = now + timedelta(seconds=self.retry_seconds)
            else:
                entry.retry_at = None
            await db.commit()
            return self._forecast(entry, now)

    def _forecast(self, entry, now):
        data = self._result(entry, now)
        metadata = data.pop("_agrifos_cache")
        return WeatherForecastRead(farm_id=uuid.UUID(int=0), farm_name="", **{
            **data, "freshness": metadata["freshness"], "consulted_at": now,
            "updated_at": entry.fetched_at, "fresh_until": entry.fresh_until,
        })
