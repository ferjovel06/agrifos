import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

from app.services.sensor_calibration import (
    CalibrationError, CalibrationPair, CalibrationScope, apply_profile,
    error_metrics, profile_from_dict, profile_to_dict, retire_profile,
    train_candidate, validate_candidate,
)

SCOPE = CalibrationScope(("device",), ("parcel",), ("clay",))


def pairs(*, multiple=False, synthetic=True, identity=False):
    # Independent artificial physical samples; deliberately not production data.
    x = [1, 2, 3, 4, 5, 6, 2.5, 4.5]
    moisture = [5, 9, 6, 10, 7, 12, 8, 11]
    return [CalibrationPair(str(i), "N", value,
                            value if identity else 2 + 3 * value + (0.5 * moisture[i] if multiple else 0),
                            "mg/kg", "synthetic-comparable-test", "dry_mass", "test fixture only",
                            predictors=(("humidity", moisture[i]),) if multiple else (),
                            predictor_units=(("humidity", "%"),) if multiple else (),
                            device_id="device", parcel_id="parcel", soil_type="clay", synthetic=synthetic)
            for i, value in enumerate(x)]


def candidate(data=None, **overrides):
    params = dict(profile_id="test-profile", version=1, analyte="N", unit="mg/kg",
                  scope=SCOPE, holdout_group_ids=("6", "7"),
                  training_evidence="synthetic validation of implementation, not agriculture",
                  trained_at=datetime(2026, 10, 9, tzinfo=timezone.utc))
    params.update(overrides)
    return train_candidate(data or pairs(), **params)


def validated_fixture(**kwargs):
    # Exercise the real-data gate in isolation; never stored or activated by tests.
    data = pairs(synthetic=False, **kwargs)
    return validate_candidate(candidate(data, predictor_names=("humidity",) if kwargs.get("multiple") else ()), data,
                              validation_evidence="test of server validation only")


