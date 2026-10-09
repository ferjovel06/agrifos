import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import nan

from app.services.measurement_processing import (
    MeasurementSample, ProcessingConfig, centered_filter, process_measurements,
    series_metrics,
)


def samples(values, **overrides):
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    return [replace(MeasurementSample(str(i), "session", "device", "parcel", "point",
                                     "N", value, "mg/kg", now + timedelta(seconds=i),
                                     now + timedelta(minutes=1)), **overrides)
            for i, value in enumerate(values)]


class MeasurementProcessingTests(unittest.TestCase):
    def test_five_same_point_spike_uses_centered_median_without_edge_padding(self):
        raw = samples([15.2, 15.4, 45.0, 15.5, 15.3])
        result = process_measurements(raw, ProcessingConfig(mad_multiplier=3.5,
                                                           threshold_evidence="synthetic test rule"))
        self.assertEqual([s.filtered for s in result], [15.2, 15.4, 15.4, 15.5, 15.3])
        self.assertIn("MAD_OUTLIER", result[2].reason_codes)
        self.assertEqual(result[2].raw.value, 45.0)
        self.assertEqual(result[2].accuracy_state, "uncalibrated")
        self.assertEqual(result[2].transmission_state, "valid")
        self.assertEqual(result[2].repeatability_state, "suspect")
        self.assertIn("CENTERED_WINDOW_EDGE", result[0].reason_codes)
        self.assertNotIn("CENTERED_WINDOW_EDGE", result[2].reason_codes)

    def test_mean_and_none_are_comparable_and_reference_errors_are_explicit(self):
        values = [15.2, 15.4, 45.0, 15.5, 15.3]
        mean, applied = centered_filter(values, method="mean")
        median, _ = centered_filter(values)
        self.assertAlmostEqual(mean[2], 21.28)
        self.assertEqual(applied, [False, False, True, False, False])
        self.assertLess(series_metrics(median, [15.4] * 5)["mae"], series_metrics(mean, [15.4] * 5)["mae"])
        self.assertLess(series_metrics(mean, [15.4] * 5)["mae"], series_metrics(values, [15.4] * 5)["mae"])
        self.assertNotIn("mae", series_metrics(values))
        self.assertEqual(centered_filter(values, method="none")[0], values)

    def test_short_series_preserves_originals_and_limitation(self):
        result = process_measurements(samples([1, 100]))
        self.assertEqual([r.filtered for r in result], [1, 100])
        self.assertTrue(all("INSUFFICIENT_REPETITIONS" in r.reason_codes for r in result))

    def test_actual_spatial_step_is_not_smoothed_or_flagged_as_mad_noise(self):
        raw = samples([10] * 5 + [100] * 5)
        raw = [replace(s, point_id="a" if i < 5 else "b") for i, s in enumerate(raw)]
        result = process_measurements(raw)
        self.assertEqual([r.filtered for r in result], [10] * 5 + [100] * 5)
        self.assertFalse(any("MAD_OUTLIER" in r.reason_codes for r in result))

    def test_interleaved_analytes_have_independent_same_point_windows(self):
        nitrogen = samples([15.2, 15.4, 45, 15.5, 15.3])
        phosphorus = [replace(p, analyte="P", value=2) for p in nitrogen]
        interleaved = [sample for pair in zip(nitrogen, phosphorus) for sample in pair]
        result = process_measurements(interleaved)
        self.assertEqual(result[4].filtered, 15.4)
        self.assertEqual(result[5].filtered, 2)
        self.assertEqual(result[4].raw.value, 45)

    def test_no_filtering_across_different_sessions_contexts_or_units(self):
        for attribute, alternate in (("session_id", "other"), ("device_id", "other"),
                                     ("parcel_id", "other"), ("analyte", "NO3-N"),
                                     ("unit", "mg/L"), ("depth_cm", 20),
                                     ("protocol_version", "other"), ("device_model", "other")):
            with self.subTest(attribute=attribute):
                raw = samples([1, 1, 100, 1, 1])
                raw[2] = replace(raw[2], **{attribute: alternate})
                self.assertEqual(process_measurements(raw)[2].filtered, 100)

    def test_revisit_point_and_missing_point_do_not_join_repetitions(self):
        raw = samples([1, 1, 100, 1, 1])
        raw[2] = replace(raw[2], point_id="b")
        self.assertEqual(process_measurements(raw)[2].filtered, 100)
        result = process_measurements(samples([1, 1, 100, 1, 1], point_id=None))
        self.assertEqual(result[2].filtered, 100)
        self.assertIn("PHYSICAL_CONTEXT_INCOMPLETE", result[2].reason_codes)

    def test_mad_zero_marks_deviation_without_dividing_by_zero(self):
        result = process_measurements(samples([1, 1, 100, 1, 1]))
        self.assertEqual(result[2].group_mad, 0)
        self.assertIn("ZERO_MAD_DEVIATION", result[2].reason_codes)
        self.assertEqual(result[2].quality_state, "suspect")
        self.assertIn("CONSTANT_REPETITIONS", process_measurements(samples([1] * 5))[2].reason_codes)

    def test_no_manufacturer_limits_are_invented_and_units_are_checked(self):
        self.assertNotIn("OUTSIDE_DECLARED_RANGE", process_measurements(samples([1000000]))[0].reason_codes)
        result = process_measurements(samples([100], declared_range=(0, 10)))
        self.assertIn("OUTSIDE_DECLARED_RANGE", result[0].reason_codes)
        self.assertEqual(result[0].quality_state, "invalid")
        for unit, reason in (("degC", "INCOMPATIBLE_UNIT"), ("mystery", "UNKNOWN_UNIT")):
            self.assertIn(reason, process_measurements(samples([1], unit=unit))[0].reason_codes)
        self.assertIn("ANALYTE_UNIDENTIFIED", process_measurements(samples([1], analyte="unidentified"))[0].reason_codes)
        self.assertEqual(process_measurements(samples([1], analyte="ec", unit="dS/m"))[0].quality_state, "valid")

    def test_bad_transmission_nonfinite_missing_duplicates_and_timestamps(self):
        for value, status, reason in ((nan, "valid", "NON_FINITE_VALUE"),
                                      (None, "valid", "MISSING_VALUE"),
                                      (1, "crc_error", "TRANSMISSION_CRC_ERROR"),
                                      (1, "timeout", "TRANSMISSION_TIMEOUT"),
                                      (1, "disconnected", "TRANSMISSION_DISCONNECTED"),
                                      (1, "incomplete", "TRANSMISSION_INCOMPLETE")):
            result = process_measurements(samples([value], reading_status=status))[0]
            self.assertIn(reason, result.reason_codes)
            self.assertEqual(result.transmission_state, "invalid")
        raw = samples([1, 2])
        raw[1] = replace(raw[1], measurement_id=raw[0].measurement_id)
        self.assertTrue(all("DUPLICATE_MEASUREMENT_ID" in r.reason_codes for r in process_measurements(raw)))
        naive = datetime(2026, 1, 1)
        self.assertIn("TIMESTAMP_WITHOUT_TIMEZONE", process_measurements(samples([1], acquired_at=naive))[0].reason_codes)
        raw = samples([1, 2])
        raw[1] = replace(raw[1], acquired_at=raw[0].acquired_at)
        self.assertIn("NON_INCREASING_TIMESTAMP", process_measurements(raw)[1].reason_codes)

    def test_invalid_gap_does_not_blend_values_and_raw_reprocessing_is_immutable(self):
        raw = samples([1, 1, nan, 100, 100])
        first = process_measurements(raw)
        second = process_measurements(raw, ProcessingConfig(method="mean"))
        self.assertEqual(first[3].filtered, 100)
        self.assertIs(first[3].raw, raw[3])
        self.assertIs(second[3].raw, raw[3])
        self.assertEqual(raw[3].value, 100)

    def test_missing_channel_placeholder_with_different_key_ends_same_point_run(self):
        raw = samples([15.2, 15.4, None, 45, 15.5, 15.3])
        raw[2] = replace(raw[2], analyte="nitrogen", unit="", reading_status="invalid")
        result = process_measurements(raw)
        self.assertEqual(result[3].filtered, 45)
        self.assertIn("INSUFFICIENT_REPETITIONS", result[3].reason_codes)

    def test_stability_and_thresholds_need_documented_configuration(self):
        with self.assertRaises(ValueError):
            ProcessingConfig(max_jump=20)
        for window in (2, 4, 0):
            with self.assertRaises(ValueError):
                ProcessingConfig(window=window)
        result = process_measurements(samples([1, 2, 3, 100, 1]), ProcessingConfig(
            minimum_stabilization_seconds=2, max_jump=20, max_mad=0.5,
            threshold_evidence="empirical test fixture only"))
        self.assertIn("INSUFFICIENT_STABILIZATION", result[0].reason_codes)
        self.assertNotIn("INSUFFICIENT_STABILIZATION", result[2].reason_codes)
        self.assertIn("ABRUPT_JUMP", result[3].reason_codes)
        self.assertIn("EXCESS_REPEATABILITY_DISPERSION", result[0].reason_codes)


if __name__ == "__main__":
    unittest.main()
