import math
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from pydantic import ValidationError
from app.schemas.fertilization import FertilizerScenarioRead

from app.models import FertilizationPlan, FertilizationPlanItem
from app.repositories.fertilization_plan import create_fertilization_plan
from app.routers.fertilization import _client_recommendation, _fingerprint_request
from app.services.organic_fertilization import build_organic_scenario
from tests.test_fertilization_service import calculate, make_request, CONFIG


class OrganicFertilizationTests(unittest.TestCase):
    def screen(self, targets=None):
        return build_organic_scenario(
            targets or {"N": 71.07, "P2O5": 20.20, "K2O": 15.73},
            hectares_per_manzana=.7042, plants_per_hectare=5000,
        )

    def test_screenshot_reference_balance_and_native_units(self):
        scenario = self.screen()
        meta = scenario.organic
        self.assertEqual([d.unit for d in meta.candidates], ["kg", "L", "kg"])
        self.assertEqual([d.product_key for d in meta.candidates],
                         ["bocashi", "biol", "coffee_pulp_compost"])
        self.assertAlmostEqual(meta.candidates[0].quantity_ha, 1372.18, places=2)
        self.assertAlmostEqual(meta.candidates[2].quantity_ha, 472.65, places=2)
        self.assertEqual(meta.candidates[1].quantity_ha, 100)
        self.assertEqual(meta.candidates[1].quantity_manzana, 70.42)
        self.assertEqual(meta.candidates[1].quantity_plant, 20)
        self.assertEqual(meta.candidates[1].plant_unit, "mL")
        self.assertAlmostEqual(meta.total_contributions_kg_ha["N"], 16.60, places=2)
        self.assertGreater(meta.reference_shortfall_kg_ha["N"], 54.47)
        self.assertEqual(meta.state, "partial")
        self.assertFalse(meta.can_apply)
        self.assertIsNone(meta.equivalent_contributions_kg_ha)
        self.assertFalse(scenario.is_mathematically_valid)
        self.assertEqual(scenario.products, [])
        self.assertEqual(scenario.application_schedule, [])

    def test_zero_targets_do_not_add_unrequested_nutrients(self):
        for zero in ("N", "P2O5", "K2O"):
            target = dict(N=70, P2O5=20, K2O=15)
            target[zero] = 0
            meta = self.screen(target).organic
            self.assertEqual(meta.total_contributions_kg_ha[zero], 0)
            self.assertTrue(all(d.quantity_ha == 0 for d in meta.candidates))

    def test_varied_targets_respect_all_caps_after_rounding(self):
        for n in (0, .01, 10, 71.07, 1000):
            for p, k in ((.01, 50), (20, .01), (20, 15.73), (100, 200)):
                targets = dict(N=n, P2O5=p, K2O=k)
                meta = self.screen(targets).organic
                for nutrient, total in meta.total_contributions_kg_ha.items():
                    self.assertLessEqual(total, targets[nutrient] + .0001)
                self.assertTrue(all(d.quantity_ha >= 0 for d in meta.candidates))

    def test_invalid_values_rejected(self):
        for invalid in (-1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                self.screen(dict(N=invalid, P2O5=20, K2O=15))

    def test_snapshot_cannot_promote_reference_to_executable(self):
        snapshot = self.screen().model_dump()
        snapshot["organic"]["can_apply"] = True
        with self.assertRaises(ValidationError):
            FertilizerScenarioRead.model_validate(snapshot)
        snapshot["organic"]["can_apply"] = False
        snapshot["is_mathematically_valid"] = True
        with self.assertRaises(ValidationError):
            FertilizerScenarioRead.model_validate(snapshot)

    def test_opt_in_preserves_mineral_outputs_and_age_branches(self):
        base = make_request()
        old = calculate(base)
        new = calculate(base.model_copy(update={"include_organic": True}))
        self.assertEqual([s.model_dump() for s in old.fertilizer_scenarios],
                         [s.model_dump() for s in new.fertilizer_scenarios[:-1]])
        self.assertEqual(old.nutrient_requirements, new.nutrient_requirements)
        self.assertEqual(new.fertilizer_scenarios[-1].name, "Orgánico")
        for age in (2, 4, 24):
            result = calculate(base.model_copy(update={"include_organic": True}),
                               plant_age_months=age)
            self.assertTrue(all(s.organic is None for s in result.fertilizer_scenarios))

    def test_capability_filters_snapshots_and_preserves_legacy_hash_input(self):
        payload = make_request()
        legacy = payload.model_dump(mode="json", exclude={"include_organic"})
        self.assertEqual(_fingerprint_request(payload), legacy)
        enabled = payload.model_copy(update={"include_organic": True})
        self.assertTrue(_fingerprint_request(enabled)["include_organic"])
        new = calculate(enabled)
        self.assertEqual(len(_client_recommendation(new, False).fertilizer_scenarios),
                         len(new.fertilizer_scenarios) - 1)
        self.assertEqual(_client_recommendation(new, True), new)


class OrganicPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reference_saved_in_snapshot_without_organic_kg_items(self):
        recommendation = calculate(make_request(include_organic=True))
        added = []
        db = SimpleNamespace(add=MagicMock(side_effect=added.append), flush=AsyncMock(),
                             commit=AsyncMock(), refresh=AsyncMock())
        async def assign_id():
            added[0].id = uuid.uuid4()
        db.flush.side_effect = assign_id
        plan = await create_fertilization_plan(
            db, recommendation=recommendation, config=CONFIG,
            method="laboratory", input_fingerprint="f" * 64,
        )
        self.assertIsInstance(plan, FertilizationPlan)
        meta = plan.recommendation_snapshot["fertilizer_scenarios"][-1]["organic"]
        self.assertEqual(meta["candidates"][1]["unit"], "L")
        self.assertFalse(meta["can_apply"])
        items = [i for i in added if isinstance(i, FertilizationPlanItem)]
        self.assertTrue(items)
        self.assertFalse(any(i.scenario_name == "Orgánico" for i in items))