class SensorCalibrationTests(unittest.TestCase):
    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(CalibrationError) as context:
            function(*args, **kwargs)
        self.assertEqual(context.exception.code, code)

    def test_known_simple_and_multiple_coefficients_are_independent_per_analyte(self):
        n = candidate()
        self.assertAlmostEqual(n.coefficients[0], 2)
        self.assertAlmostEqual(n.coefficients[1], 3)
        data = pairs(multiple=True)
        multi = candidate(data, predictor_names=("humidity",))
        for actual, expected in zip(multi.coefficients, (2, 3, 0.5)):
            self.assertAlmostEqual(actual, expected)
        p = candidate([replace(row, analyte="P", reference_value=10 + row.sensor_value * 0.2)
                       for row in pairs()], analyte="P")
        self.assertAlmostEqual(p.coefficients[0], 10)
        self.assertAlmostEqual(p.coefficients[1], 0.2)
        self.assertNotEqual(n.coefficients, p.coefficients)

    def test_bias_only_candidate_calculates_offset_and_fixed_slope(self):
        model = candidate([replace(p, reference_value=p.sensor_value + 7) for p in pairs()], model_kind="bias")
        self.assertEqual(model.coefficients, (7, 1))

    def test_repeated_samples_have_one_group_vote_and_never_leak(self):
        data = pairs()
        repeated = data + [replace(data[0], sensor_value=data[0].sensor_value)] * 30
        one, many = candidate(data), candidate(repeated)
        self.assertEqual(one.coefficients, many.coefficients)
        self.assertEqual(many.train_group_ids, ("0", "1", "2", "3", "4", "5"))
        self.assertFalse(set(many.train_group_ids).intersection(many.holdout_group_ids))
        only_four = [replace(p, sample_group_id=str(i % 4)) for i, p in enumerate(data)] * 10
        self.assert_code("INSUFFICIENT_INDEPENDENT_GROUPS", candidate, only_four, holdout_group_ids=("2", "3"))

    def test_holdout_cannot_influence_coefficients(self):
        data = pairs()
        altered = [replace(p, reference_value=1000) if p.sample_group_id in {"6", "7"} else p for p in data]
        self.assertEqual(candidate(data).coefficients, candidate(altered).coefficients)

    def test_synthetic_candidate_cannot_be_promoted_or_applied(self):
        model, data = candidate(), pairs()
        self.assert_code("SYNTHETIC_PROFILE_CANNOT_BE_VALIDATED", validate_candidate, model, data, validation_evidence="test")
        self.assert_code("MODEL_NOT_VALIDATED", apply_profile, model, analyte="N", unit="mg/kg", device_id="device", parcel_id="parcel", soil_type="clay", sensor_value=3)

    def test_server_validation_computes_metrics_and_beats_raw_baseline(self):
        model = validated_fixture()
        self.assertEqual(model.state, "validated")
        self.assertEqual(model.calibrated_metrics.count, 2)
        self.assertAlmostEqual(model.calibrated_metrics.rmse, 0)
        self.assertAlmostEqual(model.calibrated_metrics.r2, 1)
        self.assertGreater(model.baseline_metrics.mae, model.calibrated_metrics.mae)
        self.assertGreater(model.baseline_metrics.rmse, model.calibrated_metrics.rmse)
        self.assert_code("NO_INDEPENDENT_IMPROVEMENT", validate_candidate,
                         candidate(pairs(synthetic=False, identity=True)),
                         pairs(synthetic=False, identity=True), validation_evidence="test")

    def test_insufficient_missing_and_collinear_data(self):
        self.assert_code("INSUFFICIENT_INDEPENDENT_GROUPS", candidate, pairs()[:4], holdout_group_ids=("2", "3"))
        self.assert_code("MISSING_PREDICTOR", candidate, pairs(), predictor_names=("humidity",))
        constant = [replace(p, sensor_value=1) for p in pairs()]
        self.assert_code("COLLINEAR_PREDICTORS", candidate, constant)
        collinear = [replace(p, predictors=(("humidity", p.sensor_value * 2),), predictor_units=(("humidity", "%"),)) for p in pairs()]
        self.assert_code("COLLINEAR_PREDICTORS", candidate, collinear, predictor_names=("humidity",))

    def test_comparability_units_and_context_are_required(self):
        for changes, code in (({"analyte": "NO3"}, "INCOMPATIBLE_ANALYTE_OR_UNIT"),
                              ({"unit": "mg/L"}, "INCOMPATIBLE_ANALYTE_OR_UNIT"),
                              ({"reference_method": ""}, "REFERENCE_COMPARABILITY_NOT_DOCUMENTED"),
                              ({"comparability_evidence": ""}, "REFERENCE_COMPARABILITY_NOT_DOCUMENTED"),
                              ({"device_id": "unknown"}, "DEVICE_OUTSIDE_SCOPE")):
            data = pairs()
            data[0] = replace(data[0], **changes)
            self.assert_code(code, candidate, data)
        data = pairs()
        data[0] = replace(data[0], reference_method="different extraction method")
        self.assert_code("REFERENCE_METHOD_OR_UNITS_MISMATCH", candidate, data)
        self.assert_code("INCOMPATIBLE_ANALYTE_OR_UNIT", candidate,
                         [replace(p, analyte="unidentified") for p in pairs()], analyte="unidentified")
        self.assert_code("INCOMPATIBLE_ANALYTE_OR_UNIT", candidate,
                         [replace(p, unit="unknown") for p in pairs()], unit="unknown")

    def test_dataset_change_and_leakage_reject_promotion(self):
        data = pairs(synthetic=False)
        model = candidate(data)
        changed = [replace(p, reference_value=p.reference_value + 1) for p in data]
        self.assert_code("CALIBRATION_DATA_CHANGED", validate_candidate, model, changed, validation_evidence="test")
        self.assert_code("VALIDATION_GROUP_LEAKAGE", validate_candidate, replace(model, train_group_ids=model.train_group_ids + ("6",)), data, validation_evidence="test")
        self.assert_code("MODEL_TRAINING_MISMATCH", validate_candidate,
                         replace(model, coefficients=(2.1, 3)), data, validation_evidence="test")

    def test_qr_solver_handles_large_sensor_offset_without_normal_equations(self):
        data = [replace(p, sensor_value=p.sensor_value + 1e9,
                        reference_value=2 + 3 * (p.sensor_value + 1e9)) for p in pairs()]
        model = candidate(data)
        self.assertAlmostEqual(model.coefficients[1], 3, places=5)
        # Prediction is the stable quantity; intercept uncertainty at huge offsets
        # cannot be interpreted as a calibrated laboratory uncertainty estimate.
        predicted = model.coefficients[0] + model.coefficients[1] * (1e9 + 3)
        self.assertAlmostEqual(predicted, 2 + 3 * (1e9 + 3), places=4)

    def test_holdout_subgroup_worsening_prevents_promotion(self):
        # Bias=10 fits training. The majority holdout improves, but one soil
        # subgroup already matched the raw sensor and becomes worse.
        data = [replace(p, reference_value=p.sensor_value + 10, soil_type="clay") for p in pairs(synthetic=False)]
        data[6] = replace(data[6], reference_value=data[6].sensor_value + 20)
        data[7] = replace(data[7], reference_value=data[7].sensor_value, soil_type="sand")
        data.append(replace(data[6], sample_group_id="8", sensor_value=4, reference_value=14))
        scope = replace(SCOPE, soil_types=("clay", "sand"))
        model = candidate(data, model_kind="bias", scope=scope, holdout_group_ids=("6", "7", "8"))
        self.assert_code("SUBGROUP_ERROR_WORSENED", validate_candidate, model, data, validation_evidence="test")

    def test_apply_validates_scope_units_version_missing_and_extrapolation(self):
        model = validated_fixture(multiple=True)
        options = dict(analyte="N", unit="mg/kg", device_id="device", parcel_id="parcel", soil_type="clay", sensor_value=3,
                       predictors={"humidity": 8}, predictor_units={"humidity": "%"}, expected_version=1)
        result = apply_profile(model, **options)
        self.assertAlmostEqual(result.value, 15)
        self.assertIsNone(result.uncertainty)
        cases = (({"analyte": "NO3-N"}, "INCOMPATIBLE_ANALYTE_OR_UNIT"),
                 ({"unit": "mg/L"}, "INCOMPATIBLE_ANALYTE_OR_UNIT"),
                 ({"device_id": "other"}, "DEVICE_OUTSIDE_SCOPE"),
                 ({"parcel_id": "other"}, "PARCEL_OUTSIDE_SCOPE"),
                 ({"soil_type": "sand"}, "SOIL_OUTSIDE_SCOPE"),
                 ({"sensor_value": 100}, "EXTRAPOLATION_NOT_ALLOWED"),
                 ({"expected_version": 2}, "MODEL_VERSION_MISMATCH"),
                 ({"predictors": {}}, "MISSING_PREDICTOR"),
                 ({"predictor_units": {"humidity": "fraction"}}, "PREDICTOR_UNIT_MISMATCH"))
        for change, code in cases:
            self.assert_code(code, apply_profile, model, **(options | change))
        self.assert_code("MODEL_NOT_VALIDATED", apply_profile, retire_profile(model), **options)

    def test_reprocessing_returns_versioned_derivations_and_preserves_original(self):
        original = 3.0
        one = validated_fixture()
        data = [replace(p, reference_value=p.reference_value + 1) for p in pairs(synthetic=False)]
        two = validate_candidate(candidate(data, version=2), data, validation_evidence="test of version 2")
        options = dict(analyte="N", unit="mg/kg", device_id="device", parcel_id="parcel", soil_type="clay", sensor_value=original)
        before, after = apply_profile(one, **options), apply_profile(two, **options)
        self.assertEqual(original, 3)
        self.assertEqual((before.profile_version, after.profile_version), (1, 2))
        self.assertAlmostEqual(after.value - before.value, 1)
        self.assertAlmostEqual(before.value, 11)
        with self.assertRaises(FrozenInstanceError):
            one.state = "retired"

    def test_profile_round_trip_and_constant_reference_r2(self):
        model = validated_fixture()
        self.assertEqual(profile_from_dict(profile_to_dict(model)), model)
        result = error_metrics([2, 3], [3, 3])
        self.assertEqual(result.mae, 0.5)
        self.assertAlmostEqual(result.rmse, 2 ** -0.5)
        self.assertEqual(result.bias, -0.5)
        self.assertIsNone(result.r2)

    def test_calibration_scope_checks_decoder_protocol_model_and_known_depth(self):
        data = [replace(p, sensor_model="model-a", protocol_version="wire-v1",
                        acquisition_profile_id="decoder-v1", depth_cm=10) for p in pairs(synthetic=False)]
        scope = replace(SCOPE, measurement_contexts=(("model-a", "wire-v1", "decoder-v1"),), depth_range=(10, 10))
        model = validate_candidate(candidate(data, scope=scope), data, validation_evidence="test only")
        options = dict(analyte="N", unit="mg/kg", device_id="device", parcel_id="parcel",
                       soil_type="clay", sensor_value=3, sensor_model="model-a",
                       protocol_version="wire-v1", acquisition_profile_id="decoder-v1", depth_cm=10)
        self.assertAlmostEqual(apply_profile(model, **options).value, 11)
        for key in ("sensor_model", "protocol_version", "acquisition_profile_id"):
            for change in (None, "different"):
                self.assert_code("ACQUISITION_CONTEXT_OUTSIDE_SCOPE", apply_profile, model, **(options | {key: change}))
        for depth in (None, 9, 11):
            self.assert_code("DEPTH_OUTSIDE_SCOPE", apply_profile, model, **(options | {"depth_cm": depth}))
        self.assertEqual(profile_from_dict(profile_to_dict(model)), model)
        mismatch = data + [replace(data[0], acquisition_profile_id="other")]
        self.assert_code("ACQUISITION_CONTEXT_OUTSIDE_SCOPE", candidate, mismatch, scope=scope)


if __name__ == "__main__":
    unittest.main()
