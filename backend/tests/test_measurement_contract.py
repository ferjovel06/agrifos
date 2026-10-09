import copy
import math
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pydantic import ValidationError

from app.repositories.reading import calibrate_original, process_originals
from app.repositories.calibration import physical_context_key
from app.schemas.reading import ReadingCreate


def measurement_payload(**overrides):
    provenance = {"contract_version": 1, "session_id": str(uuid.uuid4()), "device_id": "fixture-unit",
        "sensor_model": "software-fixture", "protocol_version": "fixture-csv-v1", "profile_id": "fixture-only",
        "point_id": "point-a", "depth_cm": 10, "acquired_at": (datetime.now(UTC)-timedelta(minutes=1)).isoformat(),
        "variables": {"nitrogen": {"raw_value": 15.2, "unit": "mg/kg", "analyte": "N", "read_status": "valid"}}}
    provenance.update(overrides)
    return {"parcel_id": str(uuid.uuid4()), "measurement": provenance}


class MeasurementContractTests(unittest.TestCase):
    def test_filter_methods_are_distinct_without_mutating_raw(self):
        prototype = measurement_payload()
        base = datetime.now(UTC)-timedelta(minutes=1)
        rows = []
        for i, raw in enumerate((15.2,15.4,45,15.5,15.3)):
            payload = copy.deepcopy(prototype)
            payload["measurement"]["acquired_at"] = (base+timedelta(seconds=i)).isoformat()
            payload["measurement"]["variables"]["nitrogen"]["raw_value"] = raw
            parsed = ReadingCreate.model_validate(payload)
            rows.append(SimpleNamespace(id=uuid.uuid4(), **parsed.orm_values(), received_at=datetime.now(UTC)))
        identity = str(rows[2].id)
        med = process_originals(rows, method="median")[identity]["nitrogen"]
        mean = process_originals(rows, method="mean")[identity]["nitrogen"]
        raw = process_originals(rows, method="none")[identity]["nitrogen"]
        self.assertEqual(med["filtered"], 15.4)
        self.assertAlmostEqual(mean["filtered"], 21.28)
        self.assertEqual(raw["filtered"], 45)
        self.assertEqual(rows[2].measurement["variables"]["nitrogen"]["raw_value"], 45)

    def test_repeated_readings_have_same_physical_sample_context(self):
        parsed = ReadingCreate.model_validate(measurement_payload())
        row = SimpleNamespace(id=uuid.uuid4(), **parsed.orm_values())
        repetition = copy.deepcopy(row)
        repetition.id = uuid.uuid4()
        repetition.measurement["acquired_at"] = (parsed.measurement.acquired_at+timedelta(seconds=1)).isoformat()
        self.assertEqual(physical_context_key(row), physical_context_key(repetition))
        repetition.measurement["session_id"] = str(uuid.uuid4())
        self.assertNotEqual(physical_context_key(row), physical_context_key(repetition))
        repetition.measurement["point_id"] = None
        self.assertIsNone(physical_context_key(repetition))

    def test_invalid_humidity_cannot_be_a_numeric_calibration_predictor(self):
        payload = measurement_payload(variables={
            "nitrogen": {"raw_value": 15, "unit": "mg/kg", "analyte": "N"},
            "humidity": {"raw_value": 50, "unit": "%", "analyte": "humidity", "read_status": "invalid"}})
        parsed = ReadingCreate.model_validate(payload)
        reading = SimpleNamespace(id=uuid.uuid4(), **parsed.orm_values(), received_at=datetime.now(UTC))
        variables = process_originals([reading])[str(reading.id)]
        with self.assertRaisesRegex(ValueError, "MISSING_OR_INVALID_PREDICTOR"):
            calibrate_original(parsed.measurement, variables, "nitrogen", SimpleNamespace(predictor_names=("humidity",)),
                parcel_id=str(reading.parcel_id), version=1)

    def test_suspect_target_is_not_silently_calibrated(self):
        payload = measurement_payload(variables={"nitrogen": {
            "raw_value": 15, "unit": "mg/kg", "analyte": "N", "read_status": "suspect"}})
        parsed = ReadingCreate.model_validate(payload)
        reading = SimpleNamespace(id=uuid.uuid4(), **parsed.orm_values(), received_at=datetime.now(UTC))
        variables = process_originals([reading])[str(reading.id)]
        with self.assertRaisesRegex(ValueError, "CALIBRATION_INPUT_SUSPECT"):
            calibrate_original(parsed.measurement, variables, "nitrogen", SimpleNamespace(predictor_names=()),
                parcel_id=str(reading.parcel_id), version=1)

    def test_partial_device_does_not_invent_other_variables(self):
        reading = ReadingCreate.model_validate(measurement_payload())
        self.assertEqual(reading.nitrogen, 15.2)
        self.assertIsNone(reading.humidity)
        self.assertIsNone(reading.ec)
        self.assertEqual(set(reading.orm_values()["measurement"]["variables"]), {"nitrogen"})

    def test_legacy_still_requires_all_values_and_same_limits(self):
        payload = {"parcel_id": uuid.uuid4(), "nitrogen": 20, "phosphorus": 10, "potassium": 30,
                   "ec": .5, "ph": 6, "humidity": 60, "temperature": 24}
        ReadingCreate.model_validate(payload)
        for key in ("nitrogen", "phosphorus", "potassium", "ec", "ph", "humidity", "temperature"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                ReadingCreate.model_validate({k: v for k, v in payload.items() if k != key})
        with self.assertRaises(ValidationError):
            ReadingCreate.model_validate({**payload, "ph": 10.1})

    def test_finite_raw_property_and_unknown_fields(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            payload = measurement_payload()
            payload["measurement"]["variables"]["nitrogen"]["raw_value"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ReadingCreate.model_validate(payload)
        for target in ("root", "envelope", "variable"):
            payload = measurement_payload()
            object_to_edit = payload if target == "root" else payload["measurement"] if target == "envelope" else payload["measurement"]["variables"]["nitrogen"]
            object_to_edit["confidence_percent"] = 99
            with self.subTest(target=target), self.assertRaises(ValidationError):
                ReadingCreate.model_validate(payload)

    def test_dimensional_ec_conversion_without_chemical_equivalence(self):
        payload = measurement_payload(variables={"ec": {"raw_value": 750, "unit": "uS/cm", "analyte": "ec"}})
        self.assertEqual(ReadingCreate.model_validate(payload).ec, .75)
        for analyte in ("NO3", "NO3-N", "unidentified"):
            payload = measurement_payload(variables={"nitrogen": {"raw_value": 15, "unit": "mg/kg", "analyte": analyte}})
            self.assertIsNone(ReadingCreate.model_validate(payload).nitrogen)
        payload = measurement_payload(variables={"phosphorus": {"raw_value": 15, "unit": "mg/kg", "analyte": "P2O5"}})
        self.assertIsNone(ReadingCreate.model_validate(payload).phosphorus)

    def test_rejects_invented_flat_values_unit_and_timestamp(self):
        payload = measurement_payload()
        for change in ({"nitrogen": 100}, {"humidity": 60}):
            with self.assertRaises(ValidationError):
                ReadingCreate.model_validate({**payload, **change})
        payload["measurement"]["variables"]["nitrogen"]["unit"] = "kg/ha"
        with self.assertRaises(ValidationError):
            ReadingCreate.model_validate(payload)
        for timestamp in (datetime.now(UTC)+timedelta(days=1), datetime(1990,1,1,tzinfo=UTC), datetime(2026,1,1)):
            with self.assertRaises(ValidationError):
                ReadingCreate.model_validate(measurement_payload(acquired_at=timestamp))

    def test_manufacturer_range_evidence_is_retained(self):
        payload = measurement_payload(variables={"nitrogen": {"raw_value": 2000, "unit": "mg/kg", "analyte": "N",
                                                            "declared_range": [0, 100], "read_status": "suspect"}})
        reading = ReadingCreate.model_validate(payload)
        self.assertEqual(reading.nitrogen, 2000)
        self.assertEqual(reading.measurement.variables["nitrogen"].read_status, "suspect")

    def test_sync_measurement_identity_is_not_reusable(self):
        identity = uuid.uuid4()
        reading = ReadingCreate.model_validate({**measurement_payload(), "measurement_id": identity})
        self.assertEqual(reading.orm_values(entity_id=identity)["id"], identity)
        with self.assertRaises(ValueError):
            reading.orm_values(entity_id=uuid.uuid4())

    def test_location_requires_consent_precision_and_real_coordinates(self):
        location = {"consent": True, "latitude": 14, "longitude": -90, "accuracy_m": 12}
        self.assertIsNotNone(ReadingCreate.model_validate(measurement_payload(location=location)).measurement.location)
        for change in ({"consent": False}, {"consent": 1}, {"latitude": 91}, {"accuracy_m": -1}):
            with self.assertRaises(ValidationError):
                ReadingCreate.model_validate(measurement_payload(location={**location, **change}))

    def test_contract_version_is_integer_not_boolean_or_float(self):
        for value in (True, 1.0, "1", 2):
            with self.assertRaises(ValidationError):
                ReadingCreate.model_validate(measurement_payload(contract_version=value))

    def test_bounded_raw_frame_and_ordered_range(self):
        for frame in ("0", "GG", "00"*257):
            with self.assertRaises(ValidationError):
                ReadingCreate.model_validate(measurement_payload(frame_hex=frame))
        for bounds in ([1,1], [2,1], [0, math.inf]):
            with self.assertRaises(ValidationError):
                ReadingCreate.model_validate(measurement_payload(variables={"nitrogen": {
                    "raw_value": 15, "unit": "mg/kg", "analyte": "N", "declared_range": bounds}}))

    def test_adapter_preserves_originals_and_missing_variable_is_a_gap(self):
        prototype = measurement_payload()
        base = datetime.now(UTC)-timedelta(minutes=1)
        rows = []
        # There are five N samples, but a real intermediate humidity-only
        # acquisition at the same point must prevent a fake five-sample window.
        for i, value in enumerate((15.2, 15.4, None, 45, 15.5, 15.3)):
            payload = copy.deepcopy(prototype)
            payload["measurement"]["acquired_at"] = (base+timedelta(seconds=i)).isoformat()
            if value is None:
                payload["measurement"]["variables"] = {"humidity": {"raw_value": 50, "unit": "%", "analyte": "humidity"}}
            else:
                payload["measurement"]["variables"]["nitrogen"]["raw_value"] = value
            parsed = ReadingCreate.model_validate(payload)
            rows.append(SimpleNamespace(id=uuid.uuid4(), **parsed.orm_values(), received_at=base+timedelta(minutes=1)))
        originals = copy.deepcopy([row.measurement for row in rows])
        result = process_originals(rows)
        self.assertEqual(result[str(rows[3].id)]["nitrogen"]["filtered"], 45)
        self.assertNotIn("nitrogen", result[str(rows[2].id)])
        self.assertEqual(originals, [row.measurement for row in rows])
