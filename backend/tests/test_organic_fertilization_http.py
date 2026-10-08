"""Real FastAPI routes with isolated auth/repository doubles, no remote database."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest
import uuid

from fastapi.testclient import TestClient
from app.main import app
from app.core.auth import get_current_user, require_write_access
from app.db.session import get_db
from app.routers import fertilization as router
from tests.test_fertilization_service import make_request, CONFIG, VARIETY_ID


class OrganicHttpTests(unittest.TestCase):
    def test_post_snapshot_get_and_legacy_filter(self):
        user = SimpleNamespace(id=uuid.uuid4(), role="farmer")
        parcel_id = uuid.uuid4()
        parcel = SimpleNamespace(
            id=parcel_id, crop_id=CONFIG.crop_id,
            variety=SimpleNamespace(id=VARIETY_ID, name="Caturra"),
            crop=SimpleNamespace(name="Café"),
            planting_date=date(2020, 1, 1), area_hectares=1.5,
            plants_per_hectare=5000, farm=SimpleNamespace(user_id=user.id),
        )
        saved = []
        async def save(db, **kwargs):
            plan = SimpleNamespace(
                id=uuid.uuid4(), method=kwargs["method"], reading_id=None,
                lab_analysis_id=None,
                recommendation_snapshot=kwargs["recommendation"].model_dump(mode="json"),
            )
            saved.append(plan)
            return plan
        async def latest(*args, **kwargs):
            return saved[-1]
        async def database():
            yield SimpleNamespace()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[require_write_access] = lambda: user
        app.dependency_overrides[get_db] = database
        try:
            with (
                patch.object(router.parcel_repo, "get_parcel", AsyncMock(return_value=parcel)),
                patch.object(router, "get_active_engine_config", AsyncMock(return_value=CONFIG)),
                patch.object(router.fertilization_plan_repo, "get_fertilization_plan_by_fingerprint",
                             AsyncMock(return_value=None)),
                patch.object(router.fertilization_plan_repo, "create_fertilization_plan", save),
                patch.object(router.fertilization_plan_repo, "get_latest_fertilization_plan", latest),
            ):
                client = TestClient(app)
                request = make_request(parcel_id=parcel_id, include_organic=True)
                response = client.post("/fertilization/recommendations", json=request.model_dump(mode="json"))
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                meta = body["fertilizer_scenarios"][-1]["organic"]
                self.assertEqual(meta["candidates"][1]["unit"], "L")
                self.assertFalse(meta["can_apply"])
                self.assertEqual(body["fertilizer_scenarios"][-1]["application_schedule"], [])
                result = client.get("/fertilization/plans/latest", params={
                    "parcel_id": str(parcel_id), "include_organic": "true"})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["fertilizer_scenarios"], body["fertilizer_scenarios"])
                legacy = client.get("/fertilization/plans/latest", params={"parcel_id": str(parcel_id)})
                self.assertEqual(legacy.status_code, 200)
                self.assertTrue(all(s["organic"] is None for s in legacy.json()["fertilizer_scenarios"]))
                self.assertEqual(len(saved), 1)
                with patch.object(router.fertilization_plan_repo,
                                  "get_fertilization_plan_by_fingerprint",
                                  AsyncMock(return_value=saved[-1])):
                    request.include_organic = False
                    cached = client.post("/fertilization/recommendations",
                                         json=request.model_dump(mode="json"))
                self.assertEqual(cached.status_code, 200)
                self.assertTrue(all(s["organic"] is None for s in cached.json()["fertilizer_scenarios"]))
                self.assertEqual(len(saved), 1)
        finally:
            app.dependency_overrides.clear()
