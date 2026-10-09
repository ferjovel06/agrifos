"""Real PostgreSQL and ES256/JWKS integration; opt in with an isolated DB URL.

No production reset, auth dependency mock or metadata.create_all is used. The
auth fixture serves actual public signing keys over loopback HTTP. Only the DB
session dependency is injected, pointing at migrated PostgreSQL.
"""
import asyncio
import json
import os
import threading
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import httpx
import jwt
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import auth
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.integrations.weather_http import HttpWeatherTransport
from app.services.weather_http_cache import PersistentWeatherHttpCache
from tests.test_weather import provider_payload

DATABASE = os.environ.get("OFFLINE_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE, "NOT RUN: set OFFLINE_TEST_DATABASE_URL to an isolated agrifos_offline_* database")
class OfflinePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy.engine import make_url
        url = make_url(DATABASE)
        if not url.database.startswith("agrifos_offline_") or url.host not in ("127.0.0.1", "localhost"):
            raise RuntimeError("Integration requires a loopback agrifos_offline_* fixture database.")
        cls.engine = create_async_engine(DATABASE, poolclass=NullPool)
        cls.sessions = async_sessionmaker(cls.engine, expire_on_commit=False)
        async def bootstrap():
            async with cls.engine.begin() as db:
                await db.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
                await db.execute(text("CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY,email text,raw_user_meta_data jsonb NOT NULL DEFAULT '{}')"))
                await db.execute(text("CREATE TABLE IF NOT EXISTS auth.mfa_factors (id uuid PRIMARY KEY,user_id uuid REFERENCES auth.users(id),status text)"))
        asyncio.run(bootstrap())
        with patch.object(settings, "DATABASE_URL", DATABASE):
            config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
            command.upgrade(config, "head")
        cls.key = ec.generate_private_key(ec.SECP256R1())
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update(kid="offline-fixture", alg="ES256", use="sig")
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"keys": [jwk]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        cls.jwks = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.jwks.serve_forever, daemon=True)
        cls.thread.start()
        cls.auth_url = f"http://127.0.0.1:{cls.jwks.server_port}"
        cls.original_url, cls.original_jwks = settings.SUPABASE_URL, auth._jwks_client
        settings.SUPABASE_URL = cls.auth_url
        auth._jwks_client = jwt.PyJWKClient(cls.auth_url + "/auth/v1/.well-known/jwks.json")
        async def real_session():
            async with cls.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = real_session
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        app.dependency_overrides.pop(get_db, None)
        settings.SUPABASE_URL, auth._jwks_client = cls.original_url, cls.original_jwks
        cls.jwks.shutdown()
        cls.jwks.server_close()
        asyncio.run(cls.engine.dispose())

    def setUp(self):
        self.user = uuid.uuid4()
        self.email = f"offline-{self.user}@example.invalid"
        async def create():
            async with self.engine.begin() as db:
                await db.execute(text("INSERT INTO auth.users(id,email) VALUES(:id,:email)"), {"id":self.user,"email":self.email})
        asyncio.run(create())
        self.headers = {"Authorization": "Bearer " + self.token(self.user, self.email)}
        farm = self.client.post("/farms", headers=self.headers,
            json={"name":"Offline fixture","area_hectares":2,"latitude":12.112345,"longitude":-86.223456})
        self.assertEqual(farm.status_code, 201, farm.text)
        self.farm = farm.json()["id"]
        crop = self.client.get("/crops", headers=self.headers).json()[0]["id"]
        parcel = self.client.post("/parcels", headers=self.headers,
            json={"farm_id":self.farm,"crop_id":crop,"name":"Coffee fixture","area_hectares":1,
                  "plants_per_hectare":3000,"planting_date":"2025-01-01"})
        self.assertEqual(parcel.status_code, 201, parcel.text)
        self.parcel = parcel.json()["id"]

    def token(self, user, email, **overrides):
        now = datetime.now(UTC)
        return jwt.encode({"sub":str(user),"email":email,"aud":"authenticated",
            "iss":self.auth_url + "/auth/v1","iat":now,"exp":now + timedelta(minutes=5),
            "aal":"aal1",**overrides},self.key,algorithm="ES256",headers={"kid":"offline-fixture"})

    def operation(self, entity="readings"):
        values = {"parcel_id":self.parcel,"nitrogen":20,"phosphorus":10,"potassium":30,
                  "ph":6,"ec":0.4,"temperature":24,"humidity":60}
        if entity=="lab_analyses":
            values.pop("temperature"); values.pop("humidity")
            values.update(sample_code=str(uuid.uuid4()),sampled_at="2025-01-01T12:00:00Z",
                depth_start_cm=0,depth_end_cm=20,lab="Fixture lab",ph_method="water",
                ec_method="extract",organic_matter_pct=3,cic=12,clay_pct=30,silt_pct=30,sand_pct=40,
                phosphorus_method="Bray",potassium_method="extract",calcium=100,magnesium=30,sulfur=15)
        return {"operation_id":str(uuid.uuid4()),"entity_id":str(uuid.uuid4()),
                "farm_id":self.farm,"entity":entity,"operation":"create","payload_version":1,
                "expected_revision":None,"payload":values}

    def test_lost_response_and_concurrent_delivery_create_exactly_one_record(self):
        from concurrent.futures import ThreadPoolExecutor
        operation = self.operation()
        # Discard the first committed response, then deliver concurrently.
        first = self.client.post("/sync/operations", headers=self.headers, json=operation)
        self.assertEqual(first.status_code, 200, first.text)
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies=list(pool.map(lambda _: self.client.post("/sync/operations",headers=self.headers,json=operation),range(4)))
        self.assertTrue(all(reply.status_code==200 and reply.json()==first.json() for reply in replies))
        async def count():
            async with self.sessions() as db:
                return (await db.execute(text("SELECT count(*) FROM readings WHERE id=CAST(:id AS uuid)"),{"id":operation["entity_id"]})).scalar()
        self.assertEqual(asyncio.run(count()),1)
        changed={**operation,"payload":{**operation["payload"],"nitrogen":99}}
        self.assertEqual(self.client.post("/sync/operations",headers=self.headers,json=changed).status_code,409)

    def test_remote_edit_conflict_preserves_both_versions_and_legacy_revision(self):
        operation = self.operation("lab_analyses")
        response=self.client.post("/sync/operations",headers=self.headers,json=operation)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["data"]["revision"],1)
        legacy=self.client.patch("/lab-analyses/"+operation["entity_id"],headers=self.headers,json={"nitrogen":77})
        self.assertEqual(legacy.status_code,200,legacy.text)
        self.assertEqual(legacy.json()["revision"],2)
        candidate={**operation,"operation_id":str(uuid.uuid4()),"operation":"update","expected_revision":1,
                   "payload":{**operation["payload"],"nitrogen":55}}
        conflict=self.client.post("/sync/operations",headers=self.headers,json=candidate)
        self.assertEqual(conflict.status_code,409,conflict.text)
        self.assertEqual(conflict.json()["detail"]["remote"]["nitrogen"],77)
        self.assertEqual(candidate["payload"]["nitrogen"],55)

    def test_incremental_pagination_tombstones_and_user_scope(self):
        page=self.client.get("/sync/changes",headers=self.headers,params={"limit":1}).json()
        ids=[]
        while True:
            ids.extend(change["entity_id"] for change in page["changes"])
            if not page["has_more"]: break
            page=self.client.get("/sync/changes",headers=self.headers,params={"limit":1,"cursor":page["cursor"]}).json()
        self.assertEqual(set(ids),{self.farm,self.parcel})
        cursor=page["cursor"]
        empty=self.client.get("/sync/changes",headers=self.headers,params={"cursor":cursor}).json()
        self.assertEqual(empty["changes"],[])
        deleted=self.client.delete("/parcels/"+self.parcel,headers=self.headers)
        self.assertEqual(deleted.status_code,204,deleted.text)
        changes=self.client.get("/sync/changes",headers=self.headers,params={"cursor":cursor}).json()["changes"]
        self.assertEqual([(row["entity_id"],row["operation"]) for row in changes],[(self.parcel,"delete")])
        other=uuid.uuid4(); email=f"offline-{other}@example.invalid"
        async def create_other():
            async with self.engine.begin() as db:
                await db.execute(text("INSERT INTO auth.users(id,email) VALUES(:id,:email)"),{"id":other,"email":email})
        asyncio.run(create_other())
        headers={"Authorization":"Bearer "+self.token(other,email)}
        self.assertEqual(self.client.get("/sync/changes",headers=headers).json()["changes"],[])
        self.assertEqual(self.client.get("/sync/changes",headers=headers,params={"cursor":cursor}).status_code,400)
        self.assertEqual(self.client.post("/sync/operations",headers=headers,json=self.operation()).status_code,403)

    def test_expired_wrong_audience_and_mfa_are_rejected_by_real_auth_boundary(self):
        for overrides in ({"exp":datetime.now(UTC)-timedelta(seconds=1)},{"aud":"wrong"},{"iss":"https://untrusted.invalid"}):
            headers={"Authorization":"Bearer "+self.token(self.user,self.email,**overrides)}
            self.assertEqual(self.client.get("/sync/changes",headers=headers).status_code,401)
        async def factor():
            async with self.engine.begin() as db:
                await db.execute(text("INSERT INTO auth.mfa_factors(id,user_id,status) VALUES(:id,:user,'verified')"),{"id":uuid.uuid4(),"user":self.user})
        asyncio.run(factor())
        self.assertEqual(self.client.get("/sync/changes",headers=self.headers).status_code,403)
        headers={"Authorization":"Bearer "+self.token(self.user,self.email,aal="aal2")}
        self.assertEqual(self.client.get("/sync/changes",headers=headers).status_code,200)

    def test_shared_weather_concurrency_expires_304_429_and_historical(self):
        async def scenario():
            now=[datetime.now(UTC)]
            responses=[200,304,429]
            calls=[]
            url="https://weather-fixture.invalid/"+str(uuid.uuid4())
            modified="Wed, 07 Oct 2026 12:00:00 GMT"
            async def handler(request):
                calls.append(dict(request.headers))
                code=responses.pop(0)
                return httpx.Response(code,json=provider_payload() if code==200 else None,
                    headers={"last-modified":modified,"expires":(now[0]+timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT"),"retry-after":"3600"})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                def transport():
                    store=PersistentWeatherHttpCache(self.sessions,clock=lambda:now[0])
                    return HttpWeatherTransport(attempts=1,timeout_seconds=15,connect_timeout_seconds=5,client=client,cache=store)
                forecasts=await asyncio.gather(*(transport().get_json(url,params={"lat":12.1,"lon":-86.2}) for _ in range(10)))
                self.assertEqual(len(calls),1)
                self.assertEqual(forecasts[0]["_agrifos_cache"]["freshness"],"fresh")
                now[0]+=timedelta(minutes=40)
                await transport().get_json(url,params={"lat":12.1,"lon":-86.2})
                self.assertEqual(len(calls),1) # Expires is longer than default TTL.
                now[0]+=timedelta(minutes=21)
                reused=await transport().get_json(url,params={"lat":12.1,"lon":-86.2})
                self.assertEqual(calls[-1]["if-modified-since"],modified)
                self.assertEqual(reused["daily"],forecasts[0]["daily"])
                now[0]+=timedelta(minutes=61)
                stale=await transport().get_json(url,params={"lat":12.1,"lon":-86.2})
                self.assertEqual(stale["_agrifos_cache"]["freshness"],"stale")
                now[0]+=timedelta(minutes=15)
                await transport().get_json(url,params={"lat":12.1,"lon":-86.2})
                self.assertEqual(len(calls),3)
                now[0]+=timedelta(hours=5)
                responses.append(503)
                history=await transport().get_json(url,params={"lat":12.1,"lon":-86.2})
                self.assertEqual(history["_agrifos_cache"]["freshness"],"historical")
        asyncio.run(scenario())

    def test_cross_worker_fallback_cache_reuses_public_forecast_and_retains_last_valid_result(self):
        from app.integrations.weather_provider import FallbackWeatherProvider, OpenMeteoProvider, MetNorwayProvider
        from app.integrations.weather_normalization import OpenMeteoNormalizer, MetNorwayNormalizer
        from app.services.weather_http_cache import PersistentForecastCache
        from app.services.weather_service import WeatherService
        from app.models import Farm
        from tests.test_weather import met_norway_payload
        async def scenario():
            now = datetime(2026, 10, 8, tzinfo=UTC)
            calls = {"open": 0, "met": 0}
            mode = "fallback"
            namespace = str(uuid.uuid4())
            async def handler(request):
                source = "open" if "/open/" in request.url.path else "met"
                calls[source] += 1
                if source == "open" or mode == "broken":
                    return httpx.Response(503)
                self.assertEqual(request.url.params["lat"], "12.1123")
                self.assertEqual(request.url.params["lon"], "-86.2234")
                return httpx.Response(200, json=met_norway_payload(), headers={"Expires": "Thu, 08 Oct 2026 01:00:00 GMT"})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                def service():
                    raw = PersistentWeatherHttpCache(self.sessions, clock=lambda: now)
                    transport = HttpWeatherTransport(client=http, attempts=1, timeout_seconds=2, connect_timeout_seconds=1, cache=raw)
                    provider = FallbackWeatherProvider(
                        primary=OpenMeteoProvider(transport=transport, normalizer=OpenMeteoNormalizer(), base_url=f"https://fixture.invalid/{namespace}/open"),
                        fallback=MetNorwayProvider(transport=transport, normalizer=MetNorwayNormalizer(), base_url=f"https://fixture.invalid/{namespace}/met", user_agent="Agrifos test https://github.com/ferjovel06/agrifos"))
                    cache = PersistentForecastCache(self.sessions, namespace=namespace, clock=lambda: now)
                    return WeatherService(provider, cache=cache)
                farms = [Farm(id=uuid.uuid4(), name=f"Private farm {i}", latitude=12.112345, longitude=-86.223456) for i in range(10)]
                results = await asyncio.gather(*(service().forecast(farm, 2) for farm in farms))
                self.assertEqual(calls, {"open":1,"met":1})
                self.assertEqual([result.farm_id for result in results], [farm.id for farm in farms])
                for farm in farms:
                    await service().forecast(farm, 2)
                self.assertEqual(calls, {"open":1,"met":1})
                now += timedelta(minutes=40)
                await service().forecast(farms[0], 2)
                self.assertEqual(calls, {"open":1,"met":1})
                now += timedelta(minutes=21)
                mode = "broken"
                failed = await service().forecast(farms[0], 2)
                self.assertEqual(failed.freshness, "stale")
                counts = dict(calls)
                for farm in farms:
                    await service().forecast(farm, 2)
                self.assertEqual(calls, counts)
                now += timedelta(hours=6)
                history = await service().forecast(farms[0], 2)
                self.assertEqual(history.freshness, "historical")
                async with self.sessions() as db:
                    rows = (await db.execute(text("SELECT payload::text FROM weather_http_cache WHERE payload IS NOT NULL"))).scalars()
                    self.assertFalse(any("Private farm" in row for row in rows))
        asyncio.run(scenario())

    def test_nonfinite_inputs_and_revoked_ownership_do_not_leak_prior_journal(self):
        operation = self.operation()
        operation["payload"]["nitrogen"] = float("inf")
        response = self.client.post("/sync/operations", headers={**self.headers,"Content-Type":"application/json"}, content=json.dumps(operation))
        self.assertEqual(response.status_code, 422)
        other = uuid.uuid4()
        async def transfer():
            async with self.engine.begin() as db:
                await db.execute(text("INSERT INTO auth.users(id,email) VALUES(:id,:email)"), {"id":other,"email":f"{other}@example.invalid"})
        asyncio.run(transfer())
        new_headers = {"Authorization":"Bearer " + self.token(other, f"{other}@example.invalid")}
        self.assertEqual(self.client.get("/users/me", headers=new_headers).status_code, 200)
        async def move():
            async with self.engine.begin() as db:
                await db.execute(text("UPDATE farms SET user_id=:user WHERE id=CAST(:farm AS uuid)"), {"user":other,"farm":self.farm})
        asyncio.run(move())
        old = self.client.get("/sync/changes",headers=self.headers).json()["changes"]
        self.assertTrue(all(row["operation"]=="delete" and row["data"]=={} for row in old))
        current = self.client.get("/sync/changes",headers=new_headers).json()["changes"]
        self.assertTrue(any(row["entity_id"]==self.parcel for row in current))
