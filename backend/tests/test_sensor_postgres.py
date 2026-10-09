"""Synthetic measurements over migrated PostgreSQL and actual ES256/JWKS auth.

These tests exercise software, not a physical sensor or laboratory calibration.
No database reset and no authentication dependency mocks are used.
"""
import asyncio
import os
import unittest
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests import test_offline_postgres as offline_fixture


@unittest.skipUnless(os.environ.get("OFFLINE_TEST_DATABASE_URL"), "NOT RUN: isolated PostgreSQL fixture required")
class SensorPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        offline_fixture.OfflinePostgresTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        offline_fixture.OfflinePostgresTests.tearDownClass()

    def setUp(self):
        self.fixture = offline_fixture.OfflinePostgresTests("test_lost_response_and_concurrent_delivery_create_exactly_one_record")
        self.fixture.setUp()
        self.client, self.headers = self.fixture.client, self.fixture.headers
        self.session = str(uuid.uuid4())
        self.acquired = datetime.now(UTC) - timedelta(minutes=1)

    def payload(self, value=20, *, point="fixture-point", variable="nitrogen", index=0):
        unit, analyte = ("mg/kg", "N") if variable == "nitrogen" else ("%", "humidity")
        acquired = (self.acquired + timedelta(seconds=index)).isoformat().replace("+00:00", "Z")
        return {"parcel_id":self.fixture.parcel, "measurement_id":str(uuid.uuid4()),
                "recorded_at":acquired, variable:value,
                "measurement":{"contract_version":1,"session_id":self.session,
                    "device_id":"synthetic-software-fixture", "sensor_model":"fixture-not-physical-hardware",
                    "protocol_version":"synthetic-v1", "profile_id":"synthetic-profile",
                    "point_id":point,"acquired_at":acquired,
                    "variables":{variable:{"raw_value":value,"unit":unit,"analyte":analyte,"read_status":"valid"}}}}

    def create(self, payload):
        response = self.client.post("/readings",headers=self.headers,json=payload)
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def process(self, ids, window=5):
        response = self.client.post("/readings/process",headers=self.headers,
                                    json={"reading_ids":ids,"window_size":window})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def laboratory(self,value=41):
        return {"laboratory":"synthetic-software-fixture","report_id":"fixture-report",
                "sampled_at":self.acquired.isoformat(),"sampling_procedure":"Numerical fixture; no physical sampling",
                "depth_start_cm":0,"depth_end_cm":20,"moisture_conditions":"Not measured; numerical test only",
                "method":"synthetic-known-linear-reference","report_basis":"synthetic-test-basis",
                "unit":"mg/kg","analyte":"N","reference_value":value,
                "comparability_evidence":"Synthetic numerical comparison only; not laboratory data","synthetic":True}

    def test_partial_original_is_preserved_and_online_replay_is_idempotent(self):
        payload = self.payload()
        first, replay = self.create(payload), self.create(payload)
        self.assertEqual(first["id"], replay["id"])
        for key,value in payload["measurement"].items():
            if key == "variables":
                for field,expected in value["nitrogen"].items():
                    self.assertEqual(first["measurement"][key]["nitrogen"][field],expected)
            else:
                self.assertEqual(first["measurement"][key],value)
        self.assertIsNone(first["phosphorus"])
        self.assertIsNone(first["humidity"])
        self.assertIsNone(first["diagnosis"])
        self.assertGreater(datetime.fromisoformat(first["received_at"]), self.acquired)
        changed = {**payload,"measurement":{**payload["measurement"],"point_id":"changed"}}
        self.assertEqual(self.client.post("/readings",headers=self.headers,json=changed).status_code,409)

    def test_centered_processing_replay_and_reprocessing_keep_history(self):
        readings = [self.create(self.payload(value,index=i)) for i,value in enumerate([15.2,15.4,45,15.5,15.3])]
        ids = [row["id"] for row in readings]
        processed, replay = self.process(ids), self.process(ids)
        self.assertEqual(processed,replay)
        middle = next(row for row in processed if row["reading_id"]==ids[2])["variables"]["nitrogen"]
        self.assertEqual(middle["raw"]["value"],45)
        self.assertEqual(middle["filtered"],15.4)
        self.assertEqual(middle["accuracy_state"],"uncalibrated")
        self.process(ids,3)
        history = self.client.get(f"/readings/{ids[2]}/results",headers=self.headers).json()
        self.assertEqual(len(history),2)
        original = self.client.get(f"/readings/{ids[2]}",headers=self.headers).json()
        self.assertEqual(original["measurement"],readings[2]["measurement"])
        self.assertEqual(original["nitrogen"],45)
        self.assertEqual(len(original["derived_results"]),2)
        feed = self.client.get("/sync/changes",headers=self.headers).json()["changes"]
        self.assertTrue(any(row["entity_id"]==ids[2] and len(row["data"].get("derived_results",[]))==2 for row in feed))

    def test_points_and_missing_variable_gaps_are_not_smoothed(self):
        rows = [self.create(self.payload(value,point=f"point-{i}",index=i)) for i,value in enumerate([15.2,15.4,45,15.5,15.3])]
        results = self.process([row["id"] for row in rows])
        self.assertTrue(all(row["variables"]["nitrogen"]["filtered"]==row["variables"]["nitrogen"]["raw"]["value"] for row in results))
        values = [self.create(self.payload(value,index=i)) for i,value in enumerate([15.2,15.4,45])]
        gap = self.create(self.payload(60,variable="humidity",point="other-point",index=3))
        values += [gap] + [self.create(self.payload(value,index=i)) for i,value in enumerate([15.5,15.3],start=4)]
        result = self.process([row["id"] for row in values])
        middle = next(row for row in result if row["reading_id"]==values[2]["id"])
        self.assertEqual(middle["variables"]["nitrogen"]["filtered"],45)

    def test_decoder_and_soil_changes_preserve_physical_sequence_boundaries(self):
        for field in ["profile_id", "soil_type"]:
            rows = []
            for index, value in enumerate([15.2,15.4,45,15.5,15.3]):
                payload = self.payload(value,index=index)
                payload["measurement"][field] = "fixture-a" if index < 3 else "fixture-b"
                rows.append(self.create(payload))
            results = self.process([row["id"] for row in rows])
            self.assertTrue(all(row["variables"]["nitrogen"]["filtered"] == row["variables"]["nitrogen"]["raw"]["value"] for row in results), field)

    def test_raw_evidence_and_derived_history_reject_database_updates(self):
        reading = self.create(self.payload())
        derived = self.process([reading["id"]])[0]
        async def attempt(statement,values):
            async with self.fixture.engine.begin() as db:
                await db.execute(text(statement),values)
        for statement,values in [
            ("UPDATE readings SET nitrogen=999 WHERE id=CAST(:id AS uuid)",{"id":reading["id"]}),
            ("UPDATE reading_results SET payload='{}'::jsonb WHERE id=CAST(:id AS uuid)",{"id":derived["id"]}),
            ("DELETE FROM reading_results WHERE id=CAST(:id AS uuid)",{"id":derived["id"]}),
            ("DELETE FROM readings WHERE id=CAST(:id AS uuid)",{"id":reading["id"]}),
        ]:
            with self.assertRaises(DBAPIError):
                asyncio.run(attempt(statement,values))

    def test_new_private_tables_revoke_supabase_default_role_grants(self):
        async def verify():
            async with self.fixture.sessions() as db:
                for table in ["reading_results","sensor_calibrations","sensor_calibration_pairs"]:
                    rls=(await db.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:table AS regclass)"),{"table":table})).scalar()
                    self.assertTrue(rls,table)
                    for role in ["anon","authenticated"]:
                        exists=(await db.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"),{"role":role})).scalar()
                        if exists:
                            grant=(await db.execute(text("SELECT has_table_privilege(:role,:table,'SELECT,INSERT,UPDATE,DELETE')"),{"role":role,"table":table})).scalar()
                            self.assertFalse(grant,(role,table))
        asyncio.run(verify())

    def test_sql_contract_check_rejects_missing_or_text_version(self):
        async def insert(envelope):
            async with self.fixture.engine.begin() as db:
                await db.execute(text("INSERT INTO readings(id,parcel_id,measurement) VALUES(:id,CAST(:parcel AS uuid),CAST(:measurement AS jsonb))"),
                                 {"id":uuid.uuid4(),"parcel":self.fixture.parcel,"measurement":envelope})
        for envelope in ["{}",'{"contract_version":"1"}']:
            with self.assertRaises(DBAPIError):
                asyncio.run(insert(envelope))

    def test_unknown_units_inconsistent_projection_and_future_dates_rejected(self):
        payload=self.payload()
        payload["measurement"]["variables"]["nitrogen"]["unit"]="unverified-units"
        self.assertEqual(self.client.post("/readings",headers=self.headers,json=payload).status_code,422)
        payload=self.payload(); payload["nitrogen"]=900
        self.assertEqual(self.client.post("/readings",headers=self.headers,json=payload).status_code,422)
        payload=self.payload()
        future=(datetime.now(UTC)+timedelta(days=1)).isoformat()
        payload["recorded_at"]=future;payload["measurement"]["acquired_at"]=future
        self.assertEqual(self.client.post("/readings",headers=self.headers,json=payload).status_code,422)

    def test_foreign_account_cannot_read_process_or_pair_measurements(self):
        reading=self.create(self.payload())
        other=uuid.uuid4(); email=f"{other}@example.invalid"
        async def create():
            async with self.fixture.engine.begin() as db:
                await db.execute(text("INSERT INTO auth.users(id,email) VALUES(:id,:email)"),{"id":other,"email":email})
        asyncio.run(create())
        headers={"Authorization":"Bearer "+self.fixture.token(other,email)}
        self.assertEqual(self.client.get("/users/me",headers=headers).status_code,200)
        self.assertEqual(self.client.get(f"/readings/{reading['id']}/results",headers=headers).status_code,403)
        self.assertEqual(self.client.post("/readings/process",headers=headers,json={"reading_ids":[reading["id"]]}).status_code,403)
        self.assertEqual(self.client.get("/calibrations/pairs",headers=headers,params={"reading_id":reading["id"]}).status_code,404)
        self.assertEqual(self.client.post("/calibrations/pairs",headers=headers,json={
            "reading_id":reading["id"],"sample_id":"foreign","variable":"nitrogen","laboratory":self.laboratory()}).status_code,404)

    def test_paired_candidate_versions_are_immutable_and_synthetic_promotion_is_blocked(self):
        pairs=[]
        for index,value in enumerate([10,20,30,40,50,60]):
            payload=self.payload(value,point=f"sample-{index}",index=index)
            payload["measurement"]["depth_cm"]=10
            reading=self.create(payload)
            pair={"reading_id":reading["id"],"sample_id":f"sample-{index}",
                  "variable":"nitrogen","laboratory":self.laboratory(2*value+1)}
            first=self.client.post("/calibrations/pairs",headers=self.headers,json=pair)
            self.assertEqual(first.status_code,201,first.text)
            replay=self.client.post("/calibrations/pairs",headers=self.headers,json=pair)
            self.assertEqual(replay.json()["id"],first.json()["id"])
            alias=self.client.post("/calibrations/pairs",headers=self.headers,json={**pair,"sample_id":"alias"})
            self.assertEqual(alias.status_code,409,alias.text)
            pairs.append(first.json()["id"])
        request={"profile_id":str(uuid.uuid4()),"version":1,"pair_ids":pairs,
                 "holdout_sample_ids":["sample-1","sample-4"],
                 "training_evidence":"Synthetic fixture only; cannot be promoted"}
        first=self.client.post("/calibrations/train",headers=self.headers,json=request)
        self.assertEqual(first.status_code,201,first.text)
        model=first.json()
        self.assertEqual(model["state"],"candidate")
        self.assertAlmostEqual(model["profile"]["coefficients"][0],1)
        self.assertAlmostEqual(model["profile"]["coefficients"][1],2)
        second=self.client.post("/calibrations/train",headers=self.headers,json={**request,"version":2})
        self.assertEqual(second.status_code,201,second.text)
        self.assertNotEqual(second.json()["id"],model["id"])
        self.assertEqual(self.client.get(f"/calibrations/{model['id']}",headers=self.headers).json(),model)
        validation=self.client.post(f"/calibrations/{model['id']}/validate",headers=self.headers,
                                    json={"validation_evidence":"Synthetic fixture cannot validate agricultural accuracy"})
        self.assertEqual(validation.status_code,422,validation.text)
        self.assertEqual(validation.json()["detail"]["code"],"SYNTHETIC_PROFILE_CANNOT_BE_VALIDATED")
        blocked=self.client.post("/readings/process",headers=self.headers,
                                 json={"reading_ids":[reading["id"]],"calibration_id":model["id"]})
        self.assertEqual(blocked.status_code,422,blocked.text)
        duplicate=self.client.post("/calibrations/train",headers=self.headers,json=request)
        self.assertEqual(duplicate.status_code,409,duplicate.text)

    def test_incompatible_laboratory_pair_is_not_silently_converted(self):
        payload=self.payload();payload["measurement"]["depth_cm"]=10
        reading=self.create(payload)
        lab=self.laboratory();lab["analyte"]="NO3"
        response=self.client.post("/calibrations/pairs",headers=self.headers,json={
            "reading_id":reading["id"],"sample_id":"incompatible","variable":"nitrogen","laboratory":lab})
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(response.json()["detail"]["code"],"INCOMPATIBLE_ANALYTE_OR_UNIT")

    def test_numerical_fixture_reprocesses_two_calibrations_without_overwriting_raw(self):
        # Deliberately exercises the declared-real promotion gate with fabricated
        # input in an isolated DB. This is software acceptance, NOT empirical
        # calibration; these profiles never leave the disposable fixture DB.
        profile_id=str(uuid.uuid4())
        models=[]
        for version,offset in [(1,1),(2,3)]:
            ids=[]
            for index,value in enumerate([10,20,30,40,50,60]):
                payload=self.payload(value,point=f"v{version}-sample-{index}",index=index)
                payload["measurement"].update(depth_cm=10,soil_type="synthetic-test-soil")
                reading=self.create(payload)
                lab=self.laboratory(2*value+offset)
                lab.update(synthetic=False,soil_type="synthetic-test-soil")
                pair=self.client.post("/calibrations/pairs",headers=self.headers,json={
                    "reading_id":reading["id"],"sample_id":f"v{version}-sample-{index}",
                    "variable":"nitrogen","laboratory":lab})
                self.assertEqual(pair.status_code,201,pair.text)
                ids.append(pair.json()["id"])
            trained=self.client.post("/calibrations/train",headers=self.headers,json={
                "profile_id":profile_id,"version":version,"pair_ids":ids,
                "holdout_sample_ids":[f"v{version}-sample-1",f"v{version}-sample-4"],
                "training_evidence":"Isolated numerical gate test; no laboratory accuracy claim"})
            self.assertEqual(trained.status_code,201,trained.text)
            validated=self.client.post(f"/calibrations/{trained.json()['id']}/validate",headers=self.headers,
                json={"validation_evidence":"Isolated numerical test; not a production profile"})
            self.assertEqual(validated.status_code,200,validated.text)
            models.append(validated.json())
        payload=self.payload(25,point="target")
        payload["measurement"].update(depth_cm=10,soil_type="synthetic-test-soil")
        target=self.create(payload)
        history=[]
        for model,expected in zip(models,[51,53]):
            response=self.client.post("/readings/process",headers=self.headers,json={
                "reading_ids":[target["id"]],"calibration_id":model["id"]})
            self.assertEqual(response.status_code,200,response.text)
            result=response.json()[0]
            estimate=result["variables"]["nitrogen"]["calibration"]
            self.assertAlmostEqual(estimate["value"],expected)
            self.assertEqual(estimate["profile_version"],model["version"])
            self.assertEqual(estimate["input_basis"],"raw")
            history.append(result)
        saved=self.client.get(f"/readings/{target['id']}",headers=self.headers).json()
        self.assertEqual(saved["measurement"],target["measurement"])
        self.assertEqual(saved["nitrogen"],25)
        self.assertEqual(len(saved["derived_results"]),2)
        for field,value in [("profile_id","changed-decoder"),("depth_cm",11),("soil_type","other-soil")]:
            incompatible=self.payload(25,point="incompatible")
            incompatible["measurement"].update(depth_cm=10,soil_type="synthetic-test-soil")
            incompatible["measurement"][field]=value
            row=self.create(incompatible)
            response=self.client.post("/readings/process",headers=self.headers,json={
                "reading_ids":[row["id"]],"calibration_id":models[0]["id"]})
            self.assertEqual(response.status_code,200,response.text)
            self.assertIsNone(response.json()[0]["variables"]["nitrogen"]["calibration"])
        prior=self.client.get(f"/calibrations/{models[0]['id']}",headers=self.headers).json()
        self.assertEqual(prior,models[0])

    def test_unvalidated_sensor_cannot_produce_definitive_diagnostic_or_dose(self):
        reading=self.create(self.payload())
        diagnostic=self.client.get(f"/diagnostics/readings/{reading['id']}",headers=self.headers)
        self.assertEqual(diagnostic.status_code,422,diagnostic.text)
        response=self.client.post("/fertilization/recommendations",headers=self.headers,json={
            "parcel_id":self.fixture.parcel,"reading_id":reading["id"],"target_yield":1000,
            "yield_unit":"kg_green_ha","fruit_stage":"filling","soil":{"source":"sensor",
            "nitrogen":"adequate","phosphorus":"adequate","potassium":"adequate"}})
        self.assertEqual(response.status_code,422,response.text)
