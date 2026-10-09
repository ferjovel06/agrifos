"""Controlled request counts; synthetic HTTP responses, real provider adapters.

--backend-source may point to an archived origin/main/backend for the baseline.
--persistent uses real PostgreSQL; it requires the same isolated DB guard as the
integration suite. No external provider or private farm is contacted.
"""
import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
import json
import os
from pathlib import Path
import sys
import uuid


async def measure(args):
    import httpx
    from app.integrations.weather_http import HttpWeatherTransport
    from app.integrations.weather_normalization import OpenMeteoNormalizer, MetNorwayNormalizer
    from app.integrations.weather_provider import FallbackWeatherProvider, OpenMeteoProvider, MetNorwayProvider
    from app.models import Farm
    from app.services.weather_service import WeatherService, WeatherForecastCache
    from tests.test_weather import met_norway_payload
    calls = {"Open-Meteo":0,"MET Norway":0}
    namespace = str(uuid.uuid4())
    now = datetime.now(UTC)
    async def handler(request):
        name = "Open-Meteo" if "/open/" in request.url.path else "MET Norway"
        calls[name] += 1
        if name == "Open-Meteo":
            return httpx.Response(503)
        return httpx.Response(200, json=met_norway_payload(), headers={"Expires":format_datetime(now + timedelta(hours=1), usegmt=True)})
    engine = sessions = None
    if args.persistent:
        from sqlalchemy.engine import make_url
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import NullPool
        from app.services.weather_http_cache import PersistentWeatherHttpCache, PersistentForecastCache
        database = os.environ.get("OFFLINE_TEST_DATABASE_URL", "")
        url = make_url(database)
        if url.host not in ("127.0.0.1","localhost") or not url.database.startswith("agrifos_offline_"):
            raise RuntimeError("Use only an isolated loopback agrifos_offline_* DB.")
        engine = create_async_engine(database, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            def service():
                options = {"cache":PersistentWeatherHttpCache(sessions)} if args.persistent else {}
                transport = HttpWeatherTransport(client=http, attempts=1, timeout_seconds=2, connect_timeout_seconds=1, **options)
                provider = FallbackWeatherProvider(
                    primary=OpenMeteoProvider(transport=transport, normalizer=OpenMeteoNormalizer(), base_url=f"https://fixture.invalid/{namespace}/open"),
                    fallback=MetNorwayProvider(transport=transport, normalizer=MetNorwayNormalizer(), base_url=f"https://fixture.invalid/{namespace}/met", user_agent="Agrifos test https://github.com/ferjovel06/agrifos"))
                cache = (PersistentForecastCache(sessions, namespace=namespace)
                         if args.persistent else WeatherForecastCache())
                return WeatherService(provider, cache=cache)
            farms = [Farm(id=uuid.uuid4(),name="Fixture",latitude=12.112345,longitude=-86.223456) for _ in range(10)]
            results = await asyncio.gather(*(service().forecast(farm, 2) for farm in farms))
            assert len(results) == 10
            expected = 1 if args.persistent else 10
            assert all(count == expected for count in calls.values()), calls
            result = {"status":"PASS","mode":"PostgreSQL shared cache" if args.persistent else "origin/main memory caches",
                      "scenario":"10 independent services, equivalent locations, failing primary, fresh fallback",
                      "backend_forecast_requests":10,"external_requests":calls,"http":"synthetic","postgresql":bool(args.persistent)}
            if args.output:
                Path(args.output).write_text(json.dumps(result,indent=2),encoding="utf-8")
            print(json.dumps(result))
    finally:
        if engine:
            await engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-source", type=Path, default=Path(__file__).resolve().parents[1] / "backend")
    parser.add_argument("--persistent", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    sys.path.insert(0,str(args.backend_source.resolve()))
    os.environ.setdefault("DATABASE_URL","postgresql+asyncpg://postgres:fixture@127.0.0.1:59999/agrifos_offline_unused")
    os.environ.setdefault("SUPABASE_URL","http://127.0.0.1:59998")
    asyncio.run(measure(args))


if __name__ == "__main__":
    main()
